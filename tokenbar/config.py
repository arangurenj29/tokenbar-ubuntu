from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_REFRESH_INTERVAL_SECONDS = 120
DEFAULT_STALE_AFTER_MINUTES = 15
DEFAULT_LOW_QUOTA_THRESHOLD = 10.0
DEFAULT_PROVIDERS = {
    "codex": True,
    "claude": True,
    "openai_api": False,
}
DEFAULT_NOTIFICATIONS = {
    "enabled": True,
    "low_quota": True,
    "provider_errors": True,
    "stale": True,
}


@dataclass
class TokenBarConfig:
    refresh_interval_seconds: int = DEFAULT_REFRESH_INTERVAL_SECONDS
    stale_after_minutes: int = DEFAULT_STALE_AFTER_MINUTES
    low_quota_threshold: float = DEFAULT_LOW_QUOTA_THRESHOLD
    providers: dict[str, bool] = field(default_factory=lambda: DEFAULT_PROVIDERS.copy())
    notifications: dict[str, bool] = field(default_factory=lambda: DEFAULT_NOTIFICATIONS.copy())

    def normalized(self) -> "TokenBarConfig":
        return TokenBarConfig(
            refresh_interval_seconds=_positive_int(
                self.refresh_interval_seconds,
                DEFAULT_REFRESH_INTERVAL_SECONDS,
            ),
            stale_after_minutes=_positive_int(self.stale_after_minutes, DEFAULT_STALE_AFTER_MINUTES),
            low_quota_threshold=_percent_float(
                self.low_quota_threshold,
                DEFAULT_LOW_QUOTA_THRESHOLD,
            ),
            providers=_normalize_providers(self.providers),
            notifications=_normalize_notifications(self.notifications),
        )

    def as_dict(self) -> dict[str, Any]:
        normalized = self.normalized()
        return {
            "refresh_interval_seconds": normalized.refresh_interval_seconds,
            "stale_after_minutes": normalized.stale_after_minutes,
            "low_quota_threshold": normalized.low_quota_threshold,
            "providers": normalized.providers,
            "notifications": normalized.notifications,
        }


def config_path() -> Path:
    config_home = os.environ.get("XDG_CONFIG_HOME")
    base = Path(config_home).expanduser() if config_home else Path.home() / ".config"
    return base / "tokenbar" / "config.json"


def load_config(path: Path | None = None) -> tuple[TokenBarConfig, str | None]:
    path = path or config_path()
    if not path.exists():
        return TokenBarConfig(), None

    try:
        payload = json.loads(path.read_text())
        if not isinstance(payload, dict):
            raise ValueError("config root must be a JSON object")
    except Exception as exc:
        return TokenBarConfig(), f"{type(exc).__name__}: {exc}"

    config = TokenBarConfig(
        refresh_interval_seconds=_positive_int(
            payload.get("refresh_interval_seconds"),
            DEFAULT_REFRESH_INTERVAL_SECONDS,
        ),
        stale_after_minutes=_positive_int(
            payload.get("stale_after_minutes"),
            DEFAULT_STALE_AFTER_MINUTES,
        ),
        low_quota_threshold=_percent_float(
            payload.get("low_quota_threshold"),
            DEFAULT_LOW_QUOTA_THRESHOLD,
        ),
        providers=_normalize_providers(payload.get("providers")),
        notifications=_normalize_notifications(payload.get("notifications")),
    )
    return config, None


def config_as_jsonable(config: TokenBarConfig, load_error: str | None = None) -> dict[str, Any]:
    payload = config.as_dict()
    payload["path"] = str(config_path())
    if load_error:
        payload["load_error"] = load_error
    return payload


def config_to_json(config: TokenBarConfig, load_error: str | None = None) -> str:
    return json.dumps(config_as_jsonable(config, load_error), indent=2)


def default_config_json() -> str:
    return json.dumps(TokenBarConfig().as_dict(), indent=2) + "\n"


def ensure_config_file(path: Path | None = None) -> tuple[Path, bool]:
    path = path or config_path()
    if path.exists():
        return path, False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(default_config_json())
    return path, True


def _positive_int(value: Any, default: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _percent_float(value: Any, default: float) -> float:
    if isinstance(value, bool):
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if parsed < 0 or parsed > 100:
        return default
    return parsed


def _normalize_providers(value: Any) -> dict[str, bool]:
    providers = DEFAULT_PROVIDERS.copy()
    if not isinstance(value, dict):
        return providers

    for key in DEFAULT_PROVIDERS:
        raw = value.get(key)
        if isinstance(raw, bool):
            providers[key] = raw
    return providers


def _normalize_notifications(value: Any) -> dict[str, bool]:
    notifications = DEFAULT_NOTIFICATIONS.copy()
    if not isinstance(value, dict):
        return notifications

    for key in DEFAULT_NOTIFICATIONS:
        raw = value.get(key)
        if isinstance(raw, bool):
            notifications[key] = raw
    return notifications
