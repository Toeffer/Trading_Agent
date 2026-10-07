# Paper Runs

> **Purpose:** pre-registration documents and results for paper validation runs.
> **Governing decision:** `STRATEGY_V1_1_PROPOSAL_v0_1.md` §11.6 and §10.4.

---

## Why this directory exists

A paper run cannot demonstrate that a strategy is profitable. Detecting a Sharpe
ratio of 1.0 at `t = 2` requires roughly **four years** of observations, and paper
fills are optimistic on queue position, partial fills, market impact, and
gap-throughs. Any profit figure produced over a few months describes that
quarter's market regime, not the strategy.

What a paper run **can** do is refute specific design claims — a single
counterexample is sufficient — and calibrate fast-converging estimates such as
slippage. That is the whole purpose of a run, and the reason pre-registration is
mandatory.

## The failure mode this guards against

Reviewing results and adjusting, then reviewing and adjusting again, is
in-sample optimisation performed by hand. Each look consumes the dataset. Five
adjustments over one quarter leave a strategy fitted to that quarter, however
principled each individual decision felt at the time.

`strategy_v1.md` §15 evaluates each change in isolation and is **structurally
blind** to that accumulation. Pre-registration and the revision budget are the
defence.

The hazard is sharper in this architecture than in a purely human process: an
LLM assistant asked "why did this happen?" will reliably produce a fluent,
plausible explanation for pure noise. **Fluency of explanation is not evidence.**

## Procedure

1. Copy `TEMPLATE-preregistration.md` to `<run-id>-preregistration.md`.
2. Fill in every `<<FILL IN>>` marker. The expected values must be **your own
   prior**, formed before looking at any results from this run.
3. Commit it.
4. Seal it: `python3 scripts/seal-preregistration.py docs/paper-runs/<run-id>-preregistration.md`
   — this records the SHA-256 in `<run-id>-seal.json`. Commit that too.
5. Only then start the run.

## Rules

| Rule | Detail |
|---|---|
| Amendment after the run starts | **Voids the run as evidence.** Start a new run instead. |
| Revision budget | **One** strategy revision per validation window. |
| Unplanned revisions | A revision not matching a pre-registered decision rule needs its own pre-registration and its own window. It does not inherit the current one. |
| Wrong predictions | **A valid and useful result.** Record the mismatch; do not retrofit the expectation. |

## Files

| Pattern | Contents |
|---|---|
| `TEMPLATE-preregistration.md` | The template. Do not fill in directly. |
| `<run-id>-preregistration.md` | The pre-registration for one run. |
| `<run-id>-seal.json` | SHA-256 seal, written by the seal script. |
| `<run-id>-results.md` | Observations, written after the run. Never edits the pre-registration. |
| `~/.openclaw/reviews/<run-id>/review.json` | End-of-window review (outside the repo), written once per run. |

## End-of-window review (added 2026-09-30)

After the planned end date, `ibkr-operator hermes-review --run-id <run-id>` has Hermes
score the run against this pre-registration: every falsifier, every expected range,
the decision rules that fired, and at most one revision, which must quote a section 5
rule. It refuses a run that is unsealed, whose seal no longer matches, whose window is
still open, or that already has a review. P&L-type fields and results lines that
mention an excluded metric are removed before Hermes sees anything.

This is the one place outcomes reach Hermes — a scoped amendment of §11.6, approved by
Chris on 2026-09-30 and recorded in `docs/HERMES_RESEARCH.md` §4. The review is a
draft; a change still goes §15 → §16 version bump → Chris → changelog → a new sealed
pre-registration.

A sealed run that was abandoned for a newer one can be closed out with
`--superseded-by <new-run-id>` (no Hermes call). Until a run has one of these records,
`hermes-research` stops its market data before that run's start date.
