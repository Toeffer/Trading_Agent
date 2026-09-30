"""Hermes gets IBKR-sourced sizing, and proposals that disagree are not saved (2026-09-28).

Before: `ibkr-operator hermes-proposal` gave Hermes only net liquidation and
position symbols, yet asked it for entry price, ATR stop, FX and share counts
labelled "[IBKR]"; Gate H only checks that the fields exist. Now the baseline
carries `sizing_preview` (bridge data + guard.py's own calc_stop /
compute_final_max_shares), Hermes is not invoked without it, and a proposal
whose stop or quantity disagrees with it is not persisted.
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))

import guard  # noqa: E402
import hermes_advisory  # noqa: E402
import ibkr_operator  # noqa: E402
from test_ibkr_owner_thread import RULES_YAML  # noqa: E402
import fake_ib_gateway  # noqa: E402

RULES = yaml.safe_load(RULES_YAML)
BARS = [{"date": d, "open": o, "high": h, "low": lo, "close": c, "volume": 1000}
        for d, o, h, lo, c in fake_ib_gateway.BARS]
ACCOUNT = {"net_liquidation_eur": 1_000_000.0, "exchange_rate": 1 / 0.87}
QUOTE = {"ask": 200.6, "bid": 200.4, "last": 200.5, "close": 199.0}


def _preview(side="BUY", qty=10, account=ACCOUNT, quote=QUOTE, bars=BARS, fail=None):
    def _fetch_account():
        if fail:
            raise RuntimeError(fail)
        return account
    with patch("guard.fetch_account", _fetch_account), \
         patch("guard.fetch_quote", lambda s: quote), \
         patch("guard.fetch_bars", lambda s: bars), \
         patch("guard.load_rules", lambda: RULES):
        return ibkr_operator._sizing_preview("AAPL", side, qty)


class TestSizingPreview:
    def test_buy_preview_is_the_guards_own_computation(self):
        p = _preview()
        assert p["ok"], p
        stop = guard.calc_stop(200.6, BARS)
        sizing = guard.compute_final_max_shares(RULES, 1_000_000.0, 1 / 0.87, 200.6,
                                                stop["stop_distance"])
        assert p["stop"] == stop
        assert {k: p["sizing"][k] for k in sizing} == sizing
        assert p["sizing"]["requested_within_cap"] is True
        assert p["account"]["eur_usd"] == pytest.approx(1 / 0.87)
        assert "1 / ExchangeRate[USD]" in p["account"]["eur_usd_source"]

    def test_quantity_over_cap_is_flagged(self):
        p = _preview(qty=10**9)
        assert p["ok"] and p["sizing"]["requested_within_cap"] is False

    @pytest.mark.parametrize("kwargs, reason", [
        ({"fail": "bridge unreachable"}, "IBKR data unavailable"),
        ({"account": {**ACCOUNT, "exchange_rate": None}}, "EUR/USD unavailable"),
        ({"account": {**ACCOUNT, "exchange_rate": 0.5}}, "EUR/USD unavailable or implausible"),
        ({"quote": {**QUOTE, "ask": None}}, "No usable ask price"),
        ({"quote": {**QUOTE, "ask": float("nan")}}, "No usable ask price"),
        ({"bars": BARS[:1]}, "Stop/sizing computation failed"),
    ])
    def test_missing_data_is_an_error_not_a_guess(self, kwargs, reason):
        p = _preview(**kwargs)
        assert p["ok"] is False
        assert reason in p["error"]

    def test_sell_needs_no_stop_or_sizing(self):
        p = _preview(side="SELL", bars=[])
        assert p["ok"] and "stop" not in p and "Close-only" in p["sizing"]["note"]


class TestSizingCheck:
    def setup_method(self):
        self.preview = _preview()
        self.stop = self.preview["stop"]["stop_price"]
        self.cap = self.preview["sizing"]["final_max_shares"]

    def test_matching_proposal_passes(self):
        proposal = {"quantity": 5, "position_sizing": {"stop_price": self.stop}}
        assert ibkr_operator._check_hermes_sizing(proposal, self.preview)["ok"]

    def test_smaller_quantity_is_allowed(self):
        proposal = {"quantity": 1, "position_sizing": {"stop_price": self.stop}}
        assert ibkr_operator._check_hermes_sizing(proposal, self.preview)["ok"]

    def test_tighter_stop_is_allowed(self):
        entry = self.preview["stop"]["entry_price"]
        tighter = round((self.stop + entry) / 2, 2)
        proposal = {"quantity": 5, "position_sizing": {"stop_price": tighter}}
        assert ibkr_operator._check_hermes_sizing(proposal, self.preview)["ok"]

    @pytest.mark.parametrize("proposal, needle", [
        (lambda s, c: {"quantity": c + 1, "position_sizing": {"stop_price": s}}, "exceeds guard cap"),
        (lambda s, c: {"quantity": 5, "position_sizing": {"stop_price": s - 1}}, "looser than the guard stop"),
        (lambda s, c: {"quantity": 5, "position_sizing": {}}, "looser than the guard stop"),
        (lambda s, c: {"quantity": 5, "position_sizing": {"stop_price": 10_000.0}}, "not below the entry"),
        (lambda s, c: {"quantity": 0, "position_sizing": {"stop_price": s}}, "not a positive integer"),
        (lambda s, c: {"error": "sizing_preview unavailable"}, "not a positive integer"),
    ])
    def test_disagreeing_proposal_fails(self, proposal, needle):
        check = ibkr_operator._check_hermes_sizing(proposal(self.stop, self.cap), self.preview)
        assert not check["ok"]
        assert any(needle in m for m in check["mismatches"]), check


def _run_proposal(preview, hermes_json):
    completed = SimpleNamespace(stdout=json.dumps(hermes_json), stderr="", returncode=0)
    with patch("ibkr_operator._sizing_preview", return_value=preview), \
         patch("ibkr_operator.run_checklist", return_value={}), \
         patch("ibkr_operator.run_daily_report", return_value={}), \
         patch("ibkr_operator.run_doctor", return_value={}), \
         patch("subprocess.run", return_value=completed) as hermes, \
         patch("guard.save_proposal_file", return_value=Path("/tmp/p.json")) as save:
        result = ibkr_operator._run_hermes_proposal("AAPL", "BUY", 5)
    return result, hermes, save


class TestHermesProposalFlow:
    def test_no_ibkr_data_means_hermes_is_not_invoked(self):
        result, hermes, save = _run_proposal({"ok": False, "error": "IBKR data unavailable: x"}, {})
        assert result["ok"] is False and "Hermes not invoked" in result["error"]
        hermes.assert_not_called()
        save.assert_not_called()

    def test_preview_is_in_the_prompt_and_agreeing_proposal_is_saved(self):
        preview = _preview()
        proposal = {"quantity": 5, "position_sizing": {"stop_price": preview["stop"]["stop_price"]}}
        result, hermes, save = _run_proposal(preview, proposal)
        prompt = hermes.call_args.args[0][3]
        assert '"sizing_preview"' in prompt and str(preview["stop"]["stop_price"]) in prompt
        save.assert_called_once()
        assert result["proposal_path"] and result["sizing_check"]["ok"]

    def test_disagreeing_proposal_is_not_saved(self):
        preview = _preview()
        proposal = {"quantity": 5, "position_sizing": {"stop_price": 1.0}}
        result, hermes, save = _run_proposal(preview, proposal)
        save.assert_not_called()
        assert result["proposal_path"] is None
        assert "not persisted" in result["proposal_persist_error"]


class TestPreflightRequest:
    def setup_method(self):
        self.preview = _preview()
        self.stop = self.preview["stop"]["stop_price"]

    def test_guard_stop_leaves_stop_to_the_guard(self):
        proposal = {"quantity": 5, "position_sizing": {"stop_price": self.stop}}
        req = ibkr_operator._preflight_request(proposal, self.preview, "/p.json")
        assert req == {"symbol": "AAPL", "action": "BUY", "totalQuantity": 5,
                       "proposal_path": "/p.json"}

    def test_tighter_stop_is_passed_as_stop_price(self):
        tighter = round(self.stop + 1.0, 2)
        proposal = {"quantity": 5, "position_sizing": {"stop_price": tighter}}
        req = ibkr_operator._preflight_request(proposal, self.preview, "/p.json")
        assert req["stopPrice"] == tighter

    def test_request_fields_are_all_accepted_by_the_guard(self):
        proposal = {"quantity": 5, "position_sizing": {"stop_price": self.stop + 1.0}}
        req = ibkr_operator._preflight_request(proposal, self.preview, "/p.json")
        assert set(req) - {"proposal_path"} <= set(guard.ALLOWED_REQUEST_FIELDS)

    def test_flow_returns_the_request_for_a_saved_proposal(self):
        tighter = round(self.stop + 1.0, 2)
        proposal = {"quantity": 5, "position_sizing": {"stop_price": tighter}}
        result, _, save = _run_proposal(self.preview, proposal)
        save.assert_called_once()
        assert result["preflight_request"]["stopPrice"] == tighter
        assert result["preflight_request"]["proposal_path"] == result["proposal_path"]


class TestHermesInstructions:
    def test_instructions_require_the_preview_and_forbid_invented_numbers(self):
        text = hermes_advisory.ADVISORY_INSTRUCTION
        assert "sizing_preview" in text
        assert "Never fetch, estimate or invent a price, ATR, stop or FX rate" in text
        assert "1 / IBKR ExchangeRate[USD]" in text
        assert "you may choose a tighter stop, never a" in text
