from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from .cache import alert_state_path, load_alert_state, save_alert_state
from .config import TokenBarConfig
from .providers import Snapshot, remaining_pct

Notifier = Callable[["Alert"], None]


@dataclass(frozen=True)
class Alert:
    key: str
    title: str
    message: str


def compute_alerts(
    snapshots: list[Snapshot],
    config: TokenBarConfig,
    *,
    stale: bool = False,
) -> list[Alert]:
    config = config.normalized()
    notifications = config.notifications
    if not notifications.get("enabled", True):
        return []

    alerts: list[Alert] = []
    for snapshot in snapshots:
        if notifications.get("provider_errors", True) and not snapshot.ok:
            alerts.append(provider_error_alert(snapshot))
        if notifications.get("low_quota", True):
            alert = low_quota_alert(snapshot, config.low_quota_threshold)
            if alert is not None:
                alerts.append(alert)

    if stale and notifications.get("stale", True):
        alerts.append(Alert(
            "stale",
            "TokenBar data is stale",
            "Provider data has not refreshed recently.",
        ))

    return alerts


def provider_error_alert(snapshot: Snapshot) -> Alert:
    status = snapshot.status_label or snapshot.summary or "provider error"
    guidance = snapshot.guidance or snapshot.error or "Open TokenBar for details."
    return Alert(
        f"{snapshot.provider}:error:{status}",
        f"{snapshot.provider.capitalize()} needs attention",
        f"{status} · {guidance}",
    )


def low_quota_alert(snapshot: Snapshot, threshold: float) -> Alert | None:
    left = remaining_pct(snapshot.utilization_pct)
    if not snapshot.ok or left is None or left > threshold:
        return None
    return Alert(
        f"{snapshot.provider}:low-quota",
        f"{snapshot.provider.capitalize()} quota low",
        f"{left:.0f}% left. Next reset: {snapshot.reset_at or 'unknown'}.",
    )


def send_desktop_notification(alert: Alert) -> None:
    try:
        subprocess.Popen([
            "notify-send",
            "--app-name=TokenBar",
            alert.title,
            alert.message,
        ])
    except FileNotFoundError:
        print(f"{alert.title}: {alert.message}")


def process_alerts(
    snapshots: list[Snapshot],
    config: TokenBarConfig,
    *,
    stale: bool = False,
    state_path: Path | None = None,
    notifier: Notifier = send_desktop_notification,
    now: datetime | None = None,
) -> list[Alert]:
    now = now or datetime.now()
    alerts = compute_alerts(snapshots, config, stale=stale)
    current_keys = {alert.key for alert in alerts}
    state, error = load_alert_state(state_path)
    if error:
        print(f"TokenBar alert state ignored: {error}")

    snoozed_until = _snoozed_until(state)
    if snoozed_until is not None and snoozed_until > now:
        save_alert_state({
            "active_keys": [],
            "snoozed_until": snoozed_until.isoformat(timespec="seconds"),
            "updated_at": now.isoformat(timespec="seconds"),
        }, state_path)
        return []

    previous_keys = _active_keys(state)
    new_alerts = [alert for alert in alerts if alert.key not in previous_keys]

    for alert in new_alerts:
        notifier(alert)

    save_alert_state({
        "active_keys": sorted(current_keys),
        "updated_at": now.isoformat(timespec="seconds"),
    }, state_path)
    return new_alerts


def clear_alert_state(path: Path | None = None) -> Path:
    path = path or alert_state_path()
    if path.exists():
        path.unlink()
    return path


def snooze_alerts(minutes: int = 60, *, path: Path | None = None, now: datetime | None = None) -> datetime:
    now = now or datetime.now()
    snoozed_until = now + timedelta(minutes=max(1, int(minutes)))
    state, _error = load_alert_state(path)
    save_alert_state({
        "active_keys": sorted(_active_keys(state)),
        "snoozed_until": snoozed_until.isoformat(timespec="seconds"),
        "updated_at": now.isoformat(timespec="seconds"),
    }, path)
    return snoozed_until


def _active_keys(state: dict[str, Any]) -> set[str]:
    raw = state.get("active_keys")
    if not isinstance(raw, list):
        return set()
    return {key for key in raw if isinstance(key, str)}


def _snoozed_until(state: dict[str, Any]) -> datetime | None:
    raw = state.get("snoozed_until")
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None
