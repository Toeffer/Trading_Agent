"""Tests for Phase 19M — ibkr-operator hermes-proposal persists a real,
Gate-H-ready proposal file (2026-08-18).

Background (live incident / operator question): Chris asked how to turn a
Hermes advisory proposal into a proposal that actually passes Gate H
(guard.gate_proposal_discipline). Tracing the code found two separate,
independently-grown implementations of "ask Hermes for a proposal":

  - hermes_advisory.py (Phase 5B.1/P3) -- a standalone script whose prompt
    template already includes the `position_sizing` object Gate H requires
    for BUY, and which already calls guard.save_proposal_file() to persist
    the bare, unwrapped proposal dict Gate H reads.
  - ibkr_operator.py's _run_hermes_proposal() (Phase 5B.1 "(original)") --
    the function actually wired to the `ibkr-operator hermes-proposal`
    command Chris/OpenClaw use day to day. It had its own private copy of
    the prompt template that never asked for `position_sizing`, and it
    never persisted anything to disk at all. A BUY proposal generated this
    way could never pass Gate H, no matter what Hermes said.

Fix: _run_hermes_proposal() now builds its prompt via
hermes_advisory.build_prompt() (one shared template, no drift) and
persists a successfully-parsed proposal via guard.save_proposal_file()
(one shared persistence path), exactly mirroring hermes_advisory.py's
already-correct P3 behavior instead of duplicating it.

These tests prove: (1) the duplicate ad hoc template is gone and the
shared one is actually used, (2) a valid Hermes response gets persisted
to disk, (3) a malformed response is never persisted (no phantom
proposals), (4) a persistence failure is reported but does not crash the
command, and (5) end-to-end: the file this function writes actually
passes guard.gate_proposal_discipline() (Gate H) for a BUY proposal --
the concrete thing that was impossible before this fix.
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

BRIDGE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BRIDGE_DIR))

import guard  # noqa: E402
import hermes_advisory  # noqa: E402
import ibkr_operator  # noqa: E402


def _fake_completed_process(stdout: str, returncode: int = 0, stderr: str = ""):
    proc = MagicMock()
    proc.stdout = stdout
    proc.stderr = stderr
    proc.returncode = returncode
    return proc


def _valid_buy_proposal() -> dict:
    """A Hermes response matching the shared template exactly, including
    the position_sizing object Gate H hard-requires for BUY."""
    return {
        "symbol": "AAPL",
        "side": "BUY",
        "quantity": 1,
        "entry_reference": "Market entry near $200.00 [IBKR]",
        "stop_loss_invalidation": "Stop at $190.00 (2x ATR below entry) [IBKR]",
        "max_loss_eur": 10.0,
        "max_loss_pct": 0.001,
        "position_notional_eur": 200.0,
        "position_notional_pct": 0.02,
        "portfolio_exposure_after_pct": 5.0,
        "daily_drawdown_status": "No drawdown [bridge/preflight]",
        "weekly_drawdown_status": "No drawdown [bridge/preflight]",
        "reason_to_trade": "Momentum continuation [web/news]",
        "reason_not_to_trade": "Macro uncertainty [assumption]",
        "preflight_command": "curl -X POST http://127.0.0.1:8790/order/preflight ...",
        "facts": ["[IBKR] Net Liq $1,000,000"],
        "assumptions": ["[assumption] Spread is tight at open"],
        "estimates": [],
        "unknowns": [],
        "why_not_wait": "Setup is time-sensitive [assumption]",
        "awaiting_chris_approval": True,
        "advisory_only": True,
        "position_sizing": {
            "method": "ATR risk sizing",
            "inputs": {},
            "stop_candidates": {},
            "stop_price": 190.0,
            "binding_stop": "2x ATR",
            "stop_distance": 10.0,
            "notional_cap_shares": 1,
            "risk_cap_shares": 1,
            "final_shares": 1,
            "position_notional_usd": 200.0,
            "max_loss_usd": 10.0,
            "max_loss_eur": 10.0,
            "binding_factor": "risk",
            "position_pct_nl": 0.02,
            "rationale_why_this_size": "risk cap is binding",
            "rationale_why_not_smaller": "would waste the notional cap",
            "rationale_why_not_larger": "would breach risk cap",
            "rationale_limiting_factor": "risk_cap_shares",
        },
    }


@pytest.fixture
def isolated_proposals_dir(tmp_path):
    """Redirect guard.PROPOSALS_PATH to an isolated tmp dir for the
    duration of a test, restoring it afterward."""
    original = guard.PROPOSALS_PATH
    guard.PROPOSALS_PATH = tmp_path / "proposals"
    try:
        yield guard.PROPOSALS_PATH
    finally:
        guard.PROPOSALS_PATH = original


def _run_with_mocked_baseline_and_hermes(stdout: str):
    with patch.object(ibkr_operator, "run_checklist", return_value={}), \
         patch.object(ibkr_operator, "run_daily_report", return_value={}), \
         patch.object(ibkr_operator, "run_doctor", return_value={}), \
         patch("subprocess.run", return_value=_fake_completed_process(stdout)):
        return ibkr_operator._run_hermes_proposal("AAPL", "BUY", 1)


class TestSharedTemplateNotPrivateCopy:
    """The original bug was a private, drifted copy of the prompt
    template. Guard against it silently coming back."""

    def _function_source(self) -> str:
        src = Path(BRIDGE_DIR / "ibkr_operator.py").read_text()
        idx = src.index("def _run_hermes_proposal(")
        end = src.index("\ndef ", idx + 10)
        return src[idx:end]

    def test_imports_shared_build_prompt(self):
        body = self._function_source()
        assert "from hermes_advisory import build_prompt" in body

    def test_no_private_ad_hoc_output_format_marker_left_behind(self):
        body = self._function_source()
        assert "OUTPUT FORMAT: Valid JSON only" not in body

    def test_build_prompt_is_actually_invoked(self, isolated_proposals_dir):
        with patch.object(hermes_advisory, "build_prompt",
                           wraps=hermes_advisory.build_prompt) as bp:
            _run_with_mocked_baseline_and_hermes(
                json.dumps(_valid_buy_proposal())
            )
        assert bp.called
        args, _ = bp.call_args
        baseline_arg, user_request_arg = args
        assert isinstance(baseline_arg, dict)
        assert "AAPL" in user_request_arg
        assert "BUY" in user_request_arg


class TestPersistenceOnValidResponse:
    def test_valid_proposal_is_persisted(self, isolated_proposals_dir):
        result = _run_with_mocked_baseline_and_hermes(
            json.dumps(_valid_buy_proposal())
        )
        assert result["ok"] is True
        assert result["proposal_path"] is not None
        assert result["proposal_persist_error"] is None

        saved = Path(result["proposal_path"])
        assert saved.exists()
        assert saved.parent == isolated_proposals_dir

        on_disk = json.loads(saved.read_text())
        assert on_disk["symbol"] == "AAPL"
        assert on_disk["side"] == "BUY"
        assert isinstance(on_disk.get("position_sizing"), dict)

    def test_persisted_file_passes_gate_h(self, isolated_proposals_dir):
        """The concrete proof this fix closes the loop: the file this
        function writes actually passes Gate H for a BUY proposal."""
        result = _run_with_mocked_baseline_and_hermes(
            json.dumps(_valid_buy_proposal())
        )
        passed, reason, details = guard.gate_proposal_discipline(
            result["proposal_path"]
        )
        assert passed is True, f"Gate H failed unexpectedly: {reason} {details}"


class TestNoPhantomPersistenceOnMalformedResponse:
    def test_unparsable_response_is_not_persisted(self, isolated_proposals_dir):
        result = _run_with_mocked_baseline_and_hermes(
            "Hermes returned prose, not JSON, sorry."
        )
        assert result["ok"] is False
        assert result["proposal"] is None
        assert result["proposal_path"] is None
        assert result["proposal_persist_error"] is None
        assert not list(isolated_proposals_dir.glob("*")) \
            if isolated_proposals_dir.exists() else True


class TestPersistFailureDoesNotCrashCommand:
    def test_save_proposal_file_error_is_reported_not_raised(self, isolated_proposals_dir):
        with patch.object(guard, "save_proposal_file",
                           side_effect=OSError("disk full")):
            result = _run_with_mocked_baseline_and_hermes(
                json.dumps(_valid_buy_proposal())
            )
        # The Hermes answer is still surfaced even though persistence failed.
        assert result["ok"] is True
        assert result["proposal"] is not None
        assert result["proposal_path"] is None
        assert "disk full" in result["proposal_persist_error"]
