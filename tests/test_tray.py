from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from tokenbar import tray
from tokenbar.providers import Snapshot


class TrayTests(unittest.TestCase):
    def test_display_environment_available_false_when_missing(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(tray.display_environment_available())

    def test_format_usage_bar_shows_remaining_percent(self) -> None:
        self.assertEqual(tray.format_usage_bar(40, width=10), "██████░░░░")

    def test_format_usage_bar_for_missing_value(self) -> None:
        self.assertEqual(tray.format_usage_bar(None, width=10), "──────────")

    def test_countdown_until_formats_duration(self) -> None:
        result = tray.countdown_until("2026-06-11 14:15", now=datetime(2026, 6, 11, 12, 0))
        self.assertEqual(result, "2h 15m")

    def test_time_ago_formats_recent_refresh(self) -> None:
        result = tray.time_ago(datetime(2026, 6, 11, 12, 0), now=datetime(2026, 6, 11, 12, 7))
        self.assertEqual(result, "7m ago")

    def test_is_stale_after_threshold(self) -> None:
        stale = tray.is_stale(
            datetime(2026, 6, 11, 12, 0),
            now=datetime(2026, 6, 11, 12, 16),
            threshold=timedelta(minutes=15),
        )
        self.assertTrue(stale)

    def test_refresh_status_line_shows_stale(self) -> None:
        line = tray.refresh_status_line(
            datetime(2026, 6, 11, 12, 0),
            now=datetime(2026, 6, 11, 12, 20),
        )
        self.assertIn("Stale", line)
        self.assertIn("20m ago", line)

    def test_refresh_status_line_marks_cached_data(self) -> None:
        line = tray.refresh_status_line(
            datetime(2026, 6, 11, 12, 0),
            now=datetime(2026, 6, 11, 12, 7),
            cached=True,
        )
        self.assertIn("Updated 7m ago", line)
        self.assertIn("cached", line)

    def test_snapshot_is_low_quota(self) -> None:
        snapshot = Snapshot("claude", "oauth", True, "8% left", 92.0, None, None)
        self.assertTrue(tray.snapshot_is_low_quota(snapshot))

    def test_icon_path_warns_for_low_quota(self) -> None:
        snapshot = Snapshot("claude", "oauth", True, "8% left", 92.0, None, None)
        self.assertTrue(tray.icon_path_for_snapshots([snapshot]).endswith("tokenbar-warn.svg"))

    def test_icon_path_uses_configured_low_quota_threshold(self) -> None:
        snapshot = Snapshot("claude", "oauth", True, "15% left", 85.0, None, None)
        self.assertTrue(
            tray.icon_path_for_snapshots(
                [snapshot],
                low_quota_threshold=20.0,
            ).endswith("tokenbar-warn.svg")
        )

    def test_icon_path_errors_for_refresh_error(self) -> None:
        self.assertTrue(tray.icon_path_for_snapshots([], refresh_error=True).endswith("tokenbar-error.svg"))

    def test_provider_line_shows_bar_and_left_percent(self) -> None:
        snapshot = Snapshot(
            "codex",
            "oauth",
            True,
            "61% left",
            39.0,
            "2026-06-11 12:50",
            "Plan plus",
            None,
            7.0,
            "2026-06-18 12:50",
        )
        line = tray.provider_line(snapshot)
        self.assertIn("Codex", line)
        self.assertIn("61% left", line)
        self.assertNotIn("39%", line)
        self.assertIn("[", line)
        self.assertIn("5h reset", line)
        self.assertIn("weekly", line)

    def test_provider_menu_lines_puts_details_below_bar(self) -> None:
        snapshot = Snapshot(
            "codex",
            "oauth",
            True,
            "61% left",
            39.0,
            "2026-06-11 12:50",
            "Plan plus",
            None,
            7.0,
            "2026-06-18 12:50",
        )
        primary, secondary = tray.provider_menu_lines(snapshot)
        self.assertIn("61% left", primary)
        self.assertIn("[", primary)
        self.assertNotIn("reset", primary)
        self.assertIsNotNone(secondary)
        self.assertIn("5h reset", secondary or "")
        self.assertIn("weekly", secondary or "")
        self.assertIn("Plan plus", secondary or "")

    def test_provider_line_handles_missing_utilization(self) -> None:
        snapshot = Snapshot("codex", "oauth", True, "Usage unavailable", None, None, None)
        line = tray.provider_line(snapshot)
        self.assertIn("unavailable", line)
        self.assertNotIn("%", line)

    def test_provider_line_handles_error_state(self) -> None:
        snapshot = Snapshot("claude", "oauth", False, "HTTP 401", None, None, None, "unauthorized")
        line = tray.provider_line(snapshot)
        self.assertIn("🔴", line)
        self.assertIn("unauthorized", line)

    def test_provider_menu_lines_renders_guidance_below_failure(self) -> None:
        snapshot = Snapshot(
            "codex",
            "oauth",
            False,
            "auth missing",
            status_label="auth missing",
            guidance="Run: codex login",
            error="raw technical path",
        )
        primary, secondary = tray.provider_menu_lines(snapshot)
        self.assertIn("auth missing", primary)
        self.assertIsNotNone(secondary)
        self.assertIn("Run: codex login", secondary or "")
        self.assertNotIn("raw technical path", secondary or "")

    def test_provider_line_marks_low_quota(self) -> None:
        snapshot = Snapshot("claude", "oauth", True, "8% left", 92.0, None, "Plan pro")
        line = tray.provider_line(snapshot)
        self.assertIn("8% left", line)
        self.assertIn("LOW", line)

    def test_provider_line_uses_configured_low_quota_threshold(self) -> None:
        snapshot = Snapshot("claude", "oauth", True, "15% left", 85.0, None, "Plan pro")
        line = tray.provider_line(snapshot, low_quota_threshold=20.0)
        self.assertIn("15% left", line)
        self.assertIn("LOW", line)

    @patch("tokenbar.tray.GLib.timeout_add_seconds")
    @patch("tokenbar.tray.show_info")
    @patch("tokenbar.tray.launch_interactive_auth")
    def test_sign_in_provider_opens_terminal_and_schedules_refresh(self, launch_auth, show_info, timeout_add) -> None:
        launch_auth.return_value.ok = True
        launch_auth.return_value.message = "Opened terminal for Claude sign-in."
        app = object.__new__(tray.TokenBarTray)
        app._sign_in_provider("claude")
        launch_auth.assert_called_once_with("claude")
        show_info.assert_called_once_with("Opened terminal for Claude sign-in.")
        timeout_add.assert_called_once()

    @patch("tokenbar.tray.show_command_dialog")
    @patch("tokenbar.tray.launch_interactive_auth")
    def test_sign_in_provider_shows_manual_command_when_terminal_missing(self, launch_auth, show_dialog) -> None:
        launch_auth.return_value.ok = False
        launch_auth.return_value.command = "codex login"
        launch_auth.return_value.message = "Could not open a terminal"
        app = object.__new__(tray.TokenBarTray)
        app._sign_in_provider("codex")
        show_dialog.assert_called_once_with("codex login", "Could not open a terminal")

    def test_provider_display_name_polishes_known_names(self) -> None:
        self.assertEqual(tray.provider_display_name("codex"), "Codex")
        self.assertEqual(tray.provider_display_name("claude"), "Claude")
        self.assertEqual(tray.provider_display_name("openai_api"), "OpenAI API")
        self.assertEqual(tray.provider_display_name("other_provider"), "Other Provider")

    def test_main_menu_keeps_only_refresh_settings_and_quit_actions(self) -> None:
        self.assertEqual(tray.main_menu_action_labels(), ["↻ Refresh now", "⚙ Settings…", "Quit"])

    def test_settings_window_collects_secondary_actions(self) -> None:
        sections = tray.settings_window_sections()
        self.assertIn("Sign in to Claude", sections["Authentication"])
        self.assertIn("Diagnostics", sections["General"])
        self.assertIn("Update now", sections["Updates"])
        flattened = [label for labels in sections.values() for label in labels]
        self.assertNotIn("Copy Claude login command", flattened)

    def test_check_tray_support_handles_missing_display(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            ok, message = tray.check_tray_support()
        self.assertFalse(ok)
        self.assertIn("No GUI session detected", message)

    @patch("tokenbar.tray.gtk_display_ready", return_value=False)
    def test_check_tray_support_handles_gtk_failure(self, _gtk_ready) -> None:
        with patch.dict(os.environ, {"WAYLAND_DISPLAY": "wayland-0"}, clear=True):
            ok, message = tray.check_tray_support()
        self.assertFalse(ok)
        self.assertIn("GTK could not connect", message)

    @patch("tokenbar.tray.detect_indicator_backend", return_value=("AyatanaAppIndicator3", object(), None))
    @patch("tokenbar.tray.gtk_display_ready", return_value=True)
    def test_check_tray_support_prefers_ayatana(self, _gtk_ready, _detect) -> None:
        with patch.dict(os.environ, {"WAYLAND_DISPLAY": "wayland-0"}, clear=True):
            ok, message = tray.check_tray_support()
        self.assertTrue(ok)
        self.assertIn("AyatanaAppIndicator3", message)

    @patch("tokenbar.tray.detect_indicator_backend", return_value=(None, None, "missing typelib"))
    @patch("tokenbar.tray.gtk_display_ready", return_value=True)
    def test_check_tray_support_falls_back_to_status_icon(self, _gtk_ready, _detect) -> None:
        with patch.dict(os.environ, {"WAYLAND_DISPLAY": "wayland-0"}, clear=True):
            ok, message = tray.check_tray_support()
        self.assertTrue(ok)
        self.assertIn("GtkStatusIcon", message)


if __name__ == "__main__":
    unittest.main()
