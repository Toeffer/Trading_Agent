"""Tests for Phase 19K — Heartbeat staleness threshold + failure alerting (2026-08-17).

Discovered: the deployed systemd timer (systemd/ibkr-heartbeat.timer, live
since 2026-06-13, never previously tracked in git) runs `ibkr-operator
heartbeat` every 15 minutes -- but every readiness/execution-gate check that
reads heartbeat freshness hardcoded a 24-hour staleness threshold
independently, and a failing heartbeat never surfaced anywhere (no
/monitor/alerts entry, nothing doctor/checklist would flag) until a full
24h of silence. This file covers the fix: a single named
HEARTBEAT_STALE_THRESHOLD_SECONDS constant (45 min, proportionate to the
real 15-min cadence), and monitor_alert wiring on endpoint failure.
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

BRIDGE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BRIDGE_DIR))

from ibkr_operator import (  # noqa: E402
    HEARTBEAT_STALE_THRESHOLD_SECONDS,
    _heartbeat_age_seconds,
    _run_heartbeat,
    _HEARTBEAT_ENDPOINTS,
)


class TestStaleThresholdConstant:
    def test_value_is_45_minutes(self):
        """Pinned regression -- proportionate to the real 15-min timer
        cadence, not the old 24h default. If this needs to change again,
        change it deliberately, not by silent drift."""
        assert HEARTBEAT_STALE_THRESHOLD_SECONDS == 2700

    def test_tolerates_a_few_missed_cycles_without_false_alarm(self):
        """2700s should comfortably cover several missed 15-min cycles
        (900s each) without being anywhere near the old 24h ceiling."""
        assert HEARTBEAT_STALE_THRESHOLD_SECONDS >= 3 * 900
        assert HEARTBEAT_STALE_THRESHOLD_SECONDS < 86400


class TestHeartbeatAgeAgainstThreshold:
    """Exercises the real _heartbeat_age_seconds() function (used by both
    gating call sites in run_kpi()) against controlled artifact mtimes,
    rather than mocking run_kpi()'s large network surface -- the actual
    comparison logic at both call sites is a single `age < THRESHOLD`
    expression; what needs real coverage is that age computation itself."""

    def _write_artifact(self, heartbeat_dir: Path, age_seconds: float):
        heartbeat_dir.mkdir(parents=True, exist_ok=True)
        p = heartbeat_dir / "heartbeat-20260817T060000Z.json"
        p.write_text("{}")
        import os, time
        stale_mtime = time.time() - age_seconds
        os.utime(p, (stale_mtime, stale_mtime))
        return p

    def test_fresh_artifact_is_under_threshold(self, tmp_path):
        self._write_artifact(tmp_path, age_seconds=300)  # 5 min old
        age = _heartbeat_age_seconds(tmp_path)
        assert age < HEARTBEAT_STALE_THRESHOLD_SECONDS

    def test_artifact_just_past_threshold_is_stale(self, tmp_path):
        self._write_artifact(tmp_path, age_seconds=HEARTBEAT_STALE_THRESHOLD_SECONDS + 60)
        age = _heartbeat_age_seconds(tmp_path)
        assert age > HEARTBEAT_STALE_THRESHOLD_SECONDS

    def test_artifact_stale_by_old_threshold_but_not_new_one_now_flags(self, tmp_path):
        """The whole point of the fix: something that would have silently
        passed under the old 24h ceiling (e.g. 2h old, three missed 15-min
        cycles) must now be caught."""
        two_hours = 7200
        self._write_artifact(tmp_path, age_seconds=two_hours)
        age = _heartbeat_age_seconds(tmp_path)
        assert age < 86400  # would have passed the old threshold
        assert age > HEARTBEAT_STALE_THRESHOLD_SECONDS  # correctly flagged now

    def test_no_artifact_returns_none(self, tmp_path):
        assert _heartbeat_age_seconds(tmp_path / "does-not-exist") is None


# ---------------------------------------------------------------------------
# Heartbeat failure -> monitor_alert wiring
# ---------------------------------------------------------------------------

def _mock_urlopen_response(status: int, payload: dict):
    cm = MagicMock()
    cm.__enter__.return_value.status = status
    cm.__enter__.return_value.read.return_value = json.dumps(payload).encode()
    cm.__exit__.return_value = False
    return cm


def _all_endpoints_ok_side_effect(req, timeout=7):
    return _mock_urlopen_response(200, {"connected": True, "mode": "paper"})


def _one_endpoint_fails_side_effect(fail_ep: str):
    def _side_effect(req, timeout=7):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if url.endswith(fail_ep):
            raise ConnectionRefusedError("connection refused")
        return _mock_urlopen_response(200, {"connected": True, "mode": "paper"})
    return _side_effect


class TestHeartbeatFailureAlerting:
    def test_all_endpoints_ok_does_not_alert(self, tmp_path):
        with patch("ibkr_operator.urllib.request.urlopen", side_effect=_all_endpoints_ok_side_effect), \
             patch("ibkr_operator.HEARTBEAT_DIR", tmp_path), \
             patch("monitor.append_heartbeat_alert") as mock_alert:
            result = _run_heartbeat()

        assert result["all_endpoints_ok"] is True
        mock_alert.assert_not_called()

    def test_endpoint_failure_triggers_monitor_alert(self, tmp_path):
        with patch("ibkr_operator.urllib.request.urlopen",
                    side_effect=_one_endpoint_fails_side_effect("/health")), \
             patch("ibkr_operator.HEARTBEAT_DIR", tmp_path), \
             patch("monitor.append_heartbeat_alert") as mock_alert:
            result = _run_heartbeat()

        assert result["all_endpoints_ok"] is False
        mock_alert.assert_called_once()
        failures, total = mock_alert.call_args[0]
        assert total == len(_HEARTBEAT_ENDPOINTS)
        assert any("/health" in f for f in failures)

    def test_alert_logging_failure_does_not_crash_heartbeat(self, tmp_path):
        """Non-critical by design -- a broken alert path must never take
        the heartbeat check itself down with it."""
        with patch("ibkr_operator.urllib.request.urlopen",
                    side_effect=_one_endpoint_fails_side_effect("/health")), \
             patch("ibkr_operator.HEARTBEAT_DIR", tmp_path), \
             patch("monitor.append_heartbeat_alert", side_effect=RuntimeError("disk full")):
            result = _run_heartbeat()

        assert result["all_endpoints_ok"] is False
        assert result["ok"] is True  # artifact write still succeeded

    def test_ibkr_disconnected_alone_does_not_alert(self, tmp_path):
        """A disconnected Gateway overnight/pre-market is routine, not an
        infrastructure failure -- alerting on it every 15 minutes would
        just be noise. Only the bridge's own endpoints failing should."""
        def _side_effect(req, timeout=7):
            return _mock_urlopen_response(200, {"connected": False, "mode": "paper"})

        with patch("ibkr_operator.urllib.request.urlopen", side_effect=_side_effect), \
             patch("ibkr_operator.HEARTBEAT_DIR", tmp_path), \
             patch("monitor.append_heartbeat_alert") as mock_alert:
            result = _run_heartbeat()

        assert result["connected"] is False
        assert result["all_endpoints_ok"] is True  # endpoints answered fine
        mock_alert.assert_not_called()


# ---------------------------------------------------------------------------
# Deployed systemd units, now tracked in the repo
# ---------------------------------------------------------------------------

class TestSystemdUnitsTrackedInRepo:
    """Repo-side sanity check that the checked-in copies match what's
    actually deployed (systemd/ibkr-heartbeat.{service,timer}) -- the full
    live-host acceptance battery lives in test_p7_heartbeat.py and is
    intentionally excluded from portable CI."""

    SERVICE = BRIDGE_DIR / "systemd" / "ibkr-heartbeat.service"
    TIMER = BRIDGE_DIR / "systemd" / "ibkr-heartbeat.timer"

    def test_service_file_exists(self):
        assert self.SERVICE.exists()

    def test_timer_file_exists(self):
        assert self.TIMER.exists()

    def test_timer_interval_is_15_minutes(self):
        text = self.TIMER.read_text()
        assert "OnCalendar=*:0/15" in text

    def test_timer_has_jitter_and_persistence(self):
        text = self.TIMER.read_text()
        assert "RandomizedDelaySec=30" in text
        assert "Persistent=true" in text

    def test_service_uses_json_quiet_flags(self):
        text = self.SERVICE.read_text()
        assert "--json" in text and "--quiet" in text

    def test_service_is_read_only_hardened(self):
        text = self.SERVICE.read_text()
        assert "ProtectSystem=strict" in text
        assert "NoNewPrivileges=true" in text
        assert "Restart=always" not in text
        assert "ExecStartPre" not in text
        assert "ExecStartPost" not in text

    @pytest.mark.parametrize("ep", ["/connect", "/order/approve", "/order/submit", "/order/preflight"])
    def test_service_free_of_forbidden_endpoints(self, ep):
        text = self.SERVICE.read_text()
        assert ep not in text
