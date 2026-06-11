from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from tokenbar import updater
from tokenbar.updater import UpdateStatus


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class UpdaterTests(unittest.TestCase):
    @patch("tokenbar.updater.urllib.request.urlopen")
    def test_latest_version_reads_branch_sha(self, urlopen) -> None:
        urlopen.return_value = _FakeResponse({"commit": {"sha": "abc123"}})
        self.assertEqual(updater.latest_version(), "abc123")

    @patch("tokenbar.updater.latest_version", return_value="remote")
    @patch("tokenbar.updater.installed_version", return_value="local")
    def test_check_for_update_detects_new_version(self, _installed, _latest) -> None:
        status = updater.check_for_update()
        self.assertTrue(status.update_available)
        self.assertEqual(status.installed_version, "local")
        self.assertEqual(status.latest_version, "remote")

    def test_update_status_as_dict(self) -> None:
        status = UpdateStatus("old", "new", True)
        self.assertEqual(status.as_dict()["repository"], "arangurenj29/tokenbar-ubuntu")
        self.assertTrue(status.as_dict()["update_available"])

    @patch("tokenbar.updater.check_for_update", return_value=UpdateStatus("same", "same", False))
    def test_update_now_skips_when_current(self, _check) -> None:
        result = updater.update_now()
        self.assertFalse(result["updated"])
        self.assertEqual(result["latest_version"], "same")

    @patch("tokenbar.updater.install_from_source", return_value={"app_root": "/tmp/app"})
    @patch("tokenbar.updater.check_for_update", return_value=UpdateStatus("old", "new", True))
    @patch("tokenbar.updater.urllib.request.urlretrieve")
    def test_update_now_downloads_zip_and_installs(self, urlretrieve, _check, install_from_source) -> None:
        def write_zip(_url, filename):
            root = "tokenbar-ubuntu-main"
            with zipfile.ZipFile(filename, "w") as zf:
                zf.writestr(f"{root}/tokenbar/__init__.py", "")
            return filename, None

        urlretrieve.side_effect = write_zip
        result = updater.update_now()
        self.assertTrue(result["updated"])
        self.assertEqual(result["latest_version"], "new")
        install_from_source.assert_called_once()
        self.assertEqual(install_from_source.call_args.kwargs["version"], "new")

    def test_single_extracted_root_rejects_missing_tokenbar_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "repo"
            root.mkdir()
            with self.assertRaises(ValueError):
                updater._single_extracted_root(Path(temp_dir))


if __name__ == "__main__":
    unittest.main()
