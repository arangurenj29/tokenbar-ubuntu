from __future__ import annotations

import json
import os
import pathlib
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from json import JSONDecodeError
from datetime import datetime, timezone
from typing import Any

from .config import TokenBarConfig

HOME = pathlib.Path.home()


@dataclass
class Snapshot:
    provider: str
    source: str
    ok: bool
    summary: str
    utilization_pct: float | None = None
    reset_at: str | None = None
    detail: str | None = None
    error: str | None = None
    weekly_utilization_pct: float | None = None
    weekly_reset_at: str | None = None
    status_label: str | None = None
    guidance: str | None = None


LOGIN_GUIDANCE = {
    "codex": "Run: codex login",
    "claude": "Run: claude auth login",
    "openai": "Set OPENAI_ADMIN_KEY or OPENAI_API_KEY",
}


def failure_snapshot(
    provider: str,
    source: str,
    status_label: str,
    guidance: str,
    *,
    error: str | None = None,
) -> Snapshot:
    return Snapshot(
        provider=provider,
        source=source,
        ok=False,
        summary=status_label,
        status_label=status_label,
        guidance=guidance,
        error=error,
    )


def classify_provider_error(provider: str, error: Exception) -> tuple[str, str, str]:
    if isinstance(error, urllib.error.HTTPError):
        if error.code in (401, 403):
            return "auth expired", LOGIN_GUIDANCE.get(provider, "Log in again"), f"HTTP {error.code}"
        return f"HTTP {error.code}", "Try refreshing again later", f"HTTP {error.code}: {error.reason}"
    if isinstance(error, urllib.error.URLError):
        return "network unavailable", "Check internet connection", str(error)
    if isinstance(error, (JSONDecodeError, KeyError, TypeError, ValueError)):
        return "response unavailable", "Try refreshing again later", f"{type(error).__name__}: {error}"
    return "provider error", "Try refreshing again later", f"{type(error).__name__}: {error}"


def error_snapshot(provider: str, source: str, error: Exception) -> Snapshot:
    status_label, guidance, detail = classify_provider_error(provider, error)
    return failure_snapshot(provider, source, status_label, guidance, error=detail)


def _read_json(path: pathlib.Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _request_json(url: str, headers: dict[str, str]) -> dict[str, Any]:
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def _format_reset(raw: str | int | float | None) -> str | None:
    if raw is None or raw == "":
        return None
    try:
        if isinstance(raw, (int, float)):
            dt = datetime.fromtimestamp(raw, tz=timezone.utc)
        else:
            dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        local = dt.astimezone()
        return local.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(raw)


def fetch_codex() -> Snapshot:
    auth_path = HOME / ".codex" / "auth.json"
    if not auth_path.exists():
        return failure_snapshot("codex", "oauth", "auth missing", LOGIN_GUIDANCE["codex"], error=f"Missing {auth_path}")

    try:
        auth = _read_json(auth_path)
    except Exception as exc:
        return failure_snapshot("codex", "oauth", "auth unreadable", LOGIN_GUIDANCE["codex"], error=f"{type(exc).__name__}: {exc}")
    token = auth.get("tokens", {}).get("access_token")
    if not token:
        return failure_snapshot("codex", "oauth", "auth missing", LOGIN_GUIDANCE["codex"], error="Missing access token")

    try:
        payload = _request_json(
            "https://chatgpt.com/backend-api/wham/usage",
            {
                "Authorization": f"Bearer {token}",
                "User-Agent": "TokenBar/0.1",
            },
        )
    except Exception as exc:
        return error_snapshot("codex", "oauth", exc)

    primary = payload.get("rate_limit", {}).get("primary_window") or {}
    pct = primary.get("used_percent")
    secondary = payload.get("rate_limit", {}).get("secondary_window") or {}
    secondary_pct = secondary.get("used_percent")
    reset_at = _format_reset(primary.get("reset_at"))
    weekly_reset_at = _format_reset(secondary.get("reset_at"))
    plan = payload.get("plan_type") or "unknown"
    summary = f"{100 - pct:.0f}% left" if isinstance(pct, (int, float)) else "Usage unavailable"
    return Snapshot(
        provider="codex",
        source="oauth",
        ok=True,
        summary=summary,
        utilization_pct=float(pct) if isinstance(pct, (int, float)) else None,
        reset_at=reset_at,
        detail=f"Plan {plan}",
        weekly_utilization_pct=float(secondary_pct) if isinstance(secondary_pct, (int, float)) else None,
        weekly_reset_at=weekly_reset_at,
    )


def fetch_claude() -> Snapshot:
    credentials_path = HOME / ".claude" / ".credentials.json"
    if not credentials_path.exists():
        return failure_snapshot("claude", "oauth", "auth missing", LOGIN_GUIDANCE["claude"], error=f"Missing {credentials_path}")

    try:
        credentials = _read_json(credentials_path)
    except Exception as exc:
        return failure_snapshot("claude", "oauth", "auth unreadable", LOGIN_GUIDANCE["claude"], error=f"{type(exc).__name__}: {exc}")
    token = credentials.get("claudeAiOauth", {}).get("accessToken")
    if not token:
        return failure_snapshot("claude", "oauth", "auth missing", LOGIN_GUIDANCE["claude"], error="Missing Claude access token")

    try:
        payload = _request_json(
            "https://api.anthropic.com/api/oauth/usage",
            {
                "Authorization": f"Bearer {token}",
                "anthropic-beta": "oauth-2025-04-20",
                "User-Agent": "TokenBar/0.1",
            },
        )
    except Exception as exc:
        return error_snapshot("claude", "oauth", exc)

    five_hour = payload.get("five_hour") or {}
    seven_day = payload.get("seven_day") or {}
    pct = five_hour.get("utilization")
    weekly_pct = seven_day.get("utilization")
    reset_at = _format_reset(five_hour.get("resets_at"))
    weekly_reset_at = _format_reset(seven_day.get("resets_at"))
    plan = credentials.get("claudeAiOauth", {}).get("subscriptionType") or credentials.get("claudeAiOauth", {}).get("rateLimitTier") or "unknown"
    summary = f"{100 - pct:.0f}% left" if isinstance(pct, (int, float)) else "Usage unavailable"
    return Snapshot(
        provider="claude",
        source="oauth",
        ok=True,
        summary=summary,
        utilization_pct=float(pct) if isinstance(pct, (int, float)) else None,
        reset_at=reset_at,
        detail=f"Plan {plan}",
        weekly_utilization_pct=float(weekly_pct) if isinstance(weekly_pct, (int, float)) else None,
        weekly_reset_at=weekly_reset_at,
    )


def fetch_openai_api() -> Snapshot | None:
    key = os.environ.get("OPENAI_ADMIN_KEY") or os.environ.get("OPENAI_API_KEY")
    if not key:
        return None

    query = urllib.parse.urlencode({"bucket_width": "1d", "limit": 1})
    try:
        payload = _request_json(
            f"https://api.openai.com/v1/organization/costs?{query}",
            {
                "Authorization": f"Bearer {key}",
                "User-Agent": "TokenBar/0.1",
            },
        )
    except Exception as exc:
        return error_snapshot("openai", "admin-api", exc)

    rows = payload.get("data") or []
    amount = None
    if rows:
        result_rows = rows[0].get("results") or []
        if result_rows:
            amount = result_rows[0].get("amount", {}).get("value")
    summary = f"${amount:.2f} today" if isinstance(amount, (int, float)) else "Cost unavailable"
    return Snapshot("openai", "admin-api", True, summary, detail="Organization costs")


def collect_snapshots(config: TokenBarConfig | None = None) -> list[Snapshot]:
    config = (config or TokenBarConfig()).normalized()
    snapshots: list[Snapshot] = []
    if config.providers.get("codex", True):
        snapshots.append(fetch_codex())
    if config.providers.get("claude", True):
        snapshots.append(fetch_claude())
    if config.providers.get("openai_api", False):
        openai_snapshot = fetch_openai_api()
        if openai_snapshot is not None:
            snapshots.append(openai_snapshot)
    return snapshots


def snapshots_as_jsonable(config: TokenBarConfig | None = None) -> list[dict[str, Any]]:
    return [snapshot.__dict__ for snapshot in collect_snapshots(config)]


def remaining_pct(utilization_pct: float | None) -> float | None:
    if utilization_pct is None:
        return None
    return max(0.0, min(100.0, 100.0 - utilization_pct))


def top_line(snapshots: list[Snapshot]) -> str:
    parts = []
    for snapshot in snapshots:
        label = snapshot.provider.capitalize()
        left = remaining_pct(snapshot.utilization_pct)
        if left is not None:
            parts.append(f"{label} {left:.0f}% left")
        elif snapshot.ok:
            parts.append(f"{label} OK")
        else:
            parts.append(f"{label} ERR")
    return " | ".join(parts)


def overall_status_level(snapshots: list[Snapshot]) -> str:
    if any(not snapshot.ok for snapshot in snapshots):
        return "error"
    peak = max((snapshot.utilization_pct or 0) for snapshot in snapshots)
    if peak >= 75:
        return "warn"
    return "ok"
