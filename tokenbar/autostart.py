from __future__ import annotations

import os
from pathlib import Path

APP_ID = "tokenbar"


def autostart_dir() -> Path:
    config_home = os.environ.get("XDG_CONFIG_HOME")
    base = Path(config_home).expanduser() if config_home else Path.home() / ".config"
    return base / "autostart"


def autostart_path() -> Path:
    return autostart_dir() / f"{APP_ID}.desktop"


def launcher_path() -> Path:
    installed = Path.home() / ".local" / "bin" / APP_ID
    if installed.exists():
        return installed
    return Path(__file__).resolve().parents[1] / "scripts" / "run_tokenbar.sh"


def desktop_entry(exec_path: Path | None = None) -> str:
    exec_path = exec_path or launcher_path()
    return "\n".join([
        "[Desktop Entry]",
        "Type=Application",
        "Name=TokenBar",
        "Comment=Codex and Claude quota tray monitor",
        f"Exec={exec_path}",
        "Terminal=false",
        "X-GNOME-Autostart-enabled=true",
        "",
    ])


def install_autostart(path: Path | None = None, exec_path: Path | None = None) -> Path:
    path = path or autostart_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(desktop_entry(exec_path))
    return path


def remove_autostart(path: Path | None = None) -> tuple[Path, bool]:
    path = path or autostart_path()
    if path.exists():
        path.unlink()
        return path, True
    return path, False


def autostart_status(path: Path | None = None) -> str:
    path = path or autostart_path()
    return "enabled" if path.exists() else "disabled"
