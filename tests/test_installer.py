from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tokenbar import installer


class InstallerTests(unittest.TestCase):
    @patch.dict("os.environ", {"XDG_DATA_HOME": "/tmp/tokenbar-data-home"}, clear=True)
    def test_install_paths_use_xdg_data_home(self) -> None:
        self.assertEqual(installer.install_root(), Path("/tmp/tokenbar-data-home/tokenbar"))
        self.assertEqual(installer.installed_app_root(), Path("/tmp/tokenbar-data-home/tokenbar/app"))
        self.assertEqual(
            installer.installed_desktop_path(),
            Path("/tmp/tokenbar-data-home/applications/tokenbar.desktop"),
        )
        self.assertEqual(
            installer.installed_icon_path(),
            Path("/tmp/tokenbar-data-home/icons/hicolor/scalable/apps/tokenbar.svg"),
        )

    def test_desktop_entry_points_to_wrapper_and_icon_name(self) -> None:
        entry = installer.desktop_entry(Path("/home/me/.local/bin/tokenbar"))
        self.assertIn("Name=TokenBar", entry)
        self.assertIn("Exec=/home/me/.local/bin/tokenbar", entry)
        self.assertIn("Icon=tokenbar", entry)
        self.assertIn("Categories=Utility;", entry)

    def test_install_user_copies_app_wrapper_desktop_and_icon(self) -> None:
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as data_home:
            with patch("pathlib.Path.home", return_value=Path(home)):
                with patch.dict("os.environ", {"XDG_DATA_HOME": data_home}, clear=True):
                    result = installer.install_user()
                    wrapper = Path(result["wrapper"])
                    desktop = Path(result["desktop"])
                    icon = Path(result["icon"])
                    package = Path(result["app_root"]) / "tokenbar" / "__main__.py"
                    version = Path(result["app_root"]) / "VERSION"
                    self.assertTrue(wrapper.exists())
                    self.assertTrue(package.exists())
                    self.assertTrue(version.exists())
                    self.assertTrue(desktop.exists())
                    self.assertTrue(icon.exists())
                    self.assertIn("python3 -B -m tokenbar", wrapper.read_text())
                    self.assertTrue(wrapper.stat().st_mode & 0o111)

    def test_install_from_source_writes_supplied_version(self) -> None:
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as data_home:
            with patch("pathlib.Path.home", return_value=Path(home)):
                with patch.dict("os.environ", {"XDG_DATA_HOME": data_home}, clear=True):
                    result = installer.install_from_source(installer.project_root(), version="abc123")
                    version = installer.installed_version(Path(result["app_root"]) / "VERSION")
        self.assertEqual(version, "abc123")

    def test_uninstall_user_removes_install_but_keeps_config_and_cache_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as data_home:
            with patch("pathlib.Path.home", return_value=Path(home)):
                with patch.dict("os.environ", {"XDG_DATA_HOME": data_home}, clear=True):
                    config_dir = Path(home) / ".config" / "tokenbar"
                    cache_dir = Path(home) / ".cache" / "tokenbar"
                    config_dir.mkdir(parents=True)
                    cache_dir.mkdir(parents=True)
                    installer.install_user()
                    removed = installer.uninstall_user()
                    config_exists = config_dir.exists()
                    cache_exists = cache_dir.exists()
                    self.assertIn("app_root", removed)
                    self.assertTrue(config_exists)
                    self.assertTrue(cache_exists)

    def test_uninstall_user_can_purge_config_and_cache(self) -> None:
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as data_home:
            with patch("pathlib.Path.home", return_value=Path(home)):
                with patch.dict("os.environ", {"XDG_DATA_HOME": data_home}, clear=True):
                    config_dir = Path(home) / ".config" / "tokenbar"
                    cache_dir = Path(home) / ".cache" / "tokenbar"
                    config_dir.mkdir(parents=True)
                    cache_dir.mkdir(parents=True)
                    installer.install_user()
                    removed = installer.uninstall_user(purge_user_data=True)
                    config_exists = config_dir.exists()
                    cache_exists = cache_dir.exists()
                    self.assertIn("config", removed)
                    self.assertIn("cache", removed)
                    self.assertFalse(config_exists)
                    self.assertFalse(cache_exists)

    @patch("tokenbar.installer.subprocess.run")
    @patch("tokenbar.installer.shutil.which", return_value="/usr/bin/tool")
    def test_dependency_report_checks_python_gtk_and_indicator(self, _which, run) -> None:
        run.return_value.returncode = 0
        run.return_value.stderr = ""
        run.return_value.stdout = ""
        report = installer.dependency_report()
        self.assertTrue(report["python3"])
        self.assertTrue(report["gtk"])
        self.assertTrue(report["indicator"])
        self.assertTrue(report["clipboard_helper"])


if __name__ == "__main__":
    unittest.main()
