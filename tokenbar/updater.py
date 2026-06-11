from __future__ import annotations

import json
import shutil
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .installer import install_from_source, installed_version

REPOSITORY = "arangurenj29/tokenbar-ubuntu"
BRANCH = "main"
API_BRANCH_URL = f"https://api.github.com/repos/{REPOSITORY}/branches/{BRANCH}"
ZIPBALL_URL = f"https://github.com/{REPOSITORY}/archive/refs/heads/{BRANCH}.zip"


@dataclass(frozen=True)
class UpdateStatus:
    installed_version: str | None
    latest_version: str
    update_available: bool
    repository: str = REPOSITORY
    branch: str = BRANCH

    def as_dict(self) -> dict[str, Any]:
        return {
            "installed_version": self.installed_version,
            "latest_version": self.latest_version,
            "update_available": self.update_available,
            "repository": self.repository,
            "branch": self.branch,
        }


def latest_version(url: str = API_BRANCH_URL) -> str:
    with urllib.request.urlopen(url, timeout=15) as response:
        payload = json.loads(response.read().decode("utf-8"))
    sha = payload.get("commit", {}).get("sha")
    if not isinstance(sha, str) or not sha:
        raise ValueError("GitHub branch response did not include commit.sha")
    return sha


def check_for_update() -> UpdateStatus:
    installed = installed_version()
    latest = latest_version()
    return UpdateStatus(
        installed_version=installed,
        latest_version=latest,
        update_available=installed != latest,
    )


def update_now() -> dict[str, Any]:
    status = check_for_update()
    if not status.update_available:
        return {"updated": False, **status.as_dict()}

    with tempfile.TemporaryDirectory(prefix="tokenbar-update-") as temp_dir:
        archive = Path(temp_dir) / "tokenbar.zip"
        urllib.request.urlretrieve(ZIPBALL_URL, archive)
        extract_dir = Path(temp_dir) / "extract"
        extract_dir.mkdir()
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(extract_dir)
        source_root = _single_extracted_root(extract_dir)
        install_result = install_from_source(source_root, version=status.latest_version)
    return {"updated": True, "install": install_result, **status.as_dict()}


def _single_extracted_root(path: Path) -> Path:
    children = [child for child in path.iterdir() if child.is_dir()]
    if len(children) != 1:
        raise ValueError("Expected GitHub zipball to contain a single root directory")
    root = children[0]
    if not (root / "tokenbar").exists():
        raise ValueError("Downloaded update does not contain tokenbar package")
    return root


def clear_download_cache(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
