from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from tokenbar.config import TokenBarConfig
from tokenbar.notifications import clear_alert_state, compute_alerts, process_alerts, snooze_alerts
from tokenbar.providers import Snapshot


class NotificationTests(unittest.TestCase):
    def test_compute_alerts_reports_low_quota(self) -> None:
        snapshot = Snapshot("claude", "oauth", True, "8% left", utilization_pct=92.0)
        alerts = compute_alerts([snapshot], TokenBarConfig(low_quota_threshold=10.0))
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].key, "claude:low-quota")
        self.assertIn("8% left", alerts[0].message)

    def test_compute_alerts_respects_disabled_low_quota(self) -> None:
        snapshot = Snapshot("claude", "oauth", True, "8% left", utilization_pct=92.0)
        config = TokenBarConfig(notifications={"enabled": True, "low_quota": False})
        alerts = compute_alerts([snapshot], config)
        self.assertEqual(alerts, [])

    def test_compute_alerts_reports_provider_error_with_guidance(self) -> None:
        snapshot = Snapshot(
            "codex",
            "oauth",
            False,
            "auth expired",
            status_label="auth expired",
            guidance="Run: codex login",
        )
        alerts = compute_alerts([snapshot], TokenBarConfig())
        self.assertEqual(alerts[0].key, "codex:error:auth expired")
        self.assertIn("Run: codex login", alerts[0].message)

    def test_compute_alerts_reports_stale_data(self) -> None:
        alerts = compute_alerts([], TokenBarConfig(), stale=True)
        self.assertEqual(alerts[0].key, "stale")

    def test_process_alerts_deduplicates_active_alerts(self) -> None:
        snapshot = Snapshot("claude", "oauth", True, "8% left", utilization_pct=92.0)
        sent: list[str] = []
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "alert-state.json"
            first = process_alerts(
                [snapshot],
                TokenBarConfig(),
                state_path=path,
                notifier=lambda alert: sent.append(alert.key),
            )
            second = process_alerts(
                [snapshot],
                TokenBarConfig(),
                state_path=path,
                notifier=lambda alert: sent.append(alert.key),
            )
        self.assertEqual([alert.key for alert in first], ["claude:low-quota"])
        self.assertEqual(second, [])
        self.assertEqual(sent, ["claude:low-quota"])

    def test_process_alerts_realerts_after_recovery(self) -> None:
        low = Snapshot("claude", "oauth", True, "8% left", utilization_pct=92.0)
        recovered = Snapshot("claude", "oauth", True, "80% left", utilization_pct=20.0)
        sent: list[str] = []
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "alert-state.json"
            process_alerts([low], TokenBarConfig(), state_path=path, notifier=lambda alert: sent.append(alert.key))
            process_alerts([recovered], TokenBarConfig(), state_path=path, notifier=lambda alert: sent.append(alert.key))
            process_alerts([low], TokenBarConfig(), state_path=path, notifier=lambda alert: sent.append(alert.key))
        self.assertEqual(sent, ["claude:low-quota", "claude:low-quota"])

    def test_process_alerts_respects_snooze_and_alerts_after_expiry(self) -> None:
        snapshot = Snapshot("claude", "oauth", True, "8% left", utilization_pct=92.0)
        sent: list[str] = []
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "alert-state.json"
            now = datetime(2026, 6, 11, 12, 0)
            snooze_alerts(60, path=path, now=now)
            snoozed = process_alerts(
                [snapshot],
                TokenBarConfig(),
                state_path=path,
                notifier=lambda alert: sent.append(alert.key),
                now=now + timedelta(minutes=30),
            )
            after_expiry = process_alerts(
                [snapshot],
                TokenBarConfig(),
                state_path=path,
                notifier=lambda alert: sent.append(alert.key),
                now=now + timedelta(minutes=61),
            )
        self.assertEqual(snoozed, [])
        self.assertEqual([alert.key for alert in after_expiry], ["claude:low-quota"])
        self.assertEqual(sent, ["claude:low-quota"])

    def test_clear_alert_state_removes_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "alert-state.json"
            path.write_text("{}")
            result = clear_alert_state(path)
            exists = path.exists()
        self.assertEqual(result.name, "alert-state.json")
        self.assertFalse(exists)


if __name__ == "__main__":
    unittest.main()
