"""Hermes research mode — strategy development, away from the trade path.

`ibkr-operator hermes-research` runs this. Hermes reads the versioned strategy
documents and train-period backtests (sim/backtest.py), proposes up to
MAX_VARIANTS - 1 variants of the strategy next to the current one, picks at
most one, and drafts a versioned strategy proposal plus pre-registration
sections for it. Chris decides what, if anything, becomes the next sealed run.

Boundaries (Decision 11.6 and its 2026-09-30 amendment, docs/HERMES_RESEARCH.md):
- no paper-run outcome reaches Hermes here: nothing reads guard events,
  approvals, fills, positions, P&L or results documents, and market data stop
  before the start of every sealed run that has not had its end-of-window
  review (paper_runs.outcome_cutoff);
- earlier research packages are never read back (accumulated notes that shape
  proposals are undocumented strategy drift, §11.6.6);
- Hermes sees the train period only; the holdout is evaluated once, after
  Hermes has committed to its choice, and goes to Chris, not back to Hermes;
- output is a draft under ~/.openclaw/research/<id>/; the trade path never
  reads it, and nothing here edits rules, strategy documents or paper runs.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

import paper_runs
from sim import backtest as bt

REPO = Path(__file__).resolve().parent
RESEARCH_DIR = Path(os.environ.get("OPENCLAW_RESEARCH_DIR",
                                   str(Path.home() / ".openclaw" / "research")))
STRATEGY_DOCS = ("docs/STRATEGY.md", "docs/strategy_v1.md")
PREREG_TEMPLATE = "docs/paper-runs/TEMPLATE-preregistration.md"
MAX_PROMPT_CHARS = 120_000     # one argv string to the hermes CLI (Linux caps at 128 KiB)
LABEL = ("RESEARCH DRAFT — built on BACKTEST results (hypothetical). Not a "
         "pre-registration until Chris copies it into docs/paper-runs/, completes and seals it.")

RESEARCH_INSTRUCTION = """
You are Hermes, the research analyst for a manually approved paper-trading
system (IBKR paper account, long-only US single stocks). You design and
compare strategy variants on historical data. You never trade, approve,
enable or configure anything; your output is a draft for Chris.

What you can change is exactly the variant schema below: every field has a
hard range, the ranges are capped by the live risk rules, and the live stop
formula can only be tightened (atr_multiplier <= 2.0). Anything else — new
signals, new symbols, looser stops, bigger size — is out of scope for a
variant; mention it under "out_of_scope_ideas" instead.

Data discipline: you see the TRAIN period only. A held-out period exists and
will be evaluated once, for the single variant you choose, after you answer.
You will not see it. Backtests are hypothetical: fills at the next open plus
slippage, no partial fills, no market impact. Prefer variants that follow
from a stated hypothesis over variants that chase the best train number;
with this many comparisons the best train result is partly luck.
""".strip()

PROPOSE_FORMAT = """
Reply with one JSON object only:
{
  "hypothesis": "<what you expect to improve, and why, in two sentences>",
  "variants": [<up to %(n)d objects: {"name": "lower_snake_case", "description": "...", <schema fields you change>}>],
  "why_these": "<why these variants test the hypothesis>",
  "out_of_scope_ideas": ["<ideas the schema cannot express>"],
  "advisory_only": true
}
The current strategy ("baseline") is already included; do not repeat it.
""".strip()

CHOOSE_FORMAT = """
Reply with one JSON object only:
{
  "choice": "<one variant name from the results, or null for none>",
  "reasoning": "<why, including why not the others; say so if the evidence is too weak>",
  "strategy_proposal": {
    "title": "...", "version_from": "<current version>", "version_to": "<next version>",
    "changes": [{"parameter": "...", "from": ..., "to": ...}],
    "rationale": "...",
    "anti_overfit": {"hypothesis_before_data": "...", "variants_tried": <int>,
                     "why_not_luck": "...", "what_would_refute_it": "..."}
  },
  "preregistration_draft": {
    "expected_observations": [{"id": "3.1", "quantity": "...", "range": "...", "basis": "..."}],
    "decision_rules": [{"observation": "...", "response": "..."}],
    "additional_falsifiers": [{"claim": "...", "refuted_by": "..."}]
  },
  "advisory_only": true
}
Use choice null and leave strategy_proposal empty if no variant is worth a
paper window. Expected observations are the ranges you would be surprised to
fall outside during a paper run (see the template's section 3).
""".strip()


def _schema(rules: dict) -> dict:
    caps = bt.ceilings(rules)
    out = {}
    for key, (typ, lo, hi, default) in bt.VARIANT_FIELDS.items():
        hi = caps[hi] if isinstance(hi, str) else hi
        out[key] = ({"type": "bool", "default": default} if typ is bool else
                    {"type": typ.__name__, "min": lo, "max": hi, "default": default})
    return out


def data_summary(bars: dict, periods: dict) -> dict:
    """Per-symbol counts and train-period return; no holdout information."""
    start, end = periods["train"]["start"], periods["train"]["end"]
    out = {}
    for sym, series in sorted(bars.items()):
        train = [b for b in series if start <= b["date"] <= end]
        out[sym] = {"train_bars": len(train),
                    "train_return_pct": round(100 * (train[-1]["close"] / train[0]["close"] - 1), 2)
                    if len(train) > 1 else None}
    return out


def build_propose_prompt(context: dict) -> str:
    return "\n\n".join([
        RESEARCH_INSTRUCTION,
        "CONTEXT (JSON):\n" + json.dumps(context, indent=1, default=str),
        PROPOSE_FORMAT % {"n": bt.MAX_VARIANTS - 1},
    ])


def build_choose_prompt(context: dict, study: dict, template: str) -> str:
    results = {r["variant"]["name"]: {"variant": r["variant"], "metrics": r["metrics"],
                                      "skipped_entries": r["skipped_entries"]}
               for r in study["train_results"]}
    return "\n\n".join([
        RESEARCH_INSTRUCTION,
        "CONTEXT (JSON):\n" + json.dumps(context, indent=1, default=str),
        "TRAIN RESULTS — every variant tried, BACKTEST (JSON):\n"
        + json.dumps(results, indent=1, default=str),
        "PRE-REGISTRATION TEMPLATE (for the shape of sections 3 and 5):\n" + template,
        CHOOSE_FORMAT,
    ])


def parse_json_object(raw: str) -> dict | None:
    start, end = (raw or "").find("{"), (raw or "").rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        value = json.loads(raw[start:end + 1])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _ask(invoke, prompt: str, model: str, step: str, record: dict) -> dict | None:
    from hermes_advisory import check_forbidden
    if len(prompt) > MAX_PROMPT_CHARS:
        reply = {"ok": False, "error": f"prompt of {len(prompt)} chars exceeds {MAX_PROMPT_CHARS}"}
    else:
        reply = invoke(prompt, model=model, timeout=600)
    entry = {"step": step, "ok": reply.get("ok"), "evidence": reply.get("evidence"),
             "error": reply.get("error")}
    record["hermes_calls"].append(entry)
    if not reply.get("ok"):
        return None
    raw = reply.get("raw_response", "")
    entry["raw_response"] = raw
    entry["forbidden_patterns"] = check_forbidden(raw)
    parsed = parse_json_object(raw)
    if parsed is None:
        entry["error"] = "response is not a JSON object"
    elif entry["forbidden_patterns"]:
        entry["error"] = f"forbidden patterns in response: {entry['forbidden_patterns']}"
        parsed = None
    elif parsed.get("advisory_only") is not True:
        entry["error"] = "response does not declare advisory_only: true"
        parsed = None
    return parsed


def run_research(*, bars: dict, rules: dict, request: str = "", model: str = "gpt-5.5",
                 invoke=None, holdout_fraction: float = 0.3, research_dir=None,
                 paper_runs_dir=None, reviews_dir=None, today: date | None = None,
                 data_source: str = "") -> dict:
    """One research round; returns and persists the package."""
    if invoke is None:
        from hermes_advisory import invoke_hermes as invoke
    research_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
    out_dir = Path(research_dir or RESEARCH_DIR) / research_id
    record = {"label": LABEL, "research_id": research_id, "created_utc": _now(),
              "model": model, "request": request, "data_source": data_source,
              "hermes_calls": [], "status": "STARTED"}

    cutoff = paper_runs.outcome_cutoff(Path(paper_runs_dir or paper_runs.PAPER_RUNS),
                                       reviews_dir, today)
    bars = bt.truncate_before(bars, cutoff["cutoff"])
    record["outcome_cutoff"] = cutoff
    record["data_fingerprint"] = bt.fingerprint(bars)
    record["data_range"] = dict(zip(("first", "last"), bt.date_range(bars)))
    periods = bt.split_period(bars, holdout_fraction)
    record["periods"] = periods

    docs = {p: (REPO / p).read_text() for p in STRATEGY_DOCS}
    context = {
        "request_from_chris": request or "(none — propose what you think is most worth testing)",
        "strategy_documents": docs,
        "variant_schema": _schema(rules),
        "baseline_variant": bt.validate_variant({"name": "baseline"}, rules),
        "train_period": periods["train"],
        "data": data_summary(bt.truncate_before(bars, periods["holdout"]["start"]), periods),
        "benchmark": bt.BENCHMARK,
    }

    def finish(status, **extra):
        record.update(status=status, **extra)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "research.json").write_text(json.dumps(record, indent=2, default=str))
        if record.get("draft"):
            (out_dir / "draft.md").write_text(render_draft(record))
        record["path"] = str(out_dir)
        return record

    proposed = _ask(invoke, build_propose_prompt(context), model, "propose", record)
    if proposed is None:
        return finish("HERMES_FAILED", error=record["hermes_calls"][-1].get("error"))
    variants, rejected = [{"name": "baseline", "description": "current strategy"}], []
    for spec in proposed.get("variants") or []:
        try:
            v = bt.validate_variant(spec, rules)
        except bt.VariantError as e:
            rejected.append({"variant": spec, "reason": str(e)})
            continue
        if v["name"] in {x["name"] for x in variants}:
            rejected.append({"variant": spec, "reason": "duplicate name"})
        elif len(variants) >= bt.MAX_VARIANTS:
            rejected.append({"variant": spec, "reason": f"over the {bt.MAX_VARIANTS}-variant budget"})
        else:
            variants.append(spec)
    record["proposal"] = {k: proposed.get(k) for k in ("hypothesis", "why_these", "out_of_scope_ideas")}
    record["rejected_variants"] = rejected
    if len(variants) == 1:
        return finish("NO_VALID_VARIANTS")

    study = bt.run_study(bars, variants, rules, out_dir, periods=periods)
    template = (REPO / PREREG_TEMPLATE).read_text()
    chosen = _ask(invoke, build_choose_prompt(context, study, template), model, "choose", record)
    if chosen is None:
        return finish("HERMES_FAILED", error=record["hermes_calls"][-1].get("error"))
    choice = chosen.get("choice")
    names = [v["name"] for v in study["variants"]]
    if choice is not None and choice not in names:
        return finish("INVALID_CHOICE", error=f"choice {choice!r} is not one of {names}")
    record["draft"] = {k: chosen.get(k) for k in
                       ("choice", "reasoning", "strategy_proposal", "preregistration_draft")}
    record["train_results"] = {r["variant"]["name"]: r["metrics"] for r in study["train_results"]}
    if choice is None or choice == "baseline":
        return finish("NO_CHANGE_PROPOSED")
    # After Hermes has committed: the one holdout look, for Chris only.
    holdout = bt.evaluate_holdout(out_dir / "study.json", bars, choice, rules)
    return finish("DRAFT_READY", holdout={"variant": choice, "metrics": holdout["result"]["metrics"],
                                          "baseline_train": record["train_results"]["baseline"]})


def render_draft(record: dict) -> str:
    d = record["draft"]
    sp = d.get("strategy_proposal") or {}
    pre = d.get("preregistration_draft") or {}
    lines = [f"# Research draft {record['research_id']}", "", f"> {LABEL}", "",
             f"- Status: **{record['status']}**",
             f"- Model: `{record['model']}` · created {record['created_utc']}",
             f"- Data: {record['data_range']['first']} → {record['data_range']['last']} "
             f"(cut off before {record['outcome_cutoff']['cutoff'] or 'no open run'}), "
             f"fingerprint `{record['data_fingerprint'][:16]}`",
             f"- Train {record['periods']['train']['start']} → {record['periods']['train']['end']} · "
             f"holdout {record['periods']['holdout']['start']} → {record['periods']['holdout']['end']}",
             "", "## Hypothesis", "", str((record.get("proposal") or {}).get("hypothesis")), "",
             "## Choice", "", f"**{d.get('choice')}** — {d.get('reasoning')}", "",
             "## Train results (every variant tried, BACKTEST)", "",
             "| Variant | Return % | Max DD % | Sharpe | Entries/wk | Avg R |", "|---|---|---|---|---|---|"]
    for name, m in (record.get("train_results") or {}).items():
        lines.append(f"| {name} | {m['total_return_pct']} | {m['max_drawdown_pct']} | {m['sharpe']} "
                     f"| {m['entries_per_week']} | {m['avg_r_multiple']} |")
    if record.get("holdout"):
        m = record["holdout"]["metrics"]
        lines += ["", "## Holdout — one look, not shown to Hermes", "",
                  f"`{record['holdout']['variant']}`: return {m['total_return_pct']} %, "
                  f"max DD {m['max_drawdown_pct']} %, Sharpe {m['sharpe']}, "
                  f"entries/wk {m['entries_per_week']}, avg R {m['avg_r_multiple']}."]
    lines += ["", "## Strategy proposal", "", "```json", json.dumps(sp, indent=2), "```",
              "", "## Pre-registration draft (sections 3 and 5, plus falsifiers)", "",
              "| # | Quantity | Expected range | Basis |", "|---|---|---|---|"]
    for row in pre.get("expected_observations") or []:
        lines.append("| {id} | {quantity} | `{range}` | {basis} |".format(
            **{k: _cell(row.get(k)) for k in ("id", "quantity", "range", "basis")}))
    lines += ["", "| Observation | Pre-registered response |", "|---|---|"]
    for row in pre.get("decision_rules") or []:
        lines.append(f"| {_cell(row.get('observation'))} | `{_cell(row.get('response'))}` |")
    for row in pre.get("additional_falsifiers") or []:
        lines.append(f"- Falsifier: {_cell(row.get('claim'))} — refuted by {_cell(row.get('refuted_by'))}")
    lines += ["", "## Next steps (Chris)", "",
              "1. Judge the draft; the holdout number is one look, not proof.",
              "2. If accepted: §15 checklist, §16 version bump, changelog — the normal path.",
              "3. Copy `TEMPLATE-preregistration.md`, fill it from this draft with your own "
              "priors, commit and seal it before the run starts."]
    return "\n".join(lines) + "\n"


def _cell(value) -> str:
    return re.sub(r"\s+", " ", str(value if value is not None else "")).replace("|", "/")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
