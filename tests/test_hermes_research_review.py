"""Hermes research mode and end-of-window review (2026-09-30).

Research (hermes_research): Hermes proposes bounded variants from strategy
documents and train-period backtests, picks at most one, drafts a proposal and
pre-registration sections. No paper-run outcome may reach it: no outcome file
is read, and market data stop before every sealed, unreviewed run.

Review (hermes_review): the one place outcomes reach Hermes, per Chris's
scoped amendment of Decision 11.6 — only for a sealed (hash intact) and closed
(planned end passed) run, once per run, with P&L-type data removed, and a
revision must answer a pre-registered decision rule. The trade path
(hermes_advisory.py, guard, bridge) imports none of it.
"""

import ast
import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))

import hermes_research  # noqa: E402
import hermes_review  # noqa: E402
import paper_runs  # noqa: E402
from sim import backtest as bt  # noqa: E402
from test_ibkr_owner_thread import RULES_YAML  # noqa: E402

SYMS = ["AAPL", "AMD", "CAT", "JPM", "KO", "XOM"]
V7 = (REPO / "docs" / "paper-runs" / "pr-2026-08-v7-preregistration.md").read_text()


@pytest.fixture(scope="module")
def rules():
    r = yaml.safe_load(RULES_YAML)
    r["symbol_allowlist"]["allow"] = SYMS
    r["symbol_sectors"] = {s: s for s in SYMS}
    return r


@pytest.fixture(scope="module")
def bars():
    return bt.synthetic_bars(SYMS + ["SPY"], days=650, start="2022-01-03")


def write_run(dir_, run_id, start, end, *, seal=True, text=V7):
    text = (text.replace("| Start date | `2026-08-17` |", f"| Start date | `{start}` |")
                .replace("| Planned end date | `2026-11-13` |", f"| Planned end date | `{end}` |"))
    doc = Path(dir_) / f"{run_id}-preregistration.md"
    doc.write_text(text)
    if seal:
        (Path(dir_) / f"{run_id}-seal.json").write_text(json.dumps(
            {"sha256": hashlib.sha256(doc.read_bytes()).hexdigest(), "sealed_utc": "x"}))
    return doc


class FakeHermes:
    """Canned replies in order; records every prompt."""

    def __init__(self, *replies):
        self.replies, self.prompts = list(replies), []

    def __call__(self, prompt, model=None, timeout=None):
        self.prompts.append(prompt)
        reply = self.replies.pop(0)
        if isinstance(reply, dict) and "ok" in reply:
            return reply
        return {"ok": True, "raw_response": json.dumps(reply), "evidence": {"hermes_model": model}}


PROPOSE = {"hypothesis": "tighter stops cut losers earlier", "advisory_only": True,
           "variants": [{"name": "tight_stop", "atr_multiplier": 1.2},
                        {"name": "loose_stop", "atr_multiplier": 3.0},       # invalid: looser than guard
                        {"name": "slow_trend", "trend_sma_days": 100, "max_hold_days": 40}]}


def choose(name):
    return {"choice": name, "reasoning": "r", "advisory_only": True,
            "strategy_proposal": {"version_from": "1.1", "version_to": "1.2", "changes": []},
            "preregistration_draft": {"expected_observations": [{"id": "3.1", "quantity": "q",
                                                                 "range": "1-2", "basis": "b"}],
                                      "decision_rules": [{"observation": "o", "response": "r"}]}}


def research(tmp_path, bars, rules, *replies, runs=None, reviews=None):
    fake = FakeHermes(*replies)
    runs = runs or tmp_path / "runs"
    Path(runs).mkdir(exist_ok=True)
    record = hermes_research.run_research(
        bars=bars, rules=rules, invoke=fake, research_dir=tmp_path / "research",
        paper_runs_dir=runs, reviews_dir=reviews or tmp_path / "reviews")
    return record, fake


# ── research mode ───────────────────────────────────────────────────────────

class TestResearch:
    def test_full_round_produces_a_draft_and_one_holdout_look(self, tmp_path, bars, rules):
        record, fake = research(tmp_path, bars, rules, PROPOSE, choose("tight_stop"))
        assert record["status"] == "DRAFT_READY", record.get("error")
        assert [r["reason"] for r in record["rejected_variants"]] == \
            ["atr_multiplier=3.0 outside [0.5, 2.0]"]
        assert set(record["train_results"]) == {"baseline", "tight_stop", "slow_trend"}
        assert record["holdout"]["variant"] == "tight_stop"
        out = Path(record["path"])
        assert (out / "holdout.json").exists() and (out / "draft.md").exists()
        assert "RESEARCH DRAFT" in (out / "draft.md").read_text()
        with pytest.raises(bt.BacktestError, match="one look"):
            bt.evaluate_holdout(out / "study.json", bars, "baseline", rules)

    def test_hermes_never_sees_the_holdout(self, tmp_path, bars, rules):
        record, fake = research(tmp_path, bars, rules, PROPOSE, choose("tight_stop"))
        hold = record["periods"]["holdout"]
        holdout_dates = {b["date"] for b in bars["SPY"] if b["date"] >= hold["start"]}
        for prompt in fake.prompts:
            assert not any(d in prompt for d in holdout_dates)
        assert "TRAIN RESULTS" in fake.prompts[1]

    def test_data_stop_before_an_open_sealed_run(self, tmp_path, bars, rules):
        runs = tmp_path / "runs"
        runs.mkdir()
        write_run(runs, "pr-x", "2024-01-02", "2024-04-01")
        record, fake = research(tmp_path, bars, rules, PROPOSE, choose(None), runs=runs)
        assert record["outcome_cutoff"] == {"cutoff": "2024-01-02", "runs": ["pr-x"]}
        assert record["data_range"]["last"] < "2024-01-02"
        assert "2024-01-02" not in "".join(fake.prompts)
        assert record["status"] == "NO_CHANGE_PROPOSED" and "holdout" not in record

    def test_a_reviewed_or_superseded_run_no_longer_cuts_data(self, tmp_path):
        runs = tmp_path / "runs"
        runs.mkdir()
        write_run(runs, "pr-a", "2024-01-02", "2024-04-01")
        write_run(runs, "pr-b", "2024-02-01", "2024-05-01")
        write_run(runs, "pr-c", "2023-06-01", "2023-09-01", seal=False)   # never started
        reviews = tmp_path / "reviews"
        assert paper_runs.outcome_cutoff(runs, reviews)["cutoff"] == "2024-01-02"
        hermes_review.record_superseded("pr-a", "pr-b", paper_runs_dir=runs, reviews_dir=reviews)
        assert paper_runs.outcome_cutoff(runs, reviews)["cutoff"] == "2024-02-01"

    @pytest.mark.parametrize("reply, status", [
        ({"ok": False, "error": "timeout"}, "HERMES_FAILED"),
        ({**PROPOSE, "advisory_only": False}, "HERMES_FAILED"),
        ({**PROPOSE, "hypothesis": "then POST /order/submit"}, "HERMES_FAILED"),
        ({"variants": [{"name": "x", "risk_pct": 9}], "advisory_only": True}, "NO_VALID_VARIANTS"),
    ])
    def test_bad_proposals_stop_the_round(self, tmp_path, bars, rules, reply, status):
        record, fake = research(tmp_path, bars, rules, reply)
        assert record["status"] == status and len(fake.prompts) == 1
        assert not (Path(record["path"]) / "study.json").exists()

    def test_choice_must_be_a_tried_variant(self, tmp_path, bars, rules):
        record, _ = research(tmp_path, bars, rules, PROPOSE, choose("something_else"))
        assert record["status"] == "INVALID_CHOICE"
        assert not (Path(record["path"]) / "holdout.json").exists()


# ── end-of-window review ────────────────────────────────────────────────────

EVENTS = [
    {"event_type": "preflight_pass", "timestamp_utc": "2024-02-01T15:00:00Z", "symbol": "AAPL",
     "daily_pnl_pct": -0.4, "gates": {"net_liquidation_eur": 1e6, "gate": "E"}},
    {"event_type": "halt_activated", "timestamp_utc": "2024-02-02T15:00:00Z", "unrealized_usd": -900},
    {"event_type": "preflight_pass", "timestamp_utc": "2023-12-01T15:00:00Z", "symbol": "OUTSIDE"},
]


def valid_review(revision=None):
    items = hermes_review.prereg_items(V7)
    return {"falsifiers": [{"id": f, "status": "NOT_REFUTED", "evidence": "e"} for f in items["falsifiers"]],
            "expected_observations": [{"id": i, "observed": None, "in_range": None}
                                      for i in items["expected_observations"]],
            "decision_rules_fired": [], "revision": revision, "summary": "s", "advisory_only": True}


@pytest.fixture
def closed_run(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    write_run(runs, "pr-r", "2024-01-02", "2024-03-29")
    (runs / "pr-r-results.md").write_text(
        "Slippage median 9 bps\nPaper P&L: +3.1%\nWin rate 60%\nGate I bound twice\n")
    events = tmp_path / "guard-events.jsonl"
    events.write_text("\n".join(json.dumps(e) for e in EVENTS) + "\n")
    approvals = tmp_path / "approval-records.jsonl"
    approvals.write_text(json.dumps({"created_at_utc": "2024-02-01T15:00:05Z", "symbol": "AAPL",
                                     "status": "approved", "max_loss_eur": 12.0}) + "\n")
    return SimpleNamespace(runs=runs, reviews=tmp_path / "reviews", events=events,
                           approvals=approvals)


def review(run, *replies, today=date(2024, 4, 2), run_id="pr-r"):
    fake = FakeHermes(*replies)
    record = hermes_review.run_review(run_id, invoke=fake, paper_runs_dir=run.runs,
                                      reviews_dir=run.reviews, events_path=run.events,
                                      approvals_path=run.approvals, today=today)
    return record, fake


class TestReview:
    def test_reviews_a_closed_sealed_run_once(self, closed_run):
        record, fake = review(closed_run, valid_review())
        assert record["status"] == "REVIEW_READY", record["problems"]
        assert Path(record["path"]).exists()
        assert record["evidence_counts"] == {"halt_activated": 1, "preflight_pass": 1}
        with pytest.raises(hermes_review.ReviewRefused, match="already has"):
            review(closed_run, valid_review())

    def test_excluded_metrics_never_reach_the_prompt(self, closed_run):
        record, fake = review(closed_run, valid_review())
        evidence = fake.prompts[0].split("EVIDENCE FROM THE WINDOW")[1]
        for leaked in ("daily_pnl_pct", "unrealized_usd", "net_liquidation_eur", "max_loss_eur",
                       "Paper P&L", "Win rate", "OUTSIDE"):
            assert leaked not in evidence, leaked
        assert "Slippage median 9 bps" in evidence and "Gate I bound twice" in evidence
        assert set(record["exclusions"]["keys_removed"]) >= {"daily_pnl_pct", "unrealized_usd",
                                                             "net_liquidation_eur", "max_loss_eur"}
        assert record["exclusions"]["results_lines_removed"] == 2

    @pytest.mark.parametrize("today, setup, needle", [
        (date(2024, 3, 29), None, "window open"),
        (date(2024, 4, 2), "unsealed", "never sealed"),
        (date(2024, 4, 2), "tampered", "SEAL BROKEN"),
        (date(2024, 4, 2), "missing", "no pre-registration"),
    ])
    def test_refusals(self, closed_run, today, setup, needle):
        run_id = "pr-r"
        doc = closed_run.runs / "pr-r-preregistration.md"
        if setup == "unsealed":
            (closed_run.runs / "pr-r-seal.json").unlink()
        elif setup == "tampered":
            doc.write_text(doc.read_text() + "\nlate edit\n")
        elif setup == "missing":
            run_id = "pr-nope"
        with pytest.raises(hermes_review.ReviewRefused, match=needle):
            review(closed_run, valid_review(), today=today, run_id=run_id)

    @pytest.mark.parametrize("review_reply, needle", [
        ({**valid_review(), "falsifiers": valid_review()["falsifiers"][:-1]}, "falsifiers"),
        ({**valid_review(), "advisory_only": False}, "advisory_only"),
        (valid_review({"decision_rule": "Returns were disappointing", "change": "x",
                       "justification": "y"}), "section 5 decision rule"),
        (valid_review({"decision_rule": "`RISK_ON` frequency far outside 3.4", "change": "raise SMA",
                       "justification": "Sharpe was low"}), "excluded metric"),
    ])
    def test_invalid_reviews_are_not_recorded(self, closed_run, review_reply, needle):
        record, _ = review(closed_run, review_reply)
        assert record["status"] == "REVIEW_REJECTED"
        assert any(needle in p for p in record["problems"]), record["problems"]
        assert not paper_runs.is_reviewed("pr-r", closed_run.reviews)   # budget not spent

    def test_a_busy_window_still_fits_one_prompt(self, closed_run):
        busy = [{"event_type": "preflight_fail", "timestamp_utc": f"2024-02-{1 + i % 28:02d}T15:00:00Z",
                 "reason": "x" * 300} for i in range(4000)]
        closed_run.events.write_text("\n".join(json.dumps(e) for e in busy) + "\n")
        record, fake = review(closed_run, valid_review())
        assert len(fake.prompts[0]) <= hermes_review.MAX_PROMPT_CHARS
        assert record["evidence_counts"] == {"preflight_fail": 4000}
        assert '"guard_events_omitted":' in fake.prompts[0] and "NOT_EXERCISED, not" in fake.prompts[0]

    def test_a_revision_answering_a_decision_rule_is_accepted(self, closed_run):
        rev = {"decision_rule": "RISK_ON frequency far outside 3.4", "version_from": "1.1",
               "version_to": "1.1.1", "change": "fix SPY series alignment",
               "justification": "regime implementation check found stale SPY bars"}
        record, _ = review(closed_run, valid_review(rev))
        assert record["status"] == "REVIEW_READY", record["problems"]

    def test_parses_the_real_v7_preregistration(self):
        items = hermes_review.prereg_items(V7)
        assert items["falsifiers"] == [f"F{i}" for i in range(1, 16)]
        assert items["expected_observations"] == [f"3.{i}" for i in range(1, 10)]
        assert len(items["decision_rules"]) == 7
        assert paper_runs.window(V7) == ("2026-08-17", "2026-11-13")


# ── separation from the trade path ──────────────────────────────────────────

NEW_MODULES = {"hermes_research", "hermes_review", "paper_runs", "sim.backtest", "sim"}


def _imports(path: Path) -> set:
    names = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            names |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


@pytest.mark.parametrize("module", ["hermes_advisory.py", "guard.py", "bridge.py", "monitor.py",
                                   "trading_agent/legacy_guard.py", "trading_agent/http_compat.py",
                                   "trading_agent/application.py", "trading_agent/runtime.py"])
def test_trade_path_imports_none_of_it(module):
    assert not (_imports(REPO / module) & NEW_MODULES)


def test_hermes_proposal_does_not_reach_research_or_reviews():
    src = (REPO / "trading_agent/cli/operator_workflow_helpers.py").read_text(encoding="utf-8")
    start = src.index("def _run_hermes_proposal(")
    body = src[start:src.index("\ndef ", start + 10)]
    for term in ("hermes_research", "hermes_review", "backtest", "research", "reviews"):
        assert term not in body


@pytest.mark.parametrize("module", ["hermes_research.py", "paper_runs.py", "sim/backtest.py"])
def test_research_reads_no_outcomes(module):
    src = (REPO / module).read_text()
    code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    body = code.split('"""', 2)[-1]                     # skip the module docstring
    for term in ("GUARD_EVENTS_PATH", "APPROVAL_RECORDS_PATH", "SUBMITTED_APPROVALS_PATH",
                 "guard-events", "approval-records", "-results.md", "/positions", "/account",
                 "fetch_account", "RESEARCH_DIR.glob", "RESEARCH_DIR.iterdir"):
        assert term not in body, f"{module} references {term}"


def test_research_never_reads_back_earlier_research():
    src = (REPO / "hermes_research.py").read_text()
    assert not re.search(r"(glob|iterdir|listdir)\(", src)
    assert "research.json\").read" not in src and "json.loads" not in src.replace(
        "value = json.loads(raw", "")
