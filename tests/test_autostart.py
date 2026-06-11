from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tokenbar.autostart import autostart_path, autostart_status, desktop_entry, install_autostart, launcher_path, remove_autostart


class AutostartTests(unittest.TestCase):
    @patch.dict("os.environ", {"XDG_CONFIG_HOME": "/tmp/tokenbar-config-home"}, clear=True)
    def test_autostart_path_uses_xdg_config_home(self) -> None:
        self.assertEqual(autostart_path(), Path("/tmp/tokenbar-config-home/autostart/tokenbar.desktop"))

    def test_desktop_entry_contains_exec_path(self) -> None:
        entry = desktop_entry(Path("/tmp/tokenbar/run.sh"))
        self.assertIn("Name=TokenBar", entry)
        self.assertIn("Exec=/tmp/tokenbar/run.sh", entry)

    def test_install_and_remove_autostart(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "tokenbar.desktop"
            install_autostart(path, Path("/tmp/tokenbar/run.sh"))
            enabled = autostart_status(path)
            removed_path, removed = remove_autostart(path)
            disabled = autostart_status(path)
        self.assertEqual(enabled, "enabled")
        self.assertEqual(removed_path, path)
        self.assertTrue(removed)
        self.assertEqual(disabled, "disabled")

    def test_launcher_path_prefers_installed_wrapper(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            wrapper = Path(home) / ".local" / "bin" / "tokenbar"
            wrapper.parent.mkdir(parents=True)
            wrapper.write_text("#!/usr/bin/env bash\n")
            with patch("pathlib.Path.home", return_value=Path(home)):
                self.assertEqual(launcher_path(), wrapper)


if __name__ == "__main__":
    unittest.main()
