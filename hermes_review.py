"""End-of-window review — the one place paper-run outcomes reach Hermes.

`ibkr-operator hermes-review --run-id <id>` runs this, and only for a run whose
pre-registration is sealed (the seal hash still matches) and whose planned end
date has passed. Hermes scores the run against its own pre-registration:
each falsifier, each expected-observation range, which decision rules fired,
and whether the revision budget allows a change. If a pre-registered decision
rule calls for one, it drafts the version bump for Chris.

Scoped amendment of Decision 11.6 (approved by Chris 2026-09-30, recorded in
docs/HERMES_RESEARCH.md): outcomes may reach Hermes here and nowhere else.
- The trade path (hermes_advisory.py) stays outcome-free; this module is
  separate and nothing in the trade path imports it.
- P&L stays excluded (§10.3, §11.6, pre-registration §6): P&L-type fields are
  stripped from the evidence and results-document lines that mention an
  excluded metric are dropped before the prompt is built. A revision that
  cites one is rejected.
- One review per run (the revision budget is one per window); the review
  record is written once, and a second review is refused.
- Output is a draft for Chris. The change path is unchanged: observation →
  pre-registered decision rule → §15 → §16 version bump → Chris → changelog.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone
from pathlib import Path

import paper_runs
from hermes_research import parse_json_object

LABEL = "END-OF-WINDOW REVIEW DRAFT — Hermes's scoring for Chris; not a strategy change until Chris approves it"
MAX_EVENTS = 1500
# Hermes receives the prompt as one argv string (Linux caps one at 128 KiB).
MAX_PROMPT_CHARS = 120_000

# Keys removed from evidence (any depth) and results lines dropped: §6 exclusions.
EXCLUDED_KEY = re.compile(r"pnl|p_and_l|profit|realized|unrealized|equity|net_?liq|"
                          r"sharpe|win_?rate|loss_(eur|usd|pct|amount)|drawdown|"
                          r"largest_(winner|loser)|return_pct", re.I)
EXCLUDED_TEXT = re.compile(r"p\s*&\s*l|\bpnl\b|profit|win\s*rate|sharpe|largest\s+(winner|loser)|"
                           r"drawdown|net\s*liq|realized|unrealized|return\s*%|% return", re.I)
STATUSES = {"REFUTED", "NOT_REFUTED", "NOT_EXERCISED"}

REVIEW_INSTRUCTION = """
You are Hermes, reviewing a finished paper-trading validation window against
its sealed pre-registration. You are advisory only: you never trade, approve,
enable or configure anything; your review is a draft for Chris.

Rules of the review (Decision 11.6):
- Score only what the pre-registration asked. A falsifier is REFUTED by a
  single counterexample in the evidence, NOT_REFUTED if the evidence shows the
  check was exercised and held, NOT_EXERCISED if the evidence never tested it.
- For each expected observation, state what was observed and whether it fell
  in the pre-registered range; null if the evidence does not show it.
- A revision may only answer a section 5 decision rule, quote that rule's
  observation exactly, and is limited to one. P&L, win rate, Sharpe and
  largest winner/loser are excluded and were removed from the evidence; never
  cite them. "Record it and change nothing" is a legitimate and often correct
  outcome. Fluency is not evidence: if the evidence is thin, say so.
""".strip()

REVIEW_FORMAT = """
Reply with one JSON object only:
{
  "falsifiers": [{"id": "F1", "status": "REFUTED|NOT_REFUTED|NOT_EXERCISED", "evidence": "..."}],
  "expected_observations": [{"id": "3.1", "observed": "... or null", "in_range": true|false|null, "note": "..."}],
  "decision_rules_fired": [{"observation": "<section 5 observation, verbatim>", "response": "..."}],
  "revision": null or {"decision_rule": "<section 5 observation, verbatim>", "version_from": "...",
                       "version_to": "...", "change": "...", "justification": "..."},
  "summary": "<five sentences at most>",
  "advisory_only": true
}
Every falsifier and every expected observation in the pre-registration must appear exactly once.
""".strip()


class ReviewRefused(RuntimeError):
    """The run is not reviewable (unsealed, broken seal, open, already reviewed)."""


def _table(text: str, heading: str) -> list[list[str]]:
    """Rows (cells) of the first table under the '## <n>. heading' section."""
    m = re.search(rf"^## \d+\. {re.escape(heading)}.*?$(.*?)(?=^## |\Z)", text, re.M | re.S)
    rows = []
    for line in (m.group(1) if m else "").splitlines():
        if not line.startswith("|") or re.match(r"^\|[\s|:-]+\|$", line):
            continue
        rows.append([c.strip() for c in line.strip().strip("|").split("|")])
    return rows[1:]                         # drop the header row


def prereg_items(text: str) -> dict:
    return {
        "falsifiers": [r[0] for r in _table(text, "Falsifiers") if re.fullmatch(r"F\d+", r[0])],
        "expected_observations": [r[0] for r in _table(text, "Expected observations")
                                  if re.fullmatch(r"\d+\.\d+", r[0])],
        "decision_rules": [r[0] for r in _table(text, "Decision rules")],
    }


def _norm(text) -> str:
    return re.sub(r"\s+", " ", str(text or "").replace("`", "")).strip().lower()


def check_reviewable(run_id: str, *, paper_runs_dir=None, reviews_dir=None,
                     today: date | None = None) -> dict:
    doc = paper_runs.prereg_path(run_id, Path(paper_runs_dir or paper_runs.PAPER_RUNS))
    if not doc.exists():
        raise ReviewRefused(f"no pre-registration at {doc}")
    seal = paper_runs.seal_status(doc)
    if not seal["sealed"]:
        raise ReviewRefused(f"{run_id} was never sealed; an unsealed run is not evidence")
    if not seal["intact"]:
        raise ReviewRefused(f"SEAL BROKEN — {doc.name} changed after sealing; the run is void")
    text = doc.read_text()
    start, end = paper_runs.window(text)
    if not start or not end:
        raise ReviewRefused("section 1 has no Start date / Planned end date")
    today = today or date.today()
    if today.isoformat() <= end:
        raise ReviewRefused(f"window open until {end}; the review runs after the planned end")
    if paper_runs.is_reviewed(run_id, reviews_dir):
        raise ReviewRefused(f"{run_id} already has an end-of-window review; one per window")
    return {"doc": doc, "text": text, "start": start, "end": end, "seal": seal}


def _strip(value, dropped: set):
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if EXCLUDED_KEY.search(str(k)):
                dropped.add(str(k))
            else:
                out[k] = _strip(v, dropped)
        return out
    if isinstance(value, list):
        return [_strip(v, dropped) for v in value]
    return value


def _jsonl_in_window(path: Path, start: str, end: str, stamp_keys) -> list[dict]:
    out = []
    if not path or not Path(path).exists():
        return out
    for line in Path(path).read_text().splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        stamp = next((str(row[k]) for k in stamp_keys if row.get(k)), "")
        if start <= stamp[:10] <= end:
            out.append(row)
    return out


def collect_evidence(run_id: str, start: str, end: str, *, events_path, approvals_path,
                     results_path) -> dict:
    """Window-limited evidence with every excluded metric removed."""
    dropped: set = set()
    events = _jsonl_in_window(events_path, start, end, ("timestamp_utc", "timestamp"))
    approvals = _jsonl_in_window(approvals_path, start, end,
                                 ("created_at_utc", "timestamp_utc", "timestamp"))
    counts: dict = {}
    for e in events:
        counts[e.get("event_type", "?")] = counts.get(e.get("event_type", "?"), 0) + 1
    results_lines, dropped_lines = [], 0
    if results_path and Path(results_path).exists():
        for line in Path(results_path).read_text().splitlines():
            if EXCLUDED_TEXT.search(line):
                dropped_lines += 1
            else:
                results_lines.append(line)
    events, approvals = _strip(events, dropped), _strip(approvals, dropped)
    evidence = {
        "run_id": run_id, "window": {"start": start, "end": end},
        "guard_event_counts": dict(sorted(counts.items())),
        "results_document": "\n".join(results_lines) if results_lines else None,
    }
    # If the prompt would not fit, the oldest records go first; the omission is stated.
    keep = min(len(events), MAX_EVENTS)
    while True:
        kept_approvals = min(len(approvals), keep)
        evidence.update(guard_events=events[len(events) - keep:],
                        guard_events_omitted=len(events) - keep,
                        approval_records=approvals[len(approvals) - kept_approvals:],
                        approval_records_omitted=len(approvals) - kept_approvals)
        if len(_dumps(evidence)) <= MAX_PROMPT_CHARS - 40_000 or keep == 0:
            break
        keep //= 2
    exclusions = {"keys_removed": sorted(dropped), "results_lines_removed": dropped_lines}
    return {"evidence": evidence, "exclusions": exclusions}


def build_review_prompt(prereg_text: str, evidence: dict) -> str:
    return "\n\n".join([
        REVIEW_INSTRUCTION,
        "SEALED PRE-REGISTRATION:\n" + prereg_text,
        "EVIDENCE FROM THE WINDOW (JSON, excluded metrics removed; if events were omitted, "
        "a falsifier they could have tested is NOT_EXERCISED, not NOT_REFUTED):\n"
        + _dumps(evidence),
        REVIEW_FORMAT,
    ])


def validate_review(review: dict, items: dict) -> list[str]:
    """Problems with Hermes's review; empty when it can be recorded as-is."""
    problems = []
    if review.get("advisory_only") is not True:
        problems.append("advisory_only is not true")
    for key, allowed in (("falsifiers", STATUSES), ("expected_observations", None)):
        got = [r.get("id") for r in review.get(key) or [] if isinstance(r, dict)]
        if sorted(got) != sorted(items[key]):
            problems.append(f"{key}: expected each of {items[key]} once, got {got}")
        if allowed:
            bad = [r for r in review.get(key) or [] if r.get("status") not in allowed]
            if bad:
                problems.append(f"{key}: invalid status in {bad}")
    revision = review.get("revision")
    if revision:
        if not isinstance(revision, dict):
            problems.append("revision must be an object or null")
        else:
            if _norm(revision.get("decision_rule")) not in {_norm(r) for r in items["decision_rules"]}:
                problems.append("revision does not quote a section 5 decision rule; per section 7 "
                                "it needs its own pre-registration and window")
            cited = " ".join(str(revision.get(k, "")) for k in ("change", "justification"))
            if EXCLUDED_TEXT.search(cited):
                problems.append("revision cites an excluded metric (section 6)")
    return problems


def run_review(run_id: str, *, invoke=None, model: str = "gpt-5.5", paper_runs_dir=None,
               reviews_dir=None, events_path=None, approvals_path=None,
               today: date | None = None) -> dict:
    """Score a closed, sealed run once; the record is written exactly once."""
    import guard
    from hermes_advisory import check_forbidden
    if invoke is None:
        from hermes_advisory import invoke_hermes as invoke
    run = check_reviewable(run_id, paper_runs_dir=paper_runs_dir, reviews_dir=reviews_dir,
                           today=today)
    items = prereg_items(run["text"])
    collected = collect_evidence(
        run_id, run["start"], run["end"],
        events_path=events_path or guard.GUARD_EVENTS_PATH,
        approvals_path=approvals_path or guard.APPROVAL_RECORDS_PATH,
        results_path=run["doc"].with_name(f"{run_id}-results.md"))
    prompt = build_review_prompt(run["text"], collected["evidence"])
    if len(prompt) > MAX_PROMPT_CHARS:
        reply = {"ok": False, "error": f"prompt of {len(prompt)} chars exceeds {MAX_PROMPT_CHARS}"}
    else:
        reply = invoke(prompt, model=model, timeout=600)
    record = {"label": LABEL, "run_id": run_id, "created_utc": _now(), "model": model,
              "window": {"start": run["start"], "planned_end": run["end"]},
              "seal": run["seal"], "exclusions": collected["exclusions"],
              "evidence_counts": collected["evidence"]["guard_event_counts"],
              "hermes": {"ok": reply.get("ok"), "evidence": reply.get("evidence"),
                         "error": reply.get("error")}}
    review, problems = None, []
    if reply.get("ok"):
        raw = reply.get("raw_response", "")
        review = parse_json_object(raw)
        forbidden = check_forbidden(raw)
        problems = (["response is not a JSON object"] if review is None
                    else validate_review(review, items))
        if forbidden:
            problems.append(f"forbidden patterns in response: {forbidden}")
        record["hermes"]["raw_response"] = raw
    else:
        problems = [f"Hermes failed: {reply.get('error')}"]
    record.update(review=review, problems=problems,
                  status="REVIEW_READY" if not problems else "REVIEW_REJECTED")
    if problems:
        return record                        # nothing recorded: the budget is not spent
    return _write_once(run_id, record, reviews_dir)


def record_superseded(run_id: str, superseded_by: str, *, paper_runs_dir=None,
                      reviews_dir=None) -> dict:
    """Close out an abandoned sealed run without a Hermes review (Chris's call)."""
    base = Path(paper_runs_dir or paper_runs.PAPER_RUNS)
    for rid in (run_id, superseded_by):
        doc = paper_runs.prereg_path(rid, base)
        if not doc.exists() or not paper_runs.seal_status(doc)["sealed"]:
            raise ReviewRefused(f"{rid} is not a sealed pre-registration")
    if run_id == superseded_by:
        raise ReviewRefused("a run cannot supersede itself")
    if paper_runs.is_reviewed(run_id, reviews_dir):
        raise ReviewRefused(f"{run_id} already has an end-of-window record")
    record = {"label": "SUPERSEDED — no review; the run is not evidence", "run_id": run_id,
              "created_utc": _now(), "status": "SUPERSEDED", "superseded_by": superseded_by}
    return _write_once(run_id, record, reviews_dir)


def _write_once(run_id: str, record: dict, reviews_dir) -> dict:
    out = paper_runs.review_dir(run_id, reviews_dir)
    out.mkdir(parents=True, exist_ok=True)
    try:
        with (out / "review.json").open("x") as fh:
            fh.write(json.dumps(record, indent=2, default=str))
    except FileExistsError:
        raise ReviewRefused(f"{run_id} already has an end-of-window record") from None
    record["path"] = str(out / "review.json")
    return record


def _dumps(value) -> str:
    return json.dumps(value, separators=(",", ":"), default=str)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
