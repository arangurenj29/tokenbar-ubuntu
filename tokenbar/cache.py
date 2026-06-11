from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from .providers import Snapshot

CACHE_FILENAME = "latest-snapshot.json"
ALERT_STATE_FILENAME = "alert-state.json"


def cache_dir() -> Path:
    cache_home = os.environ.get("XDG_CACHE_HOME")
    base = Path(cache_home).expanduser() if cache_home else Path.home() / ".cache"
    return base / "tokenbar"


def snapshot_cache_path() -> Path:
    return cache_dir() / CACHE_FILENAME


def alert_state_path() -> Path:
    return cache_dir() / ALERT_STATE_FILENAME


def save_snapshot_cache(
    snapshots: list[Snapshot],
    *,
    saved_at: datetime | None = None,
    path: Path | None = None,
) -> Path:
    saved_at = saved_at or datetime.now()
    path = path or snapshot_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "saved_at": saved_at.isoformat(timespec="seconds"),
        "snapshots": [snapshot.__dict__ for snapshot in snapshots],
    }
    path.write_text(json.dumps(payload, indent=2))
    return path


def load_snapshot_cache(path: Path | None = None) -> tuple[list[Snapshot], datetime | None, str | None]:
    path = path or snapshot_cache_path()
    if not path.exists():
        return [], None, None
    try:
        payload = json.loads(path.read_text())
        if not isinstance(payload, dict):
            raise ValueError("cache root must be a JSON object")
        saved_at = _parse_saved_at(payload.get("saved_at"))
        snapshots = _snapshots_from_jsonable(payload.get("snapshots"))
        return snapshots, saved_at, None
    except Exception as exc:
        return [], None, f"{type(exc).__name__}: {exc}"


def snapshot_cache_as_jsonable(path: Path | None = None) -> dict[str, Any]:
    snapshots, saved_at, error = load_snapshot_cache(path)
    payload: dict[str, Any] = {
        "path": str(path or snapshot_cache_path()),
        "saved_at": saved_at.isoformat(timespec="seconds") if saved_at else None,
        "snapshots": [snapshot.__dict__ for snapshot in snapshots],
    }
    if error:
        payload["load_error"] = error
    return payload


def load_alert_state(path: Path | None = None) -> tuple[dict[str, Any], str | None]:
    path = path or alert_state_path()
    if not path.exists():
        return {}, None
    try:
        payload = json.loads(path.read_text())
        if not isinstance(payload, dict):
            raise ValueError("alert state root must be a JSON object")
        return payload, None
    except Exception as exc:
        return {}, f"{type(exc).__name__}: {exc}"


def save_alert_state(state: dict[str, Any], path: Path | None = None) -> Path:
    path = path or alert_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2))
    return path


def _parse_saved_at(raw: Any) -> datetime | None:
    if raw in (None, ""):
        return None
    if not isinstance(raw, str):
        raise ValueError("saved_at must be a string")
    return datetime.fromisoformat(raw)


def _snapshots_from_jsonable(raw: Any) -> list[Snapshot]:
    if not isinstance(raw, list):
        raise ValueError("snapshots must be a list")
    snapshots: list[Snapshot] = []
    allowed_keys = set(Snapshot.__dataclass_fields__.keys())
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("snapshot must be a JSON object")
        filtered = {key: item.get(key) for key in allowed_keys if key in item}
        snapshots.append(Snapshot(**filtered))
    return snapshots
