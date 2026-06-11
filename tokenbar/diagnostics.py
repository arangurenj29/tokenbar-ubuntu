from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from .autostart import autostart_path, autostart_status
from .cache import alert_state_path, snapshot_cache_path
from .config import TokenBarConfig, config_path


def collect_diagnostics(
    config: TokenBarConfig,
    *,
    config_error: str | None = None,
    tray_backend: str | None = None,
    tray_message: str | None = None,
) -> dict[str, Any]:
    codex_auth = Path.home() / ".codex" / "auth.json"
    claude_auth = Path.home() / ".claude" / ".credentials.json"
    return {
        "environment": {
            "display": bool(os.environ.get("DISPLAY")),
            "wayland_display": bool(os.environ.get("WAYLAND_DISPLAY")),
            "xdg_current_desktop": os.environ.get("XDG_CURRENT_DESKTOP"),
            "session_type": os.environ.get("XDG_SESSION_TYPE"),
            "notify_send": shutil.which("notify-send") is not None,
            "zenity": shutil.which("zenity") is not None,
            "clipboard_helper": next((name for name in ("wl-copy", "xclip", "xsel") if shutil.which(name)), None),
        },
        "tray": {
            "backend": tray_backend,
            "message": tray_message,
        },
        "paths": {
            "config": str(config_path()),
            "config_exists": config_path().exists(),
            "cache": str(snapshot_cache_path()),
            "cache_exists": snapshot_cache_path().exists(),
            "alert_state": str(alert_state_path()),
            "alert_state_exists": alert_state_path().exists(),
            "autostart": str(autostart_path()),
            "autostart_status": autostart_status(),
        },
        "auth": {
            "codex_auth_exists": codex_auth.exists(),
            "claude_auth_exists": claude_auth.exists(),
            "openai_api_key_exported": bool(os.environ.get("OPENAI_ADMIN_KEY") or os.environ.get("OPENAI_API_KEY")),
        },
        "config": config.as_dict(),
        "config_error": config_error,
    }


def format_diagnostics_text(diagnostics: dict[str, Any]) -> str:
    env = diagnostics["environment"]
    paths = diagnostics["paths"]
    auth = diagnostics["auth"]
    config = diagnostics["config"]
    tray = diagnostics["tray"]
    lines = [
        "TokenBar diagnostics",
        "",
        f"Tray backend: {tray.get('backend') or 'not checked'}",
        f"Tray message: {tray.get('message') or 'n/a'}",
        f"Wayland: {env['wayland_display']} · DISPLAY: {env['display']}",
        f"Desktop: {env.get('xdg_current_desktop') or 'unknown'} · Session: {env.get('session_type') or 'unknown'}",
        f"notify-send: {env['notify_send']} · zenity: {env['zenity']}",
        f"Clipboard helper: {env.get('clipboard_helper') or 'missing'}",
        "",
        f"Config: {paths['config']} ({'exists' if paths['config_exists'] else 'missing'})",
        f"Cache: {paths['cache']} ({'exists' if paths['cache_exists'] else 'missing'})",
        f"Alert state: {paths['alert_state']} ({'exists' if paths['alert_state_exists'] else 'missing'})",
        f"Autostart: {paths['autostart_status']} · {paths['autostart']}",
        "",
        f"Codex auth: {'found' if auth['codex_auth_exists'] else 'missing'}",
        f"Claude auth: {'found' if auth['claude_auth_exists'] else 'missing'}",
        f"OpenAI API env: {'set' if auth['openai_api_key_exported'] else 'not set'}",
        "",
        f"Refresh interval: {config['refresh_interval_seconds']}s",
        f"Stale after: {config['stale_after_minutes']}m",
        f"Low quota threshold: {config['low_quota_threshold']}%",
        f"Providers: {config['providers']}",
        f"Notifications: {config['notifications']}",
    ]
    if diagnostics.get("config_error"):
        lines.append(f"Config error: {diagnostics['config_error']}")
    return "\n".join(lines)
