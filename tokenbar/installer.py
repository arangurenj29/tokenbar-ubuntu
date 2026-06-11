from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Any

APP_ID = "tokenbar"
APP_NAME = "TokenBar"
VERSION_FILENAME = "VERSION"


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def local_bin_dir() -> Path:
    return Path.home() / ".local" / "bin"


def local_share_dir() -> Path:
    data_home = os.environ.get("XDG_DATA_HOME")
    base = Path(data_home).expanduser() if data_home else Path.home() / ".local" / "share"
    return base


def install_root() -> Path:
    return local_share_dir() / APP_ID


def installed_app_root() -> Path:
    return install_root() / "app"


def installed_wrapper_path() -> Path:
    return local_bin_dir() / APP_ID


def installed_desktop_path() -> Path:
    return local_share_dir() / "applications" / f"{APP_ID}.desktop"


def installed_icon_path() -> Path:
    return local_share_dir() / "icons" / "hicolor" / "scalable" / "apps" / f"{APP_ID}.svg"


def dependency_report() -> dict[str, Any]:
    report: dict[str, Any] = {
        "python3": shutil.which("python3") is not None,
        "notify_send": shutil.which("notify-send") is not None,
        "xdg_open": shutil.which("xdg-open") is not None,
        "zenity": shutil.which("zenity") is not None,
        "gtk": False,
        "indicator": False,
        "errors": [],
    }
    probe = (
        "import gi; "
        "gi.require_version('Gtk','3.0'); "
        "from gi.repository import Gtk; "
        "Gtk.init_check(None)"
    )
    result = subprocess.run(["python3", "-c", probe], capture_output=True, text=True)
    report["gtk"] = result.returncode == 0
    if result.returncode != 0:
        report["errors"].append(result.stderr.strip() or result.stdout.strip())

    indicator_probe = (
        "import gi; "
        "gi.require_version('AyatanaAppIndicator3','0.1'); "
        "from gi.repository import AyatanaAppIndicator3"
    )
    indicator = subprocess.run(["python3", "-c", indicator_probe], capture_output=True, text=True)
    report["indicator"] = indicator.returncode == 0
    if indicator.returncode != 0:
        report["errors"].append(indicator.stderr.strip() or indicator.stdout.strip())
    return report


def install_user() -> dict[str, str]:
    return install_from_source(project_root(), version=read_source_version(project_root()))


def install_from_source(source_root: Path, *, version: str | None = None) -> dict[str, str]:
    app_root = installed_app_root()
    if app_root.exists():
        shutil.rmtree(app_root)
    app_root.mkdir(parents=True, exist_ok=True)

    shutil.copytree(source_root / "tokenbar", app_root / "tokenbar")
    for filename in ("README.md", "LICENSE"):
        source = source_root / filename
        if source.exists():
            shutil.copy2(source, app_root / filename)
    if (source_root / "docs").exists():
        shutil.copytree(source_root / "docs", app_root / "docs")
    (app_root / VERSION_FILENAME).write_text((version or read_source_version(source_root)) + "\n")

    wrapper = installed_wrapper_path()
    wrapper.parent.mkdir(parents=True, exist_ok=True)
    wrapper.write_text(_wrapper_script(app_root))
    wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    icon = installed_icon_path()
    icon.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_root / "tokenbar" / "assets" / "icons" / "tokenbar-ok.svg", icon)

    desktop = installed_desktop_path()
    desktop.parent.mkdir(parents=True, exist_ok=True)
    desktop.write_text(desktop_entry(wrapper, icon_name=APP_ID))

    return {
        "app_root": str(app_root),
        "wrapper": str(wrapper),
        "desktop": str(desktop),
        "icon": str(icon),
    }


def uninstall_user(*, purge_user_data: bool = False) -> dict[str, str]:
    removed: dict[str, str] = {}
    for key, path in {
        "app_root": install_root(),
        "wrapper": installed_wrapper_path(),
        "desktop": installed_desktop_path(),
        "icon": installed_icon_path(),
    }.items():
        if path.is_dir():
            shutil.rmtree(path)
            removed[key] = str(path)
        elif path.exists():
            path.unlink()
            removed[key] = str(path)

    if purge_user_data:
        for key, path in {
            "config": Path.home() / ".config" / APP_ID,
            "cache": Path.home() / ".cache" / APP_ID,
        }.items():
            if path.exists():
                shutil.rmtree(path)
                removed[key] = str(path)
    return removed


def installed_version(path: Path | None = None) -> str | None:
    path = path or installed_app_root() / VERSION_FILENAME
    if not path.exists():
        return None
    value = path.read_text().strip()
    return value or None


def read_source_version(source_root: Path) -> str:
    version_path = source_root / VERSION_FILENAME
    if version_path.exists():
        version = version_path.read_text().strip()
        if version:
            return version
    return "source"


def desktop_entry(exec_path: Path, *, icon_name: str = APP_ID) -> str:
    return "\n".join([
        "[Desktop Entry]",
        "Type=Application",
        f"Name={APP_NAME}",
        "Comment=Codex and Claude quota tray monitor",
        f"Exec={exec_path}",
        f"Icon={icon_name}",
        "Terminal=false",
        "Categories=Utility;",
        "",
    ])


def _wrapper_script(app_root: Path) -> str:
    return "\n".join([
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        f"cd {str(app_root)!r}",
        'exec python3 -B -m tokenbar "$@"',
        "",
    ])
