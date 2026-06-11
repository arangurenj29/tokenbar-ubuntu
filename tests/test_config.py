from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tokenbar.config import TokenBarConfig, config_as_jsonable, config_path, ensure_config_file, load_config


class ConfigTests(unittest.TestCase):
    def test_missing_config_uses_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config, error = load_config(Path(temp_dir) / "missing.json")
        self.assertIsNone(error)
        self.assertEqual(config.refresh_interval_seconds, 120)
        self.assertEqual(config.stale_after_minutes, 15)
        self.assertEqual(config.low_quota_threshold, 10.0)
        self.assertEqual(config.providers, {"codex": True, "claude": True, "openai_api": False})
        self.assertEqual(
            config.notifications,
            {"enabled": True, "low_quota": True, "provider_errors": True, "stale": True},
        )

    def test_invalid_json_uses_defaults_and_reports_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text("{not-json")
            config, error = load_config(path)
        self.assertIsNotNone(error)
        self.assertEqual(config.providers["codex"], True)
        self.assertEqual(config.providers["openai_api"], False)

    def test_partial_config_merges_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text(json.dumps({
                "refresh_interval_seconds": 60,
                "providers": {"claude": False, "unknown": True},
                "notifications": {"provider_errors": False, "unknown": False},
            }))
            config, error = load_config(path)
        self.assertIsNone(error)
        self.assertEqual(config.refresh_interval_seconds, 60)
        self.assertEqual(config.stale_after_minutes, 15)
        self.assertEqual(config.providers, {"codex": True, "claude": False, "openai_api": False})
        self.assertEqual(
            config.notifications,
            {"enabled": True, "low_quota": True, "provider_errors": False, "stale": True},
        )

    def test_invalid_values_are_normalized_to_defaults(self) -> None:
        config = TokenBarConfig(
            refresh_interval_seconds=0,
            stale_after_minutes=-1,
            low_quota_threshold=120.0,
            providers={"codex": "yes", "claude": False},
            notifications={"enabled": "yes", "stale": False},
        ).normalized()
        self.assertEqual(config.refresh_interval_seconds, 120)
        self.assertEqual(config.stale_after_minutes, 15)
        self.assertEqual(config.low_quota_threshold, 10.0)
        self.assertEqual(config.providers, {"codex": True, "claude": False, "openai_api": False})
        self.assertEqual(
            config.notifications,
            {"enabled": True, "low_quota": True, "provider_errors": True, "stale": False},
        )

    @patch.dict("os.environ", {"XDG_CONFIG_HOME": "/tmp/tokenbar-config-home"}, clear=True)
    def test_config_path_uses_xdg_config_home(self) -> None:
        self.assertEqual(config_path(), Path("/tmp/tokenbar-config-home/tokenbar/config.json"))

    def test_config_dump_includes_load_error(self) -> None:
        payload = config_as_jsonable(TokenBarConfig(), "bad config")
        self.assertEqual(payload["load_error"], "bad config")
        self.assertIn("providers", payload)

    def test_ensure_config_file_creates_default_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "tokenbar" / "config.json"
            result_path, created = ensure_config_file(path)
            config, error = load_config(path)
        self.assertEqual(result_path, path)
        self.assertTrue(created)
        self.assertIsNone(error)
        self.assertEqual(config.providers, {"codex": True, "claude": True, "openai_api": False})

    def test_ensure_config_file_does_not_overwrite_existing_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "tokenbar" / "config.json"
            path.parent.mkdir(parents=True)
            path.write_text('{"refresh_interval_seconds": 60}')
            _result_path, created = ensure_config_file(path)
            content = path.read_text()
        self.assertFalse(created)
        self.assertIn("60", content)


if __name__ == "__main__":
    unittest.main()
