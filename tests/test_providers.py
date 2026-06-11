from __future__ import annotations

import unittest
import urllib.error
from unittest.mock import patch

from tokenbar import providers
from tokenbar.config import TokenBarConfig
from tokenbar.providers import Snapshot


class ProviderTests(unittest.TestCase):
    def test_format_reset_supports_unix_timestamp(self) -> None:
        result = providers._format_reset(1781200227)
        self.assertIsInstance(result, str)
        self.assertIn("2026-06-11", result)

    @patch("tokenbar.providers._request_json")
    @patch("tokenbar.providers._read_json")
    @patch("pathlib.Path.exists", return_value=True)
    def test_fetch_codex_maps_payload(self, _exists, mock_read_json, mock_request_json) -> None:
        mock_read_json.return_value = {"tokens": {"access_token": "tok"}}
        mock_request_json.return_value = {
            "plan_type": "plus",
            "rate_limit": {
                "primary_window": {"used_percent": 23, "reset_at": 1781200227},
                "secondary_window": {"used_percent": 4, "reset_at": 1781748415},
            },
        }
        snapshot = providers.fetch_codex()
        self.assertTrue(snapshot.ok)
        self.assertEqual(snapshot.provider, "codex")
        self.assertEqual(snapshot.summary, "77% left")
        self.assertEqual(snapshot.utilization_pct, 23.0)
        self.assertEqual(snapshot.weekly_utilization_pct, 4.0)
        self.assertIsNotNone(snapshot.weekly_reset_at)

    @patch("tokenbar.providers._request_json")
    @patch("tokenbar.providers._read_json")
    @patch("pathlib.Path.exists", return_value=True)
    def test_fetch_claude_maps_payload(self, _exists, mock_read_json, mock_request_json) -> None:
        mock_read_json.return_value = {"claudeAiOauth": {"accessToken": "tok", "subscriptionType": "pro"}}
        mock_request_json.return_value = {
            "five_hour": {"utilization": 66, "resets_at": "2026-06-11T18:39:59+00:00"},
            "seven_day": {"utilization": 16, "resets_at": "2026-06-12T14:59:59+00:00"},
        }
        snapshot = providers.fetch_claude()
        self.assertTrue(snapshot.ok)
        self.assertEqual(snapshot.provider, "claude")
        self.assertEqual(snapshot.summary, "34% left")
        self.assertEqual(snapshot.utilization_pct, 66.0)
        self.assertEqual(snapshot.weekly_utilization_pct, 16.0)
        self.assertIsNotNone(snapshot.weekly_reset_at)
        self.assertEqual(snapshot.detail, "Plan pro")


    @patch("pathlib.Path.exists", return_value=False)
    def test_fetch_codex_missing_credentials_has_guidance(self, _exists) -> None:
        snapshot = providers.fetch_codex()
        self.assertFalse(snapshot.ok)
        self.assertEqual(snapshot.status_label, "auth missing")
        self.assertEqual(snapshot.guidance, "Run: codex login")

    @patch("tokenbar.providers._read_json", return_value={"tokens": {}})
    @patch("pathlib.Path.exists", return_value=True)
    def test_fetch_codex_missing_token_has_guidance(self, _exists, _read_json) -> None:
        snapshot = providers.fetch_codex()
        self.assertFalse(snapshot.ok)
        self.assertEqual(snapshot.status_label, "auth missing")
        self.assertEqual(snapshot.guidance, "Run: codex login")

    @patch("tokenbar.providers._request_json")
    @patch("tokenbar.providers._read_json", return_value={"tokens": {"access_token": "tok"}})
    @patch("pathlib.Path.exists", return_value=True)
    def test_fetch_codex_http_401_has_auth_guidance(self, _exists, _read_json, mock_request_json) -> None:
        mock_request_json.side_effect = urllib.error.HTTPError("url", 401, "Unauthorized", None, None)
        snapshot = providers.fetch_codex()
        self.assertFalse(snapshot.ok)
        self.assertEqual(snapshot.status_label, "auth expired")
        self.assertEqual(snapshot.guidance, "Run: codex login")
        self.assertEqual(snapshot.error, "HTTP 401")

    @patch("tokenbar.providers._request_json")
    @patch("tokenbar.providers._read_json", return_value={"tokens": {"access_token": "tok"}})
    @patch("pathlib.Path.exists", return_value=True)
    def test_fetch_codex_network_error_has_connection_guidance(self, _exists, _read_json, mock_request_json) -> None:
        mock_request_json.side_effect = urllib.error.URLError("Temporary failure in name resolution")
        snapshot = providers.fetch_codex()
        self.assertFalse(snapshot.ok)
        self.assertEqual(snapshot.status_label, "network unavailable")
        self.assertEqual(snapshot.guidance, "Check internet connection")

    @patch("pathlib.Path.exists", return_value=False)
    def test_fetch_claude_missing_credentials_has_guidance(self, _exists) -> None:
        snapshot = providers.fetch_claude()
        self.assertFalse(snapshot.ok)
        self.assertEqual(snapshot.status_label, "auth missing")
        self.assertEqual(snapshot.guidance, "Run: claude login")

    @patch("tokenbar.providers._request_json")
    @patch("tokenbar.providers._read_json", return_value={"claudeAiOauth": {"accessToken": "tok"}})
    @patch("pathlib.Path.exists", return_value=True)
    def test_fetch_claude_http_403_has_auth_guidance(self, _exists, _read_json, mock_request_json) -> None:
        mock_request_json.side_effect = urllib.error.HTTPError("url", 403, "Forbidden", None, None)
        snapshot = providers.fetch_claude()
        self.assertFalse(snapshot.ok)
        self.assertEqual(snapshot.status_label, "auth expired")
        self.assertEqual(snapshot.guidance, "Run: claude login")

    @patch("tokenbar.providers.fetch_openai_api", return_value=None)
    @patch("tokenbar.providers.fetch_claude", return_value=Snapshot("claude", "oauth", True, "ok"))
    @patch("tokenbar.providers.fetch_codex", return_value=Snapshot("codex", "oauth", True, "ok"))
    def test_collect_snapshots_limits_default_scope(self, _codex, _claude, _openai) -> None:
        snapshots = providers.collect_snapshots()
        self.assertEqual([item.provider for item in snapshots], ["codex", "claude"])

    @patch("tokenbar.providers.fetch_openai_api", return_value=Snapshot("openai", "admin-api", True, "ok"))
    @patch("tokenbar.providers.fetch_claude", return_value=Snapshot("claude", "oauth", True, "ok"))
    @patch("tokenbar.providers.fetch_codex", return_value=Snapshot("codex", "oauth", True, "ok"))
    def test_collect_snapshots_respects_provider_config(self, _codex, _claude, _openai) -> None:
        config = TokenBarConfig(providers={"codex": False, "claude": True, "openai_api": True})
        snapshots = providers.collect_snapshots(config)
        self.assertEqual([item.provider for item in snapshots], ["claude", "openai"])

    @patch("tokenbar.providers.fetch_openai_api")
    @patch("tokenbar.providers.fetch_claude", return_value=Snapshot("claude", "oauth", True, "ok"))
    @patch("tokenbar.providers.fetch_codex", return_value=Snapshot("codex", "oauth", True, "ok"))
    def test_collect_snapshots_does_not_call_disabled_openai_api(self, _codex, _claude, mock_openai) -> None:
        config = TokenBarConfig(providers={"codex": True, "claude": True, "openai_api": False})
        snapshots = providers.collect_snapshots(config)
        self.assertEqual([item.provider for item in snapshots], ["codex", "claude"])
        mock_openai.assert_not_called()


if __name__ == "__main__":
    unittest.main()
