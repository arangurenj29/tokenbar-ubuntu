from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from tokenbar.cache import (
    alert_state_path,
    cache_dir,
    load_alert_state,
    load_snapshot_cache,
    save_alert_state,
    save_snapshot_cache,
    snapshot_cache_as_jsonable,
    snapshot_cache_path,
)
from tokenbar.providers import Snapshot


class CacheTests(unittest.TestCase):
    def test_missing_cache_returns_empty_snapshot_list(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            snapshots, saved_at, error = load_snapshot_cache(Path(temp_dir) / "missing.json")
        self.assertEqual(snapshots, [])
        self.assertIsNone(saved_at)
        self.assertIsNone(error)

    def test_save_and_load_snapshot_cache_roundtrips(self) -> None:
        saved_at = datetime(2026, 6, 11, 12, 30)
        snapshot = Snapshot(
            "codex",
            "oauth",
            True,
            "61% left",
            utilization_pct=39.0,
            reset_at="2026-06-11 14:50",
            detail="Plan plus",
            weekly_utilization_pct=7.0,
            weekly_reset_at="2026-06-18 12:50",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "latest-snapshot.json"
            save_snapshot_cache([snapshot], saved_at=saved_at, path=path)
            snapshots, loaded_at, error = load_snapshot_cache(path)
        self.assertIsNone(error)
        self.assertEqual(loaded_at, saved_at)
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0].provider, "codex")
        self.assertEqual(snapshots[0].utilization_pct, 39.0)
        self.assertEqual(snapshots[0].weekly_utilization_pct, 7.0)

    def test_invalid_cache_reports_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "latest-snapshot.json"
            path.write_text("{bad")
            snapshots, saved_at, error = load_snapshot_cache(path)
        self.assertEqual(snapshots, [])
        self.assertIsNone(saved_at)
        self.assertIsNotNone(error)

    def test_cache_dump_includes_load_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "latest-snapshot.json"
            path.write_text('{"snapshots": "bad"}')
            payload = snapshot_cache_as_jsonable(path)
        self.assertIn("load_error", payload)
        self.assertEqual(payload["snapshots"], [])

    @patch.dict("os.environ", {"XDG_CACHE_HOME": "/tmp/tokenbar-cache-home"}, clear=True)
    def test_cache_path_uses_xdg_cache_home(self) -> None:
        self.assertEqual(cache_dir(), Path("/tmp/tokenbar-cache-home/tokenbar"))
        self.assertEqual(snapshot_cache_path(), Path("/tmp/tokenbar-cache-home/tokenbar/latest-snapshot.json"))
        self.assertEqual(alert_state_path(), Path("/tmp/tokenbar-cache-home/tokenbar/alert-state.json"))

    def test_save_and_load_alert_state_roundtrips(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "alert-state.json"
            save_alert_state({"active_keys": ["claude:low-quota"]}, path)
            state, error = load_alert_state(path)
        self.assertIsNone(error)
        self.assertEqual(state["active_keys"], ["claude:low-quota"])


if __name__ == "__main__":
    unittest.main()
