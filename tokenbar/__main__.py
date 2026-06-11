from __future__ import annotations

import argparse
import json

from .autostart import install_autostart, remove_autostart
from .cache import snapshot_cache_as_jsonable
from .config import config_to_json, ensure_config_file, load_config
from .diagnostics import collect_diagnostics, format_diagnostics_text
from .installer import dependency_report, install_user, uninstall_user
from .notifications import clear_alert_state, snooze_alerts
from .providers import snapshots_as_jsonable
from .tray import check_tray_support, choose_tray_backend, run
from .updater import check_for_update, update_now


def main() -> int:
    parser = argparse.ArgumentParser(description="TokenBar Linux MVP")
    parser.add_argument("--dump-json", action="store_true", help="Print provider snapshot JSON and exit")
    parser.add_argument("--config-dump", action="store_true", help="Print effective TokenBar config JSON and exit")
    parser.add_argument("--cache-dump", action="store_true", help="Print cached provider snapshot JSON and exit")
    parser.add_argument("--init-config", action="store_true", help="Create a default config file if missing and exit")
    parser.add_argument("--doctor", action="store_true", help="Print TokenBar diagnostics and exit")
    parser.add_argument("--doctor-json", action="store_true", help="Print TokenBar diagnostics JSON and exit")
    parser.add_argument("--clear-alerts", action="store_true", help="Clear notification anti-spam/snooze state and exit")
    parser.add_argument("--snooze-alerts-minutes", type=int, help="Snooze TokenBar notifications for N minutes and exit")
    parser.add_argument("--install-autostart", action="store_true", help="Install GNOME autostart entry and exit")
    parser.add_argument("--remove-autostart", action="store_true", help="Remove GNOME autostart entry and exit")
    parser.add_argument("--install-user", action="store_true", help="Install TokenBar into the current user's local app paths")
    parser.add_argument("--uninstall-user", action="store_true", help="Remove TokenBar from the current user's local app paths")
    parser.add_argument("--purge-user-data", action="store_true", help="With --uninstall-user, also remove TokenBar config/cache")
    parser.add_argument("--install-check", action="store_true", help="Check runtime dependencies needed for user install")
    parser.add_argument("--update-check", action="store_true", help="Check GitHub for a newer TokenBar version")
    parser.add_argument("--update-now", action="store_true", help="Update the user-level install from GitHub")
    parser.add_argument("--check", action="store_true", help="Validate tray prerequisites and exit")
    args = parser.parse_args()
    if args.init_config:
        path, created = ensure_config_file()
        status = "created" if created else "already exists"
        print(f"TokenBar config {status}: {path}")
        return 0
    config, config_error = load_config()
    if args.clear_alerts:
        path = clear_alert_state()
        print(f"TokenBar alert state cleared: {path}")
        return 0
    if args.snooze_alerts_minutes is not None:
        until = snooze_alerts(args.snooze_alerts_minutes)
        print(f"TokenBar alerts snoozed until: {until.isoformat(timespec='seconds')}")
        return 0
    if args.install_autostart:
        path = install_autostart()
        print(f"TokenBar autostart installed: {path}")
        return 0
    if args.remove_autostart:
        path, removed = remove_autostart()
        status = "removed" if removed else "already absent"
        print(f"TokenBar autostart {status}: {path}")
        return 0
    if args.install_check:
        print(json.dumps(dependency_report(), indent=2))
        return 0
    if args.install_user:
        result = install_user()
        print(json.dumps(result, indent=2))
        return 0
    if args.uninstall_user:
        result = uninstall_user(purge_user_data=args.purge_user_data)
        print(json.dumps(result, indent=2))
        return 0
    if args.update_check:
        print(json.dumps(check_for_update().as_dict(), indent=2))
        return 0
    if args.update_now:
        print(json.dumps(update_now(), indent=2))
        return 0
    if args.doctor or args.doctor_json:
        backend, _module, message = choose_tray_backend()
        diagnostics = collect_diagnostics(
            config,
            config_error=config_error,
            tray_backend=backend,
            tray_message=message,
        )
        if args.doctor_json:
            print(json.dumps(diagnostics, indent=2))
        else:
            print(format_diagnostics_text(diagnostics))
        return 0
    if args.config_dump:
        print(config_to_json(config, config_error))
        return 0
    if args.cache_dump:
        print(json.dumps(snapshot_cache_as_jsonable(), indent=2))
        return 0
    if args.dump_json:
        print(json.dumps(snapshots_as_jsonable(config), indent=2))
        return 0
    if args.check:
        ok, message = check_tray_support()
        print(message)
        return 0 if ok else 2
    return run(config)


if __name__ == "__main__":
    raise SystemExit(main())
