# Hermes as the research brain — research, backtests, end-of-window review

> Added 2026-09-30. Governing decision: `STRATEGY_V1_1_PROPOSAL_v0_1.md` §11.6, as
> amended below. Nothing here touches the trade path, the kill switches, the rules
> file or the H1 boundary.

OpenClaw/Werner is the muscle: it runs the approval cycle through the bridge and
the guard. Hermes is the brain. Until now, the brain could only fill in one trade
proposal at a time (`hermes-proposal`) and never learned anything, by design
(Decision 11.6). Three tools let Hermes develop strategy **without** creating the
feedback loop that decision forbids:

| Tool | What Hermes does | What Hermes sees | What it produces |
|---|---|---|---|
| `ibkr-operator hermes-research` | proposes up to 4 variants of the strategy, picks at most one, drafts a versioned proposal and pre-registration sections | strategy documents, the variant schema, train-period backtests | `~/.openclaw/research/<id>/` (draft for Chris) |
| `python -m sim.backtest` | nothing (Chris's own tool) — the engine the research mode uses | — | `study.json`, `holdout.json` |
| `ibkr-operator hermes-review --run-id <id>` | scores a finished paper run against its sealed pre-registration; drafts a version bump if a pre-registered decision rule calls for one | the sealed pre-registration and the window's evidence, with P&L-type data removed | `~/.openclaw/reviews/<id>/review.json` (written once) |

The trade path (`hermes_advisory.py`, `hermes-proposal`, bridge, guard) imports none
of this, and nothing here is read back by it. `tests/test_hermes_research_review.py`
pins that separation; `tests/test_hermes_no_outcome_feedback.py` still pins the
trade-path adapter.

## 1. Backtests (`sim/backtest.py`)

**Everything it produces is labelled BACKTEST: hypothetical, never paper-run
evidence, never a readiness claim.**

A *variant* is a small, bounded parameter set (`VARIANT_FIELDS`): trend SMA length
and trend exit, relative-strength filter and lookback, regime filter, inverse-vol
scaling, ATR multiplier, time exit, risk %, position %, exposure %, max positions,
new trades per day. Unknown fields are rejected, like preflight. A variant can be
tighter than the live system, never looser:

- **Stop** — `guard.calc_stop()` on the same 30-day bar window the guard fetches;
  `atr_multiplier ≤ 2.0` can only move the ATR leg closer to the entry.
- **Size** — `guard.compute_final_max_shares()` with the variant's caps; risk %,
  position % and exposure % are capped at the values in `paper-trading-rules.yaml`.
- **Gates** — allowlist only (SPY is the regime benchmark, never traded), long only,
  Gate I sector cap, trades per day (signal exits count, broker-side stop fills do
  not), weekly loss halt.
- **Signals** — `strategy_v1_1_core` regime, inverse-vol scalar, effective budget and
  cross-sectional RS: the same functions the strategy uses.

Execution: signal at the close of day *t*, order at the open of *t+1* with slippage;
stops fill at the stop, or at the open on a gap. Not modelled: the intraday daily
loss halt, entry blackout windows, partial fills, market impact, FX.

**Discipline.** At most 5 variants per study (the current strategy counts as one),
and every one is reported. The data are split into train and holdout (default: the
last 30 % after a one-year warm-up). Train results do not depend on holdout data
(tested). The holdout is evaluated **once**, for one variant: `holdout.json` is
created exclusively, and a second look is refused.

```bash
python -m sim.backtest --data DIR --variants variants.json --out ~/research/study-1
python -m sim.backtest --data DIR --study ~/research/study-1/study.json --holdout <variant>
```

`DIR` holds `<SYMBOL>.csv` files (`date,open,high,low,close,volume`) — any free
daily-bar source works, no IBKR data subscription needed. `--rules` defaults to the
live rules file (read only).

## 2. Research mode (`ibkr-operator hermes-research`)

```bash
ibkr-operator hermes-research --data DIR --request "Would tighter stops help in CAUTION?"
ibkr-operator hermes-research                     # bars from the bridge's /market/bars (5 Y)
ibkr-operator hermes-research --model <model>     # default gpt-5.5
```

1. **Outcome cutoff.** Market data stop the day before the start of every sealed run
   that has no end-of-window record yet (`paper_runs.outcome_cutoff`). Bars from inside
   an open window would tell Hermes how its pre-registered strategy is doing.
2. **Propose.** Hermes gets the strategy documents (`docs/STRATEGY.md`,
   `docs/strategy_v1.md`), the variant schema with its live ceilings, and a train-period
   data summary. It returns a hypothesis and up to 4 variants. Invalid variants are
   dropped and listed.
3. **Train backtests** for the current strategy and every valid variant.
4. **Choose.** Hermes sees every train result and picks at most one, or none, and
   drafts the strategy proposal (version bump, §15 anti-overfit answers) and
   pre-registration sections 3 and 5.
5. **Holdout — one look, for Chris.** If Hermes chose a variant, its holdout result is
   computed after Hermes has committed, and goes into the draft. Hermes never sees it.
6. **Output.** `research.json` (every prompt's evidence, response, variant, result) and
   `draft.md`. Nothing else is written. Earlier research packages are never read back
   (§11.6.6: notes that shape proposals are undocumented strategy drift).

A draft is not a strategy change. If Chris accepts it, the normal path applies:
§15 checklist → §16 version bump → changelog → a fresh pre-registration, filled with
Chris's own priors, committed and sealed before the run starts.

## 3. End-of-window review (`ibkr-operator hermes-review`)

```bash
ibkr-operator hermes-review --run-id pr-2026-08-v7
ibkr-operator hermes-review --run-id pr-old --superseded-by pr-new   # close out an abandoned run
```

Refused unless the pre-registration is **sealed**, the **seal hash still matches**,
and the **planned end date has passed**. One record per run: a second review is
refused, which is how the one-revision-per-window budget is enforced.

Evidence: guard events and approval records dated inside the window, and the run's
`-results.md` if it exists. **Removed before the prompt is built:** every field whose
name matches P&L, profit, realized/unrealized, equity, net liquidation, Sharpe, win
rate, drawdown, largest winner/loser, return %, and every results-document line that
mentions one. The record lists what was removed. If the window's events do not fit one
prompt, the oldest are omitted and the prompt says so (an untested falsifier is then
`NOT_EXERCISED`, never `NOT_REFUTED`).

Hermes must score every falsifier (`REFUTED` / `NOT_REFUTED` / `NOT_EXERCISED`) and
every expected-observation range, name the decision rules that fired, and may propose
**one** revision, which must quote a section 5 decision rule. A review that misses an
item, cites an excluded metric, or proposes a revision outside section 5 is rejected
and **not** recorded — the budget is not spent on it.

`--superseded-by` records a sealed run as abandoned without a review (no Hermes call),
so an old unreviewed run stops holding the research cutoff.

## 4. Decision 11.6 — scoped amendment (approved by Chris, 2026-09-30)

Approved in-session on 2026-09-30 ("relax the stop check and build options 1 and 2
and 3", option 3 being this review). Recorded here rather than in the proposal
document, whose SHA-256 is pinned by its manifest.

**Unchanged:** learning means falsification and calibration; P&L is excluded as a
decision input; pre-registration is mandatory; at most one revision per window; no
autonomous parameter adaptation; the trade-path adapter stays stateless with respect
to outcomes; the only path from observation to change is §11.6.5.

**Amended:** §11.6.5 said Hermes never adjusts anything based on outcomes. It still
never *adjusts* anything. It may now **read** outcomes in exactly one place — the
end-of-window review of a sealed, closed run — to score the pre-registration and draft
a version bump for Chris. The review supplies the "observation → pre-registered decision
rule" step of §11.6.5; everything after it (§15, §16, Chris, changelog) is unchanged.

**Added:** Hermes may develop strategy variants in research mode on historical market
data that ends before any open window, with a variant budget and a single holdout look.
Its output is a draft; §11.6.6's rule applies — nothing from research influences a
trade proposal until it is part of a versioned, approved strategy.
