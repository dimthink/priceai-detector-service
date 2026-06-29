"""中转站红黑榜:聚合所有公开检测报告,按域名分组排序。

每份 /r/{job_id} 报告都是公开可分享的;leaderboard 只是把它们按 base_url 的
域名聚合起来,展示每个中转站被多少人测过、平均分多少、最近一次什么 verdict。

SEO 价值:用户搜「XX 中转站怎么样」时,leaderboard 页面包含该域名 + 评分
摘要,可以直接命中长尾搜索。详细报告通过链接跳到具体的 /r/{job_id}。
"""

from __future__ import annotations

import json
import re
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


REPORT_DIRS = [
    Path("/opt/veridrop/web_data/jobs/anthropic"),
    Path("/opt/veridrop/web_data/jobs/openai"),
    Path("/opt/veridrop/web_data/jobs/openai_responses"),
    Path("/opt/veridrop/web_data/jobs/gemini"),
    Path("/opt/veridrop/web_data/jobs"),  # legacy top-level
]

PROTOCOL_LABELS = {
    "anthropic": "Claude",
    "openai": "OpenAI Chat Completions",
    "openai_responses": "OpenAI Responses",
    "gemini": "Gemini",
}
VERDICT_LABELS = {"passed": "通过", "marginal": "存在风险", "failed": "未达标"}

# A domain with only 1 detection is statistically meaningless for ranking.
# Still surface it in the list (good for SEO long-tail), but mark it as
# "single sample" so users know not to over-interpret.
_MIN_RANKED_SAMPLES = 2

# Bayesian ranking parameters. The prior pulls few-sample relays toward
# a neutral 50 so a fluky 1-test "100/100" can't outrank a consistently
# 99/100 relay tested 100 times. See "排名指标" discussion 2026-05-05.
_RANKING_PRIOR_VALUE = 50.0
_RANKING_PRIOR_WEIGHT = 5.0

# Strict allow-list for path parameter — accept only what _extract_domain
# could legitimately produce from a real base_url. Rejects anything with
# slashes, query strings, uppercase, unicode, leading/trailing dots/hyphens.
# Defends path traversal, header injection, and template XSS via stray chars.
_DOMAIN_RE = re.compile(r"^[a-z0-9](?:[a-z0-9.-]{1,251}[a-z0-9])?$")

# Domains hidden from the public leaderboard (and per-domain detail pages).
# JSON reports remain on disk and individual /r/{job_id} share links keep
# working — only the aggregated listing pages skip them.
_BLOCKED_DOMAINS: frozenset[str] = frozenset({
    "api.sunyears.com",
    "router.8864k.com",
})


def is_valid_domain(s: str) -> bool:
    """Whether s is safe to accept as a path parameter for /leaderboard/{domain}."""
    if not s or len(s) > 253 or "." not in s:
        return False
    return bool(_DOMAIN_RE.match(s))


@dataclass
class ProtocolStats:
    """Per-protocol stats for one relay domain."""
    protocol: str
    count: int = 0
    scores: list[float] = field(default_factory=list)
    last_job_id: str = ""
    last_score: float = 0.0
    last_verdict: str = ""
    last_checked: datetime | None = None
    failed_detectors: Counter = field(default_factory=Counter)

    @property
    def avg(self) -> float:
        return sum(self.scores) / len(self.scores) if self.scores else 0.0

    @property
    def median(self) -> float:
        return statistics.median(self.scores) if self.scores else 0.0


@dataclass
class RelayStats:
    """Aggregated stats for one relay domain across all protocols + checks."""
    domain: str
    by_protocol: dict[str, ProtocolStats] = field(default_factory=dict)

    @property
    def total_count(self) -> int:
        return sum(p.count for p in self.by_protocol.values())

    @property
    def overall_score(self) -> float:
        """Weighted by per-protocol detection count — tiebreaker for ranking."""
        all_scores = []
        for p in self.by_protocol.values():
            all_scores.extend(p.scores)
        return sum(all_scores) / len(all_scores) if all_scores else 0.0

    @property
    def overall_median(self) -> float:
        all_scores = []
        for p in self.by_protocol.values():
            all_scores.extend(p.scores)
        return statistics.median(all_scores) if all_scores else 0.0

    @property
    def ranking_score(self) -> float:
        """Bayesian-weighted score for ranking. Pulls few-sample relays
        toward a neutral prior (50) so a single fluky 100% doesn't beat
        a consistently 99% relay tested 100 times.

        Examples (prior=50, weight=5):
          1 × 100  → 58.3   (mostly prior)
          5 × 100  → 75.0   (half prior, half observed)
          20 × 100 → 90.0   (mostly observed)
          100 × 99 → 96.6   ← outranks "5 × 100" (75.0) ✓

        Display shows median (familiar to users); ranking_score only
        drives sort order. The two together communicate "we ranked it
        by confidence-weighted score, here's the typical (median) value
        too."
        """
        all_scores: list[float] = []
        for p in self.by_protocol.values():
            all_scores.extend(p.scores)
        n = len(all_scores)
        if n == 0:
            return _RANKING_PRIOR_VALUE
        return (sum(all_scores) + _RANKING_PRIOR_VALUE * _RANKING_PRIOR_WEIGHT) / (
            n + _RANKING_PRIOR_WEIGHT
        )

    @property
    def last_checked(self) -> datetime | None:
        ts = [p.last_checked for p in self.by_protocol.values() if p.last_checked]
        return max(ts) if ts else None

    @property
    def is_ranked(self) -> bool:
        """≥ 2 samples means the score is statistically meaningful."""
        return self.total_count >= _MIN_RANKED_SAMPLES

    @property
    def protocols_label(self) -> str:
        labels = [PROTOCOL_LABELS.get(p, p) for p in sorted(self.by_protocol.keys())]
        return " · ".join(labels)

    @property
    def verdict_class(self) -> str:
        """CSS class for color coding the score badge."""
        score = self.overall_median
        if score >= 85: return "ok"
        if score >= 70: return "good"
        if score >= 50: return "warn"
        return "fail"


def _extract_domain(base_url: str) -> str:
    """Strip protocol + path, keep host. example: https://api.x.com/v1 → api.x.com."""
    if not base_url:
        return ""
    if "://" not in base_url:
        base_url = "https://" + base_url
    try:
        host = urlparse(base_url).hostname or ""
    except ValueError:
        return ""
    return host.lower()


def _parse_timestamp(ts: Any) -> datetime | None:
    if not isinstance(ts, str):
        return None
    try:
        # Handle both `Z` suffix and `+00:00` offset
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _load_report(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def aggregate() -> tuple[list[RelayStats], dict[str, int]]:
    """Scan all report JSONs, return (sorted relay stats, summary metrics).

    Sort:
      1. Ranked relays (≥ 2 detections) first, by overall_median desc
      2. Single-sample relays at the bottom, by last_checked desc (recency)
    """
    by_domain: dict[str, RelayStats] = defaultdict(lambda: RelayStats(domain=""))
    total_reports = 0

    for dir_path in REPORT_DIRS:
        if not dir_path.is_dir():
            continue
        for json_path in dir_path.glob("*.json"):
            report = _load_report(json_path)
            if not report:
                continue
            domain = _extract_domain(report.get("base_url", ""))
            if not domain:
                continue
            if domain in _BLOCKED_DOMAINS:
                continue
            total_reports += 1
            protocol = str(report.get("protocol") or "anthropic")
            score = float(report.get("total_score") or 0)
            verdict = str(report.get("verdict") or "failed")
            ts = _parse_timestamp(report.get("timestamp"))
            job_id = json_path.stem

            relay = by_domain[domain]
            relay.domain = domain
            ps = relay.by_protocol.setdefault(protocol, ProtocolStats(protocol=protocol))
            ps.count += 1
            ps.scores.append(score)
            for r in report.get("results") or []:
                if isinstance(r, dict) and r.get("status") == "fail":
                    name = r.get("name")
                    if isinstance(name, str):
                        ps.failed_detectors[name] += 1
            # Track most recent — by timestamp if available, else by file mtime
            if ts and (ps.last_checked is None or ts > ps.last_checked):
                ps.last_checked = ts
                ps.last_job_id = job_id
                ps.last_score = score
                ps.last_verdict = verdict
            elif ps.last_checked is None:
                ps.last_job_id = job_id
                ps.last_score = score
                ps.last_verdict = verdict
                try:
                    mtime = datetime.fromtimestamp(json_path.stat().st_mtime, tz=timezone.utc)
                    ps.last_checked = mtime
                except OSError:
                    pass

    relays = list(by_domain.values())
    # Sort by Bayesian-weighted ranking score (descending), then by
    # is_ranked (≥2 samples first — single-sample relays sink to the
    # bottom no matter how high their fluke score), then recency tiebreak.
    relays.sort(key=lambda r: (
        not r.is_ranked,                  # ranked relays float to the top
        -r.ranking_score,                 # then by Bayesian-weighted score
        -(r.last_checked.timestamp() if r.last_checked else 0),
    ))

    summary = {
        "total_reports": total_reports,
        "total_relays": len(relays),
        "ranked_relays": sum(1 for r in relays if r.is_ranked),
    }
    return relays, summary


@dataclass
class JobEntry:
    """One row in a per-domain detail page's history table."""
    job_id: str
    protocol: str
    model: str
    score: float
    verdict: str
    timestamp: datetime | None
    failed_count: int

    @property
    def date_str(self) -> str:
        return self.timestamp.strftime("%Y-%m-%d") if self.timestamp else ""

    @property
    def badge_class(self) -> str:
        if self.score >= 85: return "ok"
        if self.score >= 70: return "good"
        if self.score >= 50: return "warn"
        return "fail"


def aggregate_one(domain: str) -> tuple[RelayStats, list[JobEntry]] | None:
    """Build the per-domain detail view: stats + full job history.

    Returns None if no reports exist for this domain. Otherwise returns
    (stats, jobs) where jobs is sorted newest-first.

    This re-scans all report files filtered to the requested domain. At our
    scale (<10k reports) the cost is negligible; at 100k+ we'd add an index.
    """
    domain = domain.strip().lower()
    if not is_valid_domain(domain):
        return None
    if domain in _BLOCKED_DOMAINS:
        return None

    relay = RelayStats(domain=domain)
    history: list[JobEntry] = []

    for dir_path in REPORT_DIRS:
        if not dir_path.is_dir():
            continue
        for json_path in dir_path.glob("*.json"):
            report = _load_report(json_path)
            if not report:
                continue
            if _extract_domain(report.get("base_url", "")) != domain:
                continue

            protocol = str(report.get("protocol") or "anthropic")
            score = float(report.get("total_score") or 0)
            verdict = str(report.get("verdict") or "failed")
            ts = _parse_timestamp(report.get("timestamp"))
            if ts is None:
                try:
                    ts = datetime.fromtimestamp(json_path.stat().st_mtime, tz=timezone.utc)
                except OSError:
                    pass
            job_id = json_path.stem
            model = str(report.get("target_model") or "")

            results = report.get("results") or []
            failed_count = sum(
                1 for r in results
                if isinstance(r, dict) and r.get("status") == "fail"
            )

            ps = relay.by_protocol.setdefault(protocol, ProtocolStats(protocol=protocol))
            ps.count += 1
            ps.scores.append(score)
            for r in results:
                if isinstance(r, dict) and r.get("status") == "fail":
                    name = r.get("name")
                    if isinstance(name, str):
                        ps.failed_detectors[name] += 1
            if ts and (ps.last_checked is None or ts > ps.last_checked):
                ps.last_checked = ts
                ps.last_job_id = job_id
                ps.last_score = score
                ps.last_verdict = verdict
            elif ps.last_checked is None:
                ps.last_job_id = job_id
                ps.last_score = score
                ps.last_verdict = verdict

            history.append(JobEntry(
                job_id=job_id,
                protocol=protocol,
                model=model,
                score=score,
                verdict=verdict,
                timestamp=ts,
                failed_count=failed_count,
            ))

    if not history:
        return None

    # Newest first; tie-break on job_id for deterministic ordering.
    history.sort(
        key=lambda j: (j.timestamp.timestamp() if j.timestamp else 0, j.job_id),
        reverse=True,
    )
    return relay, history


def all_domains() -> list[str]:
    """Every domain that has at least one report — used to populate sitemap."""
    relays, _ = aggregate()
    return [r.domain for r in relays if r.domain]
