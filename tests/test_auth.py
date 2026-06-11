from __future__ import annotations

import json
import unittest
from unittest.mock import Mock, patch

from tokenbar import auth


class AuthTests(unittest.TestCase):
    def test_provider_login_command_for_supported_providers(self) -> None:
        self.assertEqual(auth.provider_login_command("codex"), "codex login")
        self.assertEqual(auth.provider_login_command("claude"), "claude auth login")
        self.assertIsNone(auth.provider_login_command("unknown"))

    @patch("tokenbar.auth.subprocess.Popen")
    @patch("tokenbar.auth.shutil.which", side_effect=lambda name: "/usr/bin/gnome-terminal" if name == "gnome-terminal" else None)
    def test_launch_interactive_auth_opens_available_terminal(self, _which, popen) -> None:
        result = auth.launch_interactive_auth("claude")
        self.assertTrue(result.ok)
        self.assertEqual(result.command, "claude auth login")
        self.assertEqual(result.terminal, "gnome-terminal")
        popen.assert_called_once()
        command = popen.call_args.args[0]
        self.assertEqual(command[:3], ["gnome-terminal", "--", "bash"])
        self.assertIn("claude auth login", command[-1])

    @patch("tokenbar.auth.shutil.which", return_value=None)
    def test_launch_interactive_auth_returns_manual_command_without_terminal(self, _which) -> None:
        result = auth.launch_interactive_auth("codex")
        self.assertFalse(result.ok)
        self.assertEqual(result.command, "codex login")
        self.assertIn("Could not open", result.message)

    @patch("tokenbar.auth.shutil.which", return_value="/usr/bin/claude")
    @patch("tokenbar.auth.subprocess.run")
    def test_auth_status_uses_claude_status_json(self, run, _which) -> None:
        run.return_value = Mock(returncode=0, stdout=json.dumps({"email": "user@example.com", "subscriptionType": "pro"}), stderr="")
        ok, message = auth.auth_status("claude")
        self.assertTrue(ok)
        self.assertIn("Claude: signed in", message)
        self.assertIn("user@example.com", message)
        self.assertIn("pro", message)

    @patch("tokenbar.auth.shutil.which", return_value="/usr/bin/claude")
    @patch("tokenbar.auth.subprocess.run")
    def test_auth_status_reports_cli_failure(self, run, _which) -> None:
        run.return_value = Mock(returncode=1, stdout="", stderr="login required")
        ok, message = auth.auth_status("claude")
        self.assertFalse(ok)
        self.assertIn("not signed in", message)
        self.assertIn("login required", message)


if __name__ == "__main__":
    unittest.main()
