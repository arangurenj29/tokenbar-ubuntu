from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import GLib, Gtk, Gdk

from .autostart import autostart_status, install_autostart, remove_autostart
from .cache import load_snapshot_cache, save_snapshot_cache
from .config import TokenBarConfig, ensure_config_file
from .diagnostics import collect_diagnostics, format_diagnostics_text
from .notifications import clear_alert_state, process_alerts, snooze_alerts
from .providers import Snapshot, collect_snapshots, remaining_pct, top_line
from .updater import check_for_update, update_now

TrayBackendName = str
LOW_QUOTA_THRESHOLD = 10.0
STALE_AFTER = timedelta(minutes=15)
ASSET_DIR = Path(__file__).resolve().parent / "assets" / "icons"
ICON_FILES = {
    "ok": ASSET_DIR / "tokenbar-ok.svg",
    "warn": ASSET_DIR / "tokenbar-warn.svg",
    "error": ASSET_DIR / "tokenbar-error.svg",
}


def display_environment_available() -> bool:
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def gtk_display_ready() -> bool:
    ok, _argv = Gtk.init_check(None)
    return bool(ok)


def detect_indicator_backend() -> tuple[TrayBackendName | None, Any | None, str | None]:
    errors: list[str] = []
    for namespace in ("AyatanaAppIndicator3", "AppIndicator3"):
        try:
            gi.require_version(namespace, "0.1")
            module = __import__("gi.repository", fromlist=[namespace])
            indicator_module = getattr(module, namespace)
            return namespace, indicator_module, None
        except Exception as exc:
            errors.append(f"{namespace}: {type(exc).__name__}: {exc}")
    return None, None, " | ".join(errors)


def snapshot_left_pct(snapshot: Snapshot) -> float | None:
    return remaining_pct(snapshot.utilization_pct)


def snapshot_is_low_quota(snapshot: Snapshot, threshold: float = LOW_QUOTA_THRESHOLD) -> bool:
    left = snapshot_left_pct(snapshot)
    return snapshot.ok and left is not None and left <= threshold


def icon_path_for_snapshots(
    snapshots: list[Snapshot],
    *,
    stale: bool = False,
    refresh_error: bool = False,
    low_quota_threshold: float = LOW_QUOTA_THRESHOLD,
) -> str:
    if refresh_error or any(not snapshot.ok for snapshot in snapshots):
        return str(ICON_FILES["error"])
    if stale or any(snapshot_is_low_quota(snapshot, threshold=low_quota_threshold) for snapshot in snapshots):
        return str(ICON_FILES["warn"])
    return str(ICON_FILES["ok"])


def format_usage_bar(utilization_pct: float | None, width: int = 10) -> str:
    left = remaining_pct(utilization_pct)
    if left is None:
        return "──────────"
    filled = min(width, int(round((left / 100.0) * width)))
    return "█" * filled + "░" * (width - filled)


def provider_state_icon(snapshot: Snapshot, *, low_quota_threshold: float = LOW_QUOTA_THRESHOLD) -> str:
    if not snapshot.ok:
        return "🔴"
    if snapshot_is_low_quota(snapshot, threshold=low_quota_threshold):
        return "🔴"
    left = snapshot_left_pct(snapshot)
    if left is not None and left <= 25:
        return "🟠"
    return "🟢"


def _parse_local_reset(reset_at: str) -> datetime | None:
    try:
        return datetime.strptime(reset_at, "%Y-%m-%d %H:%M")
    except ValueError:
        return None


def countdown_until(reset_at: str | None, *, now: datetime | None = None) -> str | None:
    if not reset_at:
        return None
    reset = _parse_local_reset(reset_at)
    if reset is None:
        return reset_at
    now = now or datetime.now()
    total_minutes = int((reset - now).total_seconds() // 60)
    if total_minutes <= 0:
        return "now"
    days, rem = divmod(total_minutes, 24 * 60)
    hours, minutes = divmod(rem, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def reset_summary(snapshot: Snapshot) -> str | None:
    parts: list[str] = []
    five_hour = countdown_until(snapshot.reset_at)
    weekly = countdown_until(snapshot.weekly_reset_at)
    if five_hour:
        parts.append(f"5h reset in {five_hour}")
    if weekly:
        parts.append(f"weekly in {weekly}")
    return " · ".join(parts) if parts else None


def time_ago(dt: datetime | None, *, now: datetime | None = None) -> str:
    if dt is None:
        return "never updated"
    now = now or datetime.now()
    total_seconds = int((now - dt).total_seconds())
    if total_seconds < 0:
        total_seconds = 0
    if total_seconds < 60:
        return "just now"
    minutes = total_seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours, rem_minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h {rem_minutes}m ago"
    days, rem_hours = divmod(hours, 24)
    return f"{days}d {rem_hours}h ago"


def is_stale(last_successful_refresh: datetime | None, *, now: datetime | None = None, threshold: timedelta = STALE_AFTER) -> bool:
    if last_successful_refresh is None:
        return False
    now = now or datetime.now()
    return now - last_successful_refresh >= threshold


def refresh_status_line(
    last_successful_refresh: datetime | None,
    *,
    is_refreshing: bool = False,
    last_refresh_error: str | None = None,
    cached: bool = False,
    now: datetime | None = None,
) -> str:
    parts: list[str] = []
    if is_refreshing:
        parts.append("Refreshing…")
    if last_successful_refresh is None:
        parts.append("Updated: pending")
    elif is_stale(last_successful_refresh, now=now):
        parts.append(f"Stale · updated {time_ago(last_successful_refresh, now=now)}")
    else:
        parts.append(f"Updated {time_ago(last_successful_refresh, now=now)}")
    if cached:
        parts.append("cached")
    if last_refresh_error:
        parts.append(f"Last error: {last_refresh_error}")
    return " · ".join(parts)


def provider_menu_lines(
    snapshot: Snapshot,
    *,
    low_quota_threshold: float = LOW_QUOTA_THRESHOLD,
) -> tuple[str, str | None]:
    icon = provider_state_icon(snapshot, low_quota_threshold=low_quota_threshold)
    label = provider_display_name(snapshot.provider)
    left = remaining_pct(snapshot.utilization_pct)
    if left is None:
        primary = f"{icon} {label}: {snapshot.status_label or 'unavailable'}"
    else:
        bar = format_usage_bar(snapshot.utilization_pct)
        low_suffix = " · LOW" if snapshot_is_low_quota(snapshot, threshold=low_quota_threshold) else ""
        primary = f"{icon} {label}: [{bar}] {left:.0f}% left{low_suffix}"

    details: list[str] = []
    if snapshot.status_label and snapshot.status_label != snapshot.summary:
        details.append(snapshot.status_label)
    resets = reset_summary(snapshot)
    if resets:
        details.append(resets)
    if snapshot.detail:
        details.append(snapshot.detail)
    if snapshot.guidance:
        details.append(snapshot.guidance)
    elif snapshot.error:
        details.append(snapshot.error)
    return primary, "   " + " · ".join(details) if details else None


def provider_line(snapshot: Snapshot, *, low_quota_threshold: float = LOW_QUOTA_THRESHOLD) -> str:
    primary, secondary = provider_menu_lines(snapshot, low_quota_threshold=low_quota_threshold)
    return f"{primary}\n{secondary}" if secondary else primary


def provider_display_name(provider: str) -> str:
    names = {
        "codex": "Codex",
        "claude": "Claude",
        "openai": "OpenAI API",
        "openai_api": "OpenAI API",
    }
    return names.get(provider, provider.replace("_", " ").title())


def provider_login_command(provider: str) -> str | None:
    commands = {
        "codex": "codex login",
        "claude": "claude auth login",
        "openai": "export OPENAI_ADMIN_KEY=...",
        "openai_api": "export OPENAI_ADMIN_KEY=...",
    }
    return commands.get(provider)


def copy_text_to_clipboard(text: str) -> tuple[bool, str]:
    helpers = []
    if os.environ.get("WAYLAND_DISPLAY") and shutil.which("wl-copy"):
        helpers.append((["wl-copy"], "wl-copy"))
    if os.environ.get("DISPLAY") and shutil.which("xclip"):
        helpers.append((["xclip", "-selection", "clipboard"], "xclip"))
    if os.environ.get("DISPLAY") and shutil.which("xsel"):
        helpers.append((["xsel", "--clipboard", "--input"], "xsel"))

    errors: list[str] = []
    for command, name in helpers:
        try:
            subprocess.run(command, input=text, text=True, timeout=3, check=True)
            return True, name
        except Exception as exc:
            errors.append(f"{name}: {type(exc).__name__}: {exc}")

    try:
        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        clipboard.set_text(text, -1)
        clipboard.store()
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        copied = clipboard.wait_for_text()
        if copied == text:
            return True, "Gtk clipboard"
        errors.append("Gtk clipboard did not echo copied text")
    except Exception as exc:
        errors.append(f"Gtk clipboard: {type(exc).__name__}: {exc}")

    detail = "; ".join(errors) if errors else "no clipboard helper available"
    return False, detail


def launch_desktop_path(path: Path) -> None:
    subprocess.Popen(["xdg-open", str(path)])


def show_info(message: str) -> None:
    try:
        subprocess.Popen(["zenity", "--info", f"--text={message}"])
    except FileNotFoundError:
        print(message)


class BaseTray:
    def set_icon(self, icon_path: str) -> None:
        raise NotImplementedError

    def set_tooltip(self, text: str) -> None:
        raise NotImplementedError

    def attach_menu(self, menu: Gtk.Menu) -> None:
        raise NotImplementedError


class AyatanaTray(BaseTray):
    def __init__(self, indicator_module: Any) -> None:
        indicator_cls = indicator_module.Indicator
        category = indicator_module.IndicatorCategory.APPLICATION_STATUS
        self.indicator = indicator_cls.new("tokenbar", str(ICON_FILES["ok"]), category)
        self.indicator.set_status(indicator_module.IndicatorStatus.ACTIVE)
        self.indicator.set_title("TokenBar")

    def set_icon(self, icon_path: str) -> None:
        self.indicator.set_icon_full(icon_path, "TokenBar")

    def set_tooltip(self, text: str) -> None:
        self.indicator.set_title(f"TokenBar — {text}")

    def attach_menu(self, menu: Gtk.Menu) -> None:
        self.indicator.set_menu(menu)


class GtkStatusIconTray(BaseTray):
    def __init__(self, menu: Gtk.Menu, on_activate) -> None:
        self.icon = Gtk.StatusIcon()
        self.icon.set_visible(True)
        self.icon.connect("popup-menu", self._on_popup_menu)
        self.icon.connect("activate", on_activate)
        self.menu = menu

    def _on_popup_menu(self, _icon, button, activate_time) -> None:
        self.menu.popup(None, None, Gtk.StatusIcon.position_menu, self.icon, button, activate_time)

    def set_icon(self, icon_path: str) -> None:
        self.icon.set_from_file(icon_path)

    def set_tooltip(self, text: str) -> None:
        self.icon.set_tooltip_text(text)

    def attach_menu(self, _menu: Gtk.Menu) -> None:
        return


class TokenBarTray:
    def __init__(
        self,
        backend_name: TrayBackendName,
        indicator_module: Any | None = None,
        config: TokenBarConfig | None = None,
    ) -> None:
        self.config = (config or TokenBarConfig()).normalized()
        self.stale_after = timedelta(minutes=self.config.stale_after_minutes)
        self.menu = Gtk.Menu()
        self.header = Gtk.MenuItem(label=f"TokenBar ({backend_name})")
        self.header.set_sensitive(False)
        self.menu.append(self.header)
        self.status_item = Gtk.MenuItem(label=refresh_status_line(None))
        self.status_item.set_sensitive(False)
        self.menu.append(self.status_item)
        self.menu.append(Gtk.SeparatorMenuItem())
        self.items: list[Gtk.MenuItem] = []
        self.menu.append(Gtk.SeparatorMenuItem())
        self.last_successful_refresh: datetime | None = None
        self.last_refresh_error: str | None = None
        self.cached_snapshot_loaded = False
        self.is_refreshing = False
        self._refresh_lock = threading.Lock()
        refresh_item = Gtk.MenuItem(label="↻ Refresh now")
        refresh_item.connect("activate", lambda *_: self.refresh())
        self.menu.append(refresh_item)
        dump_item = Gtk.MenuItem(label="⇩ Dump JSON snapshot")
        dump_item.connect("activate", self._dump_json)
        self.menu.append(dump_item)
        diagnostics_item = Gtk.MenuItem(label="🩺 Diagnostics")
        diagnostics_item.connect("activate", self._show_diagnostics)
        self.menu.append(diagnostics_item)
        self.menu.append(self._build_settings_menu())
        self.menu.append(self._build_notifications_menu())
        self.menu.append(self._build_updates_menu())
        self.menu.append(self._build_autostart_menu())
        quit_item = Gtk.MenuItem(label="Quit")
        quit_item.connect("activate", lambda *_: Gtk.main_quit())
        self.menu.append(quit_item)

        if backend_name in ("AyatanaAppIndicator3", "AppIndicator3") and indicator_module is not None:
            self.tray: BaseTray = AyatanaTray(indicator_module)
        else:
            self.tray = GtkStatusIconTray(self.menu, self._on_activate)

        self.tray.attach_menu(self.menu)
        self.menu.show_all()
        self._load_cached_snapshots()
        self.refresh()
        GLib.timeout_add_seconds(self.config.refresh_interval_seconds, self._refresh_timer)

    def _refresh_timer(self) -> bool:
        self.refresh()
        return True

    def _on_activate(self, *_args) -> None:
        self.refresh()
        self.menu.popup(None, None, Gtk.StatusIcon.position_menu, None, 0, Gtk.get_current_event_time())

    def _dump_json(self, *_args) -> None:
        payload = json.dumps([snapshot.__dict__ for snapshot in collect_snapshots(self.config)], indent=2)
        target = Path.home() / ".cache" / "tokenbar-snapshot.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(payload)
        show_info(f"Snapshot written to {target}")

    def _build_settings_menu(self) -> Gtk.MenuItem:
        root = Gtk.MenuItem(label="⚙ Settings / auth")
        menu = Gtk.Menu()

        init_config_item = Gtk.MenuItem(label="Create default config")
        init_config_item.connect("activate", self._init_config)
        menu.append(init_config_item)

        open_config_item = Gtk.MenuItem(label="Open config file")
        open_config_item.connect("activate", self._open_config)
        menu.append(open_config_item)

        menu.append(Gtk.SeparatorMenuItem())

        copy_codex_item = Gtk.MenuItem(label="Copy Codex login command")
        copy_codex_item.connect("activate", lambda *_: self._copy_command("codex"))
        menu.append(copy_codex_item)

        copy_claude_item = Gtk.MenuItem(label="Copy Claude login command")
        copy_claude_item.connect("activate", lambda *_: self._copy_command("claude"))
        menu.append(copy_claude_item)

        root.set_submenu(menu)
        return root

    def _build_notifications_menu(self) -> Gtk.MenuItem:
        root = Gtk.MenuItem(label="🔔 Notifications")
        menu = Gtk.Menu()

        clear_item = Gtk.MenuItem(label="Clear alert state")
        clear_item.connect("activate", self._clear_alerts)
        menu.append(clear_item)

        snooze_1h_item = Gtk.MenuItem(label="Snooze 1 hour")
        snooze_1h_item.connect("activate", lambda *_: self._snooze_alerts(60))
        menu.append(snooze_1h_item)

        snooze_4h_item = Gtk.MenuItem(label="Snooze 4 hours")
        snooze_4h_item.connect("activate", lambda *_: self._snooze_alerts(240))
        menu.append(snooze_4h_item)

        root.set_submenu(menu)
        return root

    def _build_autostart_menu(self) -> Gtk.MenuItem:
        root = Gtk.MenuItem(label=f"🚀 Autostart ({autostart_status()})")
        menu = Gtk.Menu()

        install_item = Gtk.MenuItem(label="Start TokenBar on login")
        install_item.connect("activate", self._install_autostart)
        menu.append(install_item)

        remove_item = Gtk.MenuItem(label="Do not start on login")
        remove_item.connect("activate", self._remove_autostart)
        menu.append(remove_item)

        root.set_submenu(menu)
        return root

    def _build_updates_menu(self) -> Gtk.MenuItem:
        root = Gtk.MenuItem(label="⬆ Updates")
        menu = Gtk.Menu()

        check_item = Gtk.MenuItem(label="Check for updates")
        check_item.connect("activate", self._check_updates)
        menu.append(check_item)

        update_item = Gtk.MenuItem(label="Update now")
        update_item.connect("activate", self._update_now)
        menu.append(update_item)

        root.set_submenu(menu)
        return root

    def _init_config(self, *_args) -> None:
        path, created = ensure_config_file()
        status = "created" if created else "already exists"
        show_info(f"TokenBar config {status}: {path}")

    def _open_config(self, *_args) -> None:
        path, _created = ensure_config_file()
        launch_desktop_path(path)

    def _copy_command(self, provider: str) -> None:
        command = provider_login_command(provider)
        if command is None:
            show_info(f"No login command for provider: {provider}")
            return
        ok, detail = copy_text_to_clipboard(command)
        if ok:
            show_info(f"Copied: {command}")
        else:
            show_info(f"Could not copy automatically. Run manually: {command}\n\nClipboard error: {detail}")

    def _show_diagnostics(self, *_args) -> None:
        diagnostics = collect_diagnostics(
            self.config,
            tray_backend=self.header.get_label().removeprefix("TokenBar (").removesuffix(")"),
            tray_message="running",
        )
        show_info(format_diagnostics_text(diagnostics))

    def _clear_alerts(self, *_args) -> None:
        path = clear_alert_state()
        show_info(f"TokenBar alert state cleared: {path}")

    def _snooze_alerts(self, minutes: int) -> None:
        until = snooze_alerts(minutes)
        show_info(f"TokenBar alerts snoozed until {until.strftime('%Y-%m-%d %H:%M')}")

    def _install_autostart(self, *_args) -> None:
        path = install_autostart()
        show_info(f"TokenBar autostart installed: {path}")

    def _remove_autostart(self, *_args) -> None:
        path, removed = remove_autostart()
        status = "removed" if removed else "already absent"
        show_info(f"TokenBar autostart {status}: {path}")

    def _check_updates(self, *_args) -> None:
        def worker() -> None:
            try:
                status = check_for_update()
                if status.update_available:
                    message = f"Update available: {status.latest_version[:7]}"
                else:
                    message = f"TokenBar is up to date: {status.latest_version[:7]}"
            except Exception as exc:
                message = f"Update check failed: {type(exc).__name__}: {exc}"
            GLib.idle_add(show_info, message)

        threading.Thread(target=worker, daemon=True).start()

    def _update_now(self, *_args) -> None:
        def worker() -> None:
            try:
                result = update_now()
                if result.get("updated"):
                    message = "TokenBar updated. Restart TokenBar to use the new version."
                else:
                    message = "TokenBar is already up to date."
            except Exception as exc:
                message = f"Update failed: {type(exc).__name__}: {exc}"
            GLib.idle_add(show_info, message)

        threading.Thread(target=worker, daemon=True).start()

    def _load_cached_snapshots(self) -> None:
        snapshots, saved_at, error = load_snapshot_cache()
        if error:
            print(f"TokenBar cache ignored: {error}")
            return
        if not snapshots:
            return
        self.last_successful_refresh = saved_at
        self.cached_snapshot_loaded = True
        self._apply_snapshots(snapshots, notify=False)

    def refresh(self) -> bool:
        with self._refresh_lock:
            if self.is_refreshing:
                return False
            self.is_refreshing = True
        self.status_item.set_label(refresh_status_line(
            self.last_successful_refresh,
            is_refreshing=True,
            last_refresh_error=self.last_refresh_error,
            cached=self.cached_snapshot_loaded,
        ))
        threading.Thread(target=self._refresh_worker, daemon=True).start()
        return True

    def _refresh_worker(self) -> None:
        try:
            snapshots = collect_snapshots(self.config)
            error = None
        except Exception as exc:
            snapshots = []
            error = f"{type(exc).__name__}: {exc}"
        GLib.idle_add(self._apply_refresh_result, snapshots, error)

    def _apply_refresh_result(self, snapshots: list[Snapshot], error: str | None) -> bool:
        with self._refresh_lock:
            self.is_refreshing = False
        if error is None:
            refreshed_at = datetime.now()
            self.last_successful_refresh = refreshed_at
            self.last_refresh_error = None
            self.cached_snapshot_loaded = False
            try:
                save_snapshot_cache(snapshots, saved_at=refreshed_at)
            except Exception as exc:
                print(f"TokenBar cache write failed: {type(exc).__name__}: {exc}")
        else:
            self.last_refresh_error = error
        self._apply_snapshots(snapshots)
        return False

    def _apply_snapshots(self, snapshots: list[Snapshot], *, notify: bool = True) -> bool:
        stale = is_stale(self.last_successful_refresh, threshold=self.stale_after)
        self.status_item.set_label(refresh_status_line(
            self.last_successful_refresh,
            is_refreshing=self.is_refreshing,
            last_refresh_error=self.last_refresh_error,
            cached=self.cached_snapshot_loaded,
        ))
        self.tray.set_icon(icon_path_for_snapshots(
            snapshots,
            stale=stale,
            refresh_error=self.last_refresh_error is not None,
            low_quota_threshold=self.config.low_quota_threshold,
        ))
        tooltip = top_line(snapshots)
        if stale:
            tooltip = f"STALE · {tooltip}" if tooltip else "STALE"
        self.tray.set_tooltip(tooltip)
        if notify:
            process_alerts(snapshots, self.config, stale=stale)
        for item in self.items:
            self.menu.remove(item)
        self.items.clear()
        insertion_index = 2
        for snapshot in snapshots:
            primary, secondary = provider_menu_lines(
                snapshot,
                low_quota_threshold=self.config.low_quota_threshold,
            )
            primary_item = Gtk.MenuItem(label=primary)
            primary_item.set_sensitive(False)
            self.menu.insert(primary_item, insertion_index)
            self.items.append(primary_item)
            insertion_index += 1
            if secondary:
                secondary_item = Gtk.MenuItem(label=secondary)
                secondary_item.set_sensitive(False)
                self.menu.insert(secondary_item, insertion_index)
                self.items.append(secondary_item)
                insertion_index += 1
        self.menu.show_all()
        return False


def choose_tray_backend() -> tuple[TrayBackendName | None, Any | None, str]:
    if not display_environment_available():
        return None, None, "No GUI session detected (DISPLAY/WAYLAND_DISPLAY missing)."
    if not gtk_display_ready():
        return None, None, "GTK could not connect to the active display session."

    backend_name, indicator_module, indicator_error = detect_indicator_backend()
    if backend_name is not None:
        return backend_name, indicator_module, f"Using {backend_name}."

    return "GtkStatusIcon", None, (
        "Falling back to GtkStatusIcon. " + (indicator_error or "No AppIndicator backend available.")
    )


def check_tray_support() -> tuple[bool, str]:
    backend_name, _module, message = choose_tray_backend()
    if backend_name is None:
        return False, message
    return True, message


def run(config: TokenBarConfig | None = None) -> int:
    backend_name, indicator_module, message = choose_tray_backend()
    if backend_name is None:
        print(f"TokenBar tray unavailable: {message}")
        return 2
    print(message)
    TokenBarTray(backend_name, indicator_module, config)
    Gtk.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
