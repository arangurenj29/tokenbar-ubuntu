from __future__ import annotations

import unittest
from unittest.mock import patch

from tokenbar.config import TokenBarConfig
from tokenbar.diagnostics import collect_diagnostics, format_diagnostics_text


class DiagnosticsTests(unittest.TestCase):
    @patch.dict("os.environ", {"WAYLAND_DISPLAY": "wayland-0", "XDG_SESSION_TYPE": "wayland"}, clear=True)
    def test_collect_diagnostics_includes_paths_auth_and_config(self) -> None:
        diagnostics = collect_diagnostics(
            TokenBarConfig(refresh_interval_seconds=60),
            config_error="bad config",
            tray_backend="AyatanaAppIndicator3",
            tray_message="Using AyatanaAppIndicator3.",
        )
        self.assertEqual(diagnostics["tray"]["backend"], "AyatanaAppIndicator3")
        self.assertTrue(diagnostics["environment"]["wayland_display"])
        self.assertEqual(diagnostics["config"]["refresh_interval_seconds"], 60)
        self.assertEqual(diagnostics["config_error"], "bad config")
        self.assertIn("codex_auth_exists", diagnostics["auth"])

    def test_format_diagnostics_text_is_readable(self) -> None:
        diagnostics = collect_diagnostics(TokenBarConfig(), tray_backend="GtkStatusIcon", tray_message="fallback")
        text = format_diagnostics_text(diagnostics)
        self.assertIn("TokenBar diagnostics", text)
        self.assertIn("Tray backend: GtkStatusIcon", text)
        self.assertIn("Codex auth:", text)
        self.assertIn("Clipboard helper:", text)


if __name__ == "__main__":
    unittest.main()
