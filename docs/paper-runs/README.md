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
