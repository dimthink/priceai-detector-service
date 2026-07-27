from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from web import jobs


@pytest.fixture
def isolated_job_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    job_dir = tmp_path / "jobs"
    job_dir.mkdir()
    monkeypatch.setattr(jobs, "JOBS_DIR", job_dir)
    monkeypatch.setattr(jobs, "_JOBS", {})
    return job_dir


def test_persisted_job_never_contains_api_key(isolated_job_state: Path) -> None:
    job = jobs.Job(
        id="job-safe",
        status="running",
        base_url="https://relay.example",
        target_model="gpt-test",
    )
    jobs._persist_job(job)

    payload = json.loads(jobs.state_path(job.id).read_text(encoding="utf-8"))
    assert payload["status"] == "running"
    assert "api_key" not in payload
    assert "sk-secret" not in jobs.state_path(job.id).read_text(encoding="utf-8")


def test_restart_marks_active_jobs_as_error(isolated_job_state: Path) -> None:
    job = jobs.Job(id="job-running", status="running", started_at=1.0)
    jobs._persist_job(job)
    jobs._JOBS = {}

    assert jobs.recover_interrupted_jobs() == 1
    recovered = jobs._JOBS[job.id]
    assert recovered.status == "error"
    assert recovered.finished_at is not None
    assert "service restart" in (recovered.error or "").lower()


@pytest.mark.asyncio
async def test_whole_job_timeout_becomes_error(
    isolated_job_state: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = jobs.Job(id="job-timeout", status="queued")
    jobs._JOBS[job.id] = job
    jobs._persist_job(job)

    async def stalled_run(*args, **kwargs):
        await asyncio.sleep(1)

    monkeypatch.setattr(jobs, "_run", stalled_run)
    monkeypatch.setattr(jobs, "_job_timeout_seconds", lambda *args: 0.01)
    await jobs._run_with_timeout(
        job.id,
        "https://relay.example",
        "sk-secret",
        "gpt-test",
        "quick",
        "openai",
    )

    assert jobs._JOBS[job.id].status == "error"
    assert "TimeoutError" in (jobs._JOBS[job.id].error or "")


@pytest.mark.asyncio
async def test_runtime_error_redacts_api_key_before_persisting(
    isolated_job_state: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api_key = "sk-secret-that-must-not-be-written"
    job = jobs.Job(id="job-error", status="queued", protocol="openai")
    jobs._JOBS[job.id] = job
    jobs._persist_job(job)

    async def rejected_run(*args, **kwargs):
        raise RuntimeError(f"upstream echoed Bearer {api_key}")

    monkeypatch.setattr(jobs, "_run_openai", rejected_run)
    await jobs._run(job.id, "https://relay.example", api_key, "gpt-test", "quick", "openai")

    persisted = jobs.state_path(job.id).read_text(encoding="utf-8")
    assert api_key not in persisted
    assert "[REDACTED]" in persisted


@pytest.mark.asyncio
async def test_metrics_report_active_age(isolated_job_state: Path) -> None:
    jobs._JOBS = {
        "queued": jobs.Job(id="queued", status="queued", created_at=1.0),
        "done": jobs.Job(id="done", status="done"),
        "error": jobs.Job(id="error", status="error"),
    }

    snapshot = await jobs.metrics()
    assert snapshot["queued"] == 1
    assert snapshot["running"] == 0
    assert snapshot["done"] == 1
    assert snapshot["error"] == 1
    assert snapshot["active"] == 1
    assert snapshot["oldest_active_age_s"] is not None
