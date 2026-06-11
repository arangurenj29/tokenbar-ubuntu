from __future__ import annotations

import json
import os
import subprocess
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import GLib, Gtk, Gdk

from .auth import all_auth_status, launch_interactive_auth, provider_login_command
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


def main_menu_action_labels() -> list[str]:
    return ["↻ Refresh now", "⚙ Settings…", "Quit"]


def settings_window_sections() -> dict[str, list[str]]:
    return {
        "General": ["Create default config", "Open config file", "Dump JSON snapshot", "Diagnostics"],
        "Authentication": ["Sign in to Codex", "Sign in to Claude", "Check auth status"],
        "Notifications": ["Clear alert state", "Snooze 1 hour", "Snooze 4 hours"],
        "Updates": ["Check for updates", "Update now"],
        "Startup": ["Start TokenBar on login", "Do not start on login"],
    }


def launch_desktop_path(path: Path) -> None:
    subprocess.Popen(["xdg-open", str(path)])


def show_info(message: str) -> None:
    try:
        subprocess.Popen(["zenity", "--info", f"--text={message}"])
    except FileNotFoundError:
        print(message)


def show_command_dialog(command: str, detail: str | None = None) -> None:
    dialog = Gtk.MessageDialog(
        transient_for=None,
        flags=0,
        message_type=Gtk.MessageType.INFO,
        buttons=Gtk.ButtonsType.OK,
        text="Run this command manually",
    )
    dialog.format_secondary_text((detail + "\n\n") if detail else "")
    box = dialog.get_content_area()
    entry = Gtk.Entry()
    entry.set_text(command)
    entry.set_editable(False)
    entry.set_can_focus(True)
    entry.select_region(0, -1)
    box.pack_end(entry, False, False, 8)
    dialog.show_all()
    entry.grab_focus()
    dialog.run()
    dialog.destroy()




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
        self.settings_window: Gtk.Window | None = None
        refresh_item = Gtk.MenuItem(label="↻ Refresh now")
        refresh_item.connect("activate", lambda *_: self.refresh())
        self.menu.append(refresh_item)
        settings_item = Gtk.MenuItem(label="⚙ Settings…")
        settings_item.connect("activate", self._open_settings_window)
        self.menu.append(settings_item)
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

    def _open_settings_window(self, *_args) -> None:
        if self.settings_window is not None:
            self.settings_window.present()
            return

        window = Gtk.Window(title="TokenBar Settings")
        window.set_default_size(460, 520)
        window.set_border_width(12)
        window.connect("destroy", self._on_settings_window_destroyed)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        window.add(outer)

        title = Gtk.Label(label="TokenBar Settings")
        title.set_xalign(0)
        title.get_style_context().add_class("title")
        outer.pack_start(title, False, False, 0)

        outer.pack_start(self._settings_section("General", [
            (settings_window_sections()["General"][0], self._init_config),
            (settings_window_sections()["General"][1], self._open_config),
            (settings_window_sections()["General"][2], self._dump_json),
            (settings_window_sections()["General"][3], self._show_diagnostics),
        ]), False, False, 0)

        outer.pack_start(self._settings_section("Authentication", [
            (settings_window_sections()["Authentication"][0], lambda *_: self._sign_in_provider("codex")),
            (settings_window_sections()["Authentication"][1], lambda *_: self._sign_in_provider("claude")),
            (settings_window_sections()["Authentication"][2], self._check_auth_status),
        ]), False, False, 0)

        outer.pack_start(self._settings_section("Notifications", [
            (settings_window_sections()["Notifications"][0], self._clear_alerts),
            (settings_window_sections()["Notifications"][1], lambda *_: self._snooze_alerts(60)),
            (settings_window_sections()["Notifications"][2], lambda *_: self._snooze_alerts(240)),
        ]), False, False, 0)

        outer.pack_start(self._settings_section("Updates", [
            (settings_window_sections()["Updates"][0], self._check_updates),
            (settings_window_sections()["Updates"][1], self._update_now),
        ]), False, False, 0)

        outer.pack_start(self._settings_section(f"Startup ({autostart_status()})", [
            (settings_window_sections()["Startup"][0], self._install_autostart),
            (settings_window_sections()["Startup"][1], self._remove_autostart),
        ]), False, False, 0)

        close = Gtk.Button(label="Close")
        close.connect("clicked", lambda *_: window.destroy())
        outer.pack_end(close, False, False, 0)

        self.settings_window = window
        window.show_all()
        window.present()

    def _on_settings_window_destroyed(self, *_args) -> None:
        self.settings_window = None

    def _settings_section(self, title: str, actions: list[tuple[str, Any]]) -> Gtk.Frame:
        frame = Gtk.Frame(label=title)
        grid = Gtk.Grid(column_spacing=8, row_spacing=8, margin_top=8, margin_bottom=8, margin_start=8, margin_end=8)
        frame.add(grid)
        for index, (label, callback) in enumerate(actions):
            button = Gtk.Button(label=label)
            button.set_hexpand(True)
            button.connect("clicked", callback)
            grid.attach(button, index % 2, index // 2, 1, 1)
        return frame

    def _init_config(self, *_args) -> None:
        path, created = ensure_config_file()
        status = "created" if created else "already exists"
        show_info(f"TokenBar config {status}: {path}")

    def _open_config(self, *_args) -> None:
        path, _created = ensure_config_file()
        launch_desktop_path(path)

    def _sign_in_provider(self, provider: str) -> None:
        result = launch_interactive_auth(provider)
        if result.ok:
            show_info(result.message)
            GLib.timeout_add_seconds(5, self._refresh_after_auth)
            return
        command = result.command or provider_login_command(provider) or provider
        show_command_dialog(command, result.message)

    def _refresh_after_auth(self) -> bool:
        self.refresh()
        return False

    def _check_auth_status(self, *_args) -> None:
        def worker() -> None:
            lines = [message for _provider, _ok, message in all_auth_status()]
            GLib.idle_add(show_info, "\n".join(lines))

        threading.Thread(target=worker, daemon=True).start()

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
