"""Job queue for HTTP-driven detections.

Wraps the same Runner the CLI uses. Single uvicorn worker, in-process state
guarded by an asyncio lock. Job metadata and completed reports are persisted so
server restarts produce an explicit terminal state instead of losing active
jobs. API keys are NEVER persisted — the raw key only lives in the task
coroutine until the run finishes.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from relay_detector.models import (
    DetectionReport,
    DetectionTier,
    DetectorResult,
    ExecutionConfig,
    Mode,
    PerformanceMetrics,
    Protocol,
    UsageMetrics,
    mask_api_key,
)
from relay_detector.scorer import (
    compute_total,
    effective_verdict,
    fatal_run_error,
    summary_text,
)


JobStatus = Literal["queued", "running", "done", "error"]

# Production default; override via VERIDROP_JOBS_DIR in tests / dev so the
# import doesn't try to mkdir into /opt/veridrop on a developer laptop.
JOBS_DIR = Path(
    os.environ.get("VERIDROP_JOBS_DIR", "/opt/veridrop/web_data/jobs")
)
JOBS_DIR.mkdir(parents=True, exist_ok=True)

# Cap concurrent detections so a flood of submissions doesn't exhaust file
# descriptors or get the upstream Anthropic API rate-limited. Each detection
# already runs ~13 outbound requests in parallel, so 6 inflight = ~78 sockets.
_MAX_INFLIGHT = 6
_SEMA = asyncio.Semaphore(_MAX_INFLIGHT)
_STATE_DIR_NAME = "_state"
_DEFAULT_JOB_TIMEOUTS_S = {
    "quick": 180.0,
    "standard": 480.0,
    "full": 720.0,
}


@dataclass
class Job:
    id: str
    protocol: str = "anthropic"
    status: JobStatus = "queued"
    base_url: str = ""
    target_model: str = ""
    mode: str = "full"
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    report: dict[str, Any] | None = None
    error: str | None = None


_JOBS: dict[str, Job] = {}
_LOCK = asyncio.Lock()


def _new_job_id() -> str:
    # 8-char URL-safe id; secrets gives ~48 bits of entropy, fine for an
    # unguessable shareable link without auth.
    return secrets.token_urlsafe(6)


def state_path(job_id: str) -> Path:
    return JOBS_DIR / _STATE_DIR_NAME / f"{job_id}.json"


def _persist_job(job: Job) -> None:
    path = state_path(job.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "id": job.id,
        "protocol": job.protocol,
        "status": job.status,
        "base_url": job.base_url,
        "target_model": job.target_model,
        "mode": job.mode,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "error": job.error,
    }
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def _safe_error_message(error: Exception, api_key: str) -> str:
    message = f"{type(error).__name__}: {error}"
    if api_key:
        message = message.replace(api_key, "[REDACTED]")
    message = re.sub(r"(?i)(bearer\s+)[^\s,;\"']+", r"\1[REDACTED]", message)
    message = re.sub(r"\b(?:sk|key)-[A-Za-z0-9._-]{8,}\b", "[REDACTED]", message)
    return message[:500]


def _load_persisted_job(path: Path) -> Job | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        status = payload.get("status")
        if status not in {"queued", "running", "done", "error"}:
            return None
        return Job(
            id=str(payload["id"]),
            protocol=str(payload.get("protocol") or "anthropic"),
            status=status,
            base_url=str(payload.get("base_url") or ""),
            target_model=str(payload.get("target_model") or ""),
            mode=str(payload.get("mode") or "full"),
            created_at=float(payload.get("created_at") or time.time()),
            started_at=_optional_float(payload.get("started_at")),
            finished_at=_optional_float(payload.get("finished_at")),
            error=str(payload["error"]) if payload.get("error") else None,
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, OSError):
        return None


def recover_interrupted_jobs() -> int:
    state_dir = JOBS_DIR / _STATE_DIR_NAME
    if not state_dir.exists():
        return 0
    recovered = 0
    for path in state_dir.glob("*.json"):
        job = _load_persisted_job(path)
        if job is None:
            continue
        if job.status in {"queued", "running"}:
            job.status = "error"
            job.error = "ServiceRestarted: detection interrupted by service restart"
            job.finished_at = time.time()
            _persist_job(job)
            recovered += 1
        _JOBS[job.id] = job
    return recovered


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _job_timeout_seconds(
    mode: str,
    include_long_context: bool,
    include_long_context_extreme: bool,
) -> float:
    timeout = _DEFAULT_JOB_TIMEOUTS_S.get(mode, _DEFAULT_JOB_TIMEOUTS_S["full"])
    if include_long_context_extreme:
        return max(timeout, 1200.0)
    if include_long_context:
        return max(timeout, 600.0)
    return timeout


recover_interrupted_jobs()


async def submit(
    base_url: str,
    api_key: str,
    model: str,
    mode: str,
    protocol: str = "anthropic",
    include_long_context: bool = False,
    include_long_context_extreme: bool = False,
) -> str:
    """Queue a detection job and return the job id immediately.

    Long-context probe is opt-in. Two tiers:
      - ``include_long_context`` (standard): 32k/100k/200k probes,
        $0.05–$0.50 upstream cost, 30–90s extra wall time.
      - ``include_long_context_extreme`` (adaptive): probes proportionally
        up to the model's advertised limit (e.g. 32k→500k→950k for 1M
        models). $0.05–$8 cost, 30s–5min wall time. Catches "advertised X
        but capped at Y<X" fraud that the standard tier misses on big
        models. Implies standard (it's a superset).
    """
    job_id = _new_job_id()
    job = Job(
        id=job_id,
        protocol=protocol,
        base_url=base_url,
        target_model=model,
        mode=mode,
    )
    async with _LOCK:
        _JOBS[job_id] = job
        _persist_job(job)
    asyncio.create_task(
        _run_with_timeout(
            job_id, base_url, api_key, model, mode, protocol,
            include_long_context, include_long_context_extreme,
        )
    )
    return job_id


async def get(job_id: str) -> Job | None:
    """Look up a job by id. Falls back to disk for jobs that survived a restart."""
    async with _LOCK:
        j = _JOBS.get(job_id)
    if j is not None:
        if j.status != "done" or j.report is not None:
            return j
    report = None
    for path in _report_candidates(job_id):
        if not path.exists():
            continue
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
            break
        except (json.JSONDecodeError, OSError):
            continue
    if report is None:
        persisted = _load_persisted_job(state_path(job_id))
        if persisted is not None:
            async with _LOCK:
                _JOBS[job_id] = persisted
            return persisted
        return j
    return Job(
        id=job_id,
        status="done",
        protocol=report.get("protocol", "anthropic"),
        base_url=report.get("base_url", ""),
        target_model=report.get("target_model", ""),
        mode=report.get("mode", "full"),
        created_at=time.time(),
        finished_at=time.time(),
        report=report,
    )


async def metrics() -> dict[str, int | float | None]:
    async with _LOCK:
        snapshot = list(_JOBS.values())
    counts = {status: sum(job.status == status for job in snapshot) for status in ("queued", "running", "done", "error")}
    active = [job for job in snapshot if job.status in {"queued", "running"}]
    oldest_active_age_s = (
        max(0.0, time.time() - min(job.created_at for job in active))
        if active
        else None
    )
    return {
        **counts,
        "active": counts["queued"] + counts["running"],
        "known_jobs": len(snapshot),
        "max_inflight": _MAX_INFLIGHT,
        "oldest_active_age_s": oldest_active_age_s,
    }


def report_path(job_id: str, protocol: str) -> Path:
    protocol_dir = JOBS_DIR / protocol
    protocol_dir.mkdir(parents=True, exist_ok=True)
    return protocol_dir / f"{job_id}.json"


def image_path(job_id: str, protocol: str) -> Path:
    protocol_dir = JOBS_DIR / protocol
    protocol_dir.mkdir(parents=True, exist_ok=True)
    return protocol_dir / f"{job_id}.jpg"


def _report_candidates(job_id: str) -> list[Path]:
    return [
        JOBS_DIR / f"{job_id}.json",
        JOBS_DIR / "anthropic" / f"{job_id}.json",
        JOBS_DIR / "openai" / f"{job_id}.json",
        JOBS_DIR / "openai_responses" / f"{job_id}.json",
        JOBS_DIR / "gemini" / f"{job_id}.json",
    ]


async def _run_with_timeout(
    job_id: str,
    base_url: str,
    api_key: str,
    model: str,
    mode: str,
    protocol: str,
    include_long_context: bool = False,
    include_long_context_extreme: bool = False,
) -> None:
    timeout_s = _job_timeout_seconds(
        mode,
        include_long_context,
        include_long_context_extreme,
    )
    try:
        await asyncio.wait_for(
            _run(
                job_id,
                base_url,
                api_key,
                model,
                mode,
                protocol,
                include_long_context,
                include_long_context_extreme,
            ),
            timeout=timeout_s,
        )
    except asyncio.TimeoutError:
        async with _LOCK:
            job = _JOBS.get(job_id)
            if job is not None and job.status in {"queued", "running"}:
                job.status = "error"
                job.error = f"TimeoutError: detection exceeded {int(timeout_s)} seconds"
                job.finished_at = time.time()
                _persist_job(job)


async def _run(
    job_id: str,
    base_url: str,
    api_key: str,
    model: str,
    mode: str,
    protocol: str,
    include_long_context: bool = False,
    include_long_context_extreme: bool = False,
) -> None:
    async with _SEMA:
        async with _LOCK:
            j = _JOBS.get(job_id)
            if j is None:
                return
            j.status = "running"
            j.started_at = time.time()
            _persist_job(j)

        try:
            cfg = ExecutionConfig.for_mode(Mode(mode), max_concurrent=3)
            cfg.include_long_context = include_long_context
            cfg.include_long_context_extreme = include_long_context_extreme
            # Long-context probes blow past the regular per-mode wall-clock
            # budget (60–180s). 1M-token requests alone take 2–4 minutes
            # upstream; the extreme path may also sleep 75s per tier waiting
            # for an OpenAI/Anthropic TPM window to reset before retrying
            # rate-limited probes (see _probe_tier_with_tpm_retry).
            # Without this bump asyncio.wait_for kills the runner
            # mid-detector and the user gets a misleading "fail" instead.
            if include_long_context_extreme:
                cfg.overall_timeout_s = max(cfg.overall_timeout_s, 900.0)
            elif include_long_context:
                cfg.overall_timeout_s = max(cfg.overall_timeout_s, 300.0)
            if protocol == "openai":
                outcome = await _run_openai(base_url, api_key, model, cfg)
                report_protocol = Protocol.OPENAI
                report_tier = DetectionTier.BEHAVIORAL
                tier_title = "行为/协议级验证"
                tier_message = (
                    "本检测无法可靠区分高配模型真品与低配模型伪装。"
                    "我们检测的是中转站接口是否符合 OpenAI Chat Completions 协议规范、"
                    "能力是否完整、usage 字段是否符合官方响应形状。"
                )
            elif protocol == "openai_responses":
                outcome = await _run_openai_responses(base_url, api_key, model, cfg)
                report_protocol = Protocol.OPENAI_RESPONSES
                report_tier = DetectionTier.BEHAVIORAL
                tier_title = "行为/协议级验证"
                tier_message = (
                    "本检测通过 OpenAI Responses API (POST /v1/responses) 探测中转站。"
                    "它会检查 response 对象形状、output 内容、结构化输出、工具调用和 usage 字段。"
                    "适合 Codex 等使用 Responses API 的 Agent 工具链,但仍不等同于加密级模型真伪证明。"
                )
            elif protocol == "gemini":
                outcome = await _run_gemini(base_url, api_key, model, cfg)
                report_protocol = Protocol.GEMINI
                report_tier = DetectionTier.PROTOCOL
                tier_title = "协议级验证"
                tier_message = (
                    "本检测通过 OpenAI 兼容协议 (POST /chat/completions) 探测 Gemini 中转站,"
                    "验证响应字段、tool 调用、结构化输出、流式一致性和 usage 字段是否符合 OpenAI 规范。"
                    "它不提供加密级模型真伪证明。"
                )
            elif protocol == "anthropic":
                outcome = await _run_anthropic(base_url, api_key, model, cfg)
                report_protocol = Protocol.ANTHROPIC
                report_tier = DetectionTier.CRYPTOGRAPHIC
                tier_title = "加密级验证"
                tier_message = (
                    "Claude thinking signature 来自 Anthropic 服务端签名。"
                    "通过该项时,它是当前检测集中最高可信度的真伪信号。"
                )
            else:
                raise ValueError(f"unsupported protocol: {protocol}")

            run_error = fatal_run_error(outcome.results)
            score = 0.0 if run_error else compute_total(outcome.results)
            verdict = effective_verdict(score, outcome.results)
            summary = run_error or summary_text(score, verdict)

            self_id: str | None = None
            brands: list[str] = []
            for r in outcome.results:
                if r.name != "identity" or not isinstance(r.details, dict):
                    continue
                text = r.details.get("response_text")
                if isinstance(text, str) and text.strip():
                    self_id = text.strip()
                b = r.details.get("detected_non_anthropic_brands")
                if isinstance(b, list):
                    brands = [x for x in b if isinstance(x, str)]
                break

            report = DetectionReport(
                protocol=report_protocol,
                tier=report_tier,
                tier_title=tier_title,
                tier_message=tier_message,
                base_url=base_url,
                api_key_masked=mask_api_key(api_key),
                target_model=model,
                mode=Mode(mode),
                timestamp=datetime.now(timezone.utc),
                total_score=score,
                verdict=verdict,
                results=outcome.results,
                performance=outcome.performance,
                summary=summary,
                run_error=run_error,
                self_reported_identity=self_id,
                detected_non_anthropic_brands=brands,
            )
            report_dict = json.loads(report.model_dump_json())
            report_path(job_id, protocol).write_text(
                json.dumps(report_dict, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

            async with _LOCK:
                if job_id in _JOBS:
                    _JOBS[job_id].status = "done"
                    _JOBS[job_id].protocol = protocol
                    _JOBS[job_id].report = report_dict
                    _JOBS[job_id].finished_at = time.time()
                    _JOBS[job_id].error = None
                    _persist_job(_JOBS[job_id])

        except Exception as e:  # noqa: BLE001 — bubble error into job state
            async with _LOCK:
                if job_id in _JOBS:
                    _JOBS[job_id].status = "error"
                    _JOBS[job_id].error = _safe_error_message(e, api_key)
                    _JOBS[job_id].finished_at = time.time()
                    _persist_job(_JOBS[job_id])


async def _run_anthropic(
    base_url: str,
    api_key: str,
    model: str,
    cfg: ExecutionConfig,
):
    from relay_detector.protocols.anthropic import (
        build_detectors,
        build_runner,
        make_client,
    )

    async with make_client(base_url, api_key, timeout=cfg.request_timeout_s) as client:
        runner = build_runner(client, build_detectors(cfg.mode), cfg)
        return await runner.run(model)


async def _run_openai(
    base_url: str,
    api_key: str,
    model: str,
    cfg: ExecutionConfig,
):
    from relay_detector.protocols.openai import (
        build_detectors,
        build_runner,
        make_client,
    )

    async with make_client(base_url, api_key, timeout=cfg.request_timeout_s) as client:
        runner = build_runner(client, build_detectors(cfg.mode), cfg)
        return await runner.run(model)


async def _run_openai_responses(
    base_url: str,
    api_key: str,
    model: str,
    cfg: ExecutionConfig,
):
    from relay_detector.core.runner import RunOutcome
    from relay_detector.protocols.openai import make_client
    from relay_detector.protocols.openai.baseline import build_openai_baseline_probes

    probe_set = "smoke" if cfg.mode == Mode.QUICK else "full"
    probes = build_openai_baseline_probes(
        model,
        wire_api="responses",
        probe_set=probe_set,
    )
    results: list[DetectorResult] = []
    usage = UsageMetrics()
    total_latency_ms = 0
    request_count = 0
    backoff_events = 0

    async with make_client(base_url, api_key, timeout=cfg.request_timeout_s) as client:
        for probe in probes:
            try:
                request, response, headers, latency_ms = await client.responses_create(
                    **probe.request
                )
                request_count += 1
                total_latency_ms += latency_ms
                _absorb_responses_usage(usage, response)
                validation = _validate_openai_responses_payload(response, model)
                features = _extract_openai_responses_features(response, headers)
                score = float(validation.get("score") or 0.0)
                passed = validation.get("passed") is True
                issues = validation.get("issues") if isinstance(validation.get("issues"), list) else []
                results.append(
                    DetectorResult(
                        name=_responses_probe_result_name(probe.name),
                        display_name=_responses_probe_display_name(probe.name),
                        status="pass" if passed else "fail",
                        score=max(0.0, min(100.0, score)),
                        weight=_responses_probe_weight(probe.name),
                        duration_ms=latency_ms,
                        details={
                            "wire_api": "responses",
                            "request_model": request.get("model"),
                            "response_model": response.get("model"),
                            "validation": validation,
                            "issues": issues[:30],
                            "features": features,
                            "response_text": _responses_output_text(response)[:500],
                            "evaluation_zh": _responses_probe_evaluation(probe.name, passed, issues),
                        },
                    )
                )
            except Exception as exc:  # noqa: BLE001
                request_count += 1
                if exc.__class__.__name__ == "OpenAIAPIError":
                    status = getattr(exc, "status", "")
                    body = str(getattr(exc, "body", ""))[:600]
                    message = f"HTTP {status}: {body}" if status else str(exc)
                else:
                    message = str(exc)
                if not message:
                    message = type(exc).__name__
                results.append(
                    DetectorResult(
                        name=_responses_probe_result_name(probe.name),
                        display_name=_responses_probe_display_name(probe.name),
                        status="error",
                        score=0.0,
                        weight=_responses_probe_weight(probe.name),
                        details={
                            "wire_api": "responses",
                            "error": message,
                            "evaluation_zh": "Responses API 请求失败,该中转站可能未实现 /v1/responses 或模型不支持该协议。",
                        },
                        error=message,
                    )
                )

    return RunOutcome(
        results=results,
        performance=PerformanceMetrics(
            total_latency_ms=total_latency_ms,
            usage=usage,
            request_count=request_count,
            backoff_events=backoff_events,
        ),
    )


async def _run_gemini(
    base_url: str,
    api_key: str,
    model: str,
    cfg: ExecutionConfig,
):
    from relay_detector.protocols.gemini import (
        build_detectors,
        build_runner,
        make_client,
    )

    async with make_client(base_url, api_key, timeout=cfg.request_timeout_s) as client:
        runner = build_runner(client, build_detectors(cfg.mode), cfg)
        return await runner.run(model)


def _validate_openai_responses_payload(response: dict, model: str) -> dict:
    from relay_detector.protocols.openai.protocol_templates import validate_responses_api

    return validate_responses_api(response, request_model=model).to_dict()


def _extract_openai_responses_features(response: dict, headers) -> dict:
    from relay_detector.protocols.openai.baseline import (
        extract_openai_features,
        sanitize_openai_headers,
    )

    return extract_openai_features("responses", response, sanitize_openai_headers(headers))


def _responses_probe_result_name(probe_name: str) -> str:
    if probe_name == "responses_text":
        return "basic_request"
    if probe_name == "responses_structured_output":
        return "structured_output"
    if probe_name == "responses_tool_call":
        return "function_calling"
    return probe_name


def _responses_probe_display_name(probe_name: str) -> str:
    if probe_name == "responses_text":
        return "基础请求"
    if probe_name == "responses_structured_output":
        return "结构化输出"
    if probe_name == "responses_tool_call":
        return "函数调用"
    return probe_name


def _responses_probe_weight(probe_name: str) -> float:
    if probe_name == "responses_text":
        return 30.0
    if probe_name == "responses_structured_output":
        return 35.0
    if probe_name == "responses_tool_call":
        return 35.0
    return 10.0


def _responses_probe_evaluation(probe_name: str, passed: bool, issues: list) -> str:
    if passed:
        if probe_name == "responses_text":
            return "Responses 基础请求正常: 响应对象、output 文本和 usage 字段符合预期。"
        if probe_name == "responses_structured_output":
            return "Responses 结构化输出正常: text.format=json_schema 被透传并返回有效 JSON。"
        if probe_name == "responses_tool_call":
            return "Responses 工具调用正常: 返回 function_call 类型 output,工具名和参数形状符合预期。"
        return "Responses probe 通过。"
    if issues:
        return f"Responses 协议形状存在 {len(issues)} 条问题。"
    return "Responses probe 未通过。"


def _responses_output_text(response: dict) -> str:
    output = response.get("output") if isinstance(response.get("output"), list) else []
    texts: list[str] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        for content in item.get("content") or []:
            if isinstance(content, dict) and isinstance(content.get("text"), str):
                texts.append(content["text"])
    return "\n".join(texts)


def _absorb_responses_usage(total: UsageMetrics, response: dict) -> None:
    usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
    delta = UsageMetrics()
    input_tokens = usage.get("input_tokens")
    output_tokens = usage.get("output_tokens")
    if isinstance(input_tokens, int) and not isinstance(input_tokens, bool):
        delta.input_tokens = input_tokens
    if isinstance(output_tokens, int) and not isinstance(output_tokens, bool):
        delta.output_tokens = output_tokens

    input_details = usage.get("input_tokens_details")
    if isinstance(input_details, dict):
        cached = input_details.get("cached_tokens")
        if isinstance(cached, int) and not isinstance(cached, bool):
            delta.cache_read_input_tokens = cached

    output_details = usage.get("output_tokens_details")
    if isinstance(output_details, dict):
        reasoning = output_details.get("reasoning_tokens")
        if isinstance(reasoning, int) and not isinstance(reasoning, bool):
            delta.server_tool_use = {"reasoning_tokens": reasoning}

    total.add(delta)
