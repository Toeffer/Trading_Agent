# Paper Run Pre-Registration — `<<RUN-ID>>`

> **Status:** DRAFT until sealed. Sealed documents must not be amended.
> **Governing sections:** proposal §10.4 (protocol), §10.1 (falsifiers), §11.6 (rationale).
> **Created:** `<<YYYY-MM-DD>>`
> **Sealed:** `<<YYYY-MM-DD, or "not yet">>`

---

> ### How to use this template
>
> Sections 1, 2, 3 and 5 require **your** input. Sections 4, 6 and 7 are pre-filled
> because they follow from the design rather than from judgement.
>
> **Section 3 is deliberately blank.** The expected values must be your own prior,
> formed before seeing any results from this run. Werner does not supply them: a
> number suggested by the assistant and then "confirmed" is an anchor, not a
> pre-registration, and it would defeat the purpose of the document. Guidance on
> *how* to form each estimate is given; the estimate itself is yours.
>
> Being wrong here is fine and useful. Being vague is not — "roughly normal" cannot
> be contradicted by any observation, so it registers nothing.

---

## 1. Run identity

| Field | Value |
|---|---|
| Run ID | `<<FILL IN — e.g. pr-2026-08>>` |
| Start date | `<<FILL IN>>` |
| Minimum window | 60 trading days, or until every §10.1 check has been exercised at least once — whichever is **longer** (§10.5) |
| Planned end date | `<<FILL IN>>` |
| Operator | Chris |

## 2. Strategy version under test

| Field | Value |
|---|---|
| Strategy version | `<<FILL IN — e.g. v1.1.0>>` |
| Proposal version | `<<FILL IN — e.g. 0.8>>` |
| Manifest `deterministic_manifest_hash` | `<<FILL IN — from strategy_v1_1_proposal_v0_1.manifest.json>>` |
| paper-trading-rules.yaml normalized configuration SHA-256 | `<<FILL IN>>` |
| Git runtime-safety pin | `<<FILL IN>>` |

Recording all strategy/runtime pins exactly defines what is under test. A change to
any pinned strategy/runtime input ends the run unless the change is explicitly
excluded by the pin definitions below.

**Git runtime-safety pin.** This is the most recent commit that changed any of the
enumerated runtime-safety paths, not repository HEAD. Documentation-only commits may
be layered above it without invalidating this pin, provided none of the enumerated
runtime-safety paths change. Do **not** pin raw `git log -1` HEAD — sealing this very
document is itself a commit, so the moment it lands (and its merge, if sealed via PR),
HEAD moves past whatever it pinned. This is not hypothetical: the `pr-2026-08-v2` seal
pinned `5a4654b...` as "the deployed master commit," and that pin went stale within
hours, invalidated by its own sealing commit landing on the same branch.

Compute it with:

```bash
git log -1 --format=%H -- \
  bridge.py guard.py monitor.py ibkr_operator.py \
  strategy_v1_1_core.py strategy_v1_1_advisory.py
```

If this command returns a different commit during the run, the runtime-safety baseline
has changed and the run ends.

**YAML configuration pin.** The YAML pin is computed after normalizing only the
operational `enforced` boolean to `false`. This permits the documented
`false → true → false` order-enablement cycle (RUNBOOK §L8, required to actually start
the run being pre-registered here) without changing the strategy/risk configuration
under test. No other YAML field, comment, mapping, limit, allowlist, sector assignment,
or byte content is excluded from the pin.

The normalized pin is computed by replacing exactly one `enforced: true|false` value
with `enforced: false` before SHA-256 hashing. If zero or more than one `enforced`
field is found, verification fails closed. Any change that causes the normalized
SHA-256 to differ from the pin recorded above ends the run.

Both pins can be computed and — once this document is sealed — checked against it in
one read-only command: `ibkr-operator preregistration-pin-verify --doc <this file>`.

## 3. Expected observations — YOUR PRIOR, WRITTEN BEFORE THE RUN

State each as a **range**, not a point. A range you would be surprised to fall outside.

| # | Quantity | Your expected range | Basis for the estimate |
|---|---|---|---|
| 3.1 | Median slippage vs entry reference (bps) | `<<FILL IN>>` | Observed bid-ask spread on the allowlist during RTH, not on hope |
| 3.2 | Worst-case single-trade slippage (bps) | `<<FILL IN>>` | Widest spread seen outside the blackout windows |
| 3.3 | Share of trades where the **risk** cap binds (vs notional) | `<<FILL IN>>` % | §4.8 — depends on whether ATR stops exceed the 5% floor for your names |
| 3.4 | `RISK_ON` frequency over the window | `<<FILL IN>>` % | SPY vs its 200d SMA and 12m momentum over comparable historical periods |
| 3.5 | Median `gross_scalar` | `<<FILL IN>>` | `16% ÷ realised SPY vol`; scalar ≈ 1.0 if SPY sits near its long-run median |
| 3.6 | Trades reaching preflight per week | `<<FILL IN>>` | Signal stack: 2-of-4, RS top-half, regime, Gate I. Gate D caps at 2/day |
| 3.7 | Share of cycles ending `NO_TRADE` | `<<FILL IN>>` % | A high number is not failure — it is the filters working |
| 3.8 | Gate I rejections over the window | `<<FILL IN>>` | Zero would mean the sector cap never bound; that is informative either way |
| 3.9 | Data-quality failures per week | `<<FILL IN>>` | §4.10 thresholds, 23 series fetched per cycle |

**If any of 3.1–3.9 lands outside your stated range, that is a finding**, whether or
not the run was otherwise uneventful. Record it in the results document.

## 4. Falsifiers — PRE-FILLED (§10.1)

Each claim below is refuted by **a single counterexample**. This is the run's primary
output: no achievable sample confirms an edge, but one observation can refute a design
claim.

| # | Claim | Refuted by |
|---|---|---|
| F1 | Preflight rejects every non-allowlisted symbol | one acceptance |
| F2 | Gate I never admits a second position in one sector | one admission |
| F3 | Every BUY carries a child SELL STP | one missing stop |
| F4 | A failed child-STP placement cancels the parent BUY before it fills | one uncancelled parent |
| F5 | Stop quantity always equals entry quantity | one mismatch |
| F6 | FX is fetched on every preflight, never cached | one cached value |
| F7 | Gate D blocks the third trade of a day | one third trade |
| F8 | Gate E halts new BUY at −1% daily | one BUY after the halt |
| F9 | Approvals expire at 300s with no extension | one extension |
| F10 | Bridge restart invalidates all pending approvals | one survivor |
| F11 | Monitor reconciles every fill | one unreconciled fill |
| F12 | A partial fill counts as one daily trade | one counted differently |
| F13 | No entry occurs in the 9:30–9:45 or 15:45–16:00 ET blackouts | one entry |
| F14 | The advisory budget never exceeds the YAML ceiling | one violation |
| F15 | Hermes never emits a size, weight, or leverage figure | one occurrence |

**Any refutation is a blocker.** Fix it and restart the window — a run containing a
known refuted claim is not evidence of anything.

F4, F8, F9 and F10 may need deliberate fault injection rather than waiting for natural
occurrence. Do that in a controlled session, never during a live cycle.

## 5. Decision rules — WRITTEN IN ADVANCE

For each outcome, the change it triggers. Written **now**, so that a later change is a
response to a stated hypothesis rather than a reaction to an observed pattern.

| Observation | Pre-registered response |
|---|---|
| Any falsifier F1–F15 refuted | Halt. Fix. Restart the window. *(fixed — not negotiable)* |
| Slippage exceeds 3.2 | `<<FILL IN — e.g. tighten entry to limit orders? reduce universe to tighter spreads? accept?>>` |
| `RISK_ON` frequency far outside 3.4 | `<<FILL IN — regime parameters are conventional and should NOT be tuned to fit one window; state what you would actually do>>` |
| Trade frequency far below 3.6 | `<<FILL IN — is the filter stack over-determined? which filter would you examine first?>>` |
| Data-quality failures exceed 3.9 | `<<FILL IN>>` |
| Gate I never binds | `<<FILL IN — evidence the cap is inert, or that the ranker is well spread?>>` |
| Nothing unexpected happens | `<<FILL IN — most likely outcome; "proceed to X" is a valid answer>>` |

A response of **"record it and change nothing"** is legitimate and often correct. Not
every observation warrants action, and at this sample size most do not.

## 6. Explicitly excluded from decisions — PRE-FILLED (§10.3, §11.6)

Recorded in the results document, and **formally not decision inputs**:

| Metric | Why excluded |
|---|---|
| Paper P&L | Statistically meaningless at this horizon; upward-biased by optimistic fills |
| Win rate | Dominated by noise below n ≈ 100 |
| Paper Sharpe | Needs ~4 years at SR 1.0 for `t = 2` |
| Largest winner / loser | Pure selection on noise |

No revision may cite any of these as its justification.

## 7. Revision budget — PRE-FILLED (§10.4)

| Rule | Value |
|---|---|
| Strategy revisions permitted this window | **1** |
| After a revision | A fresh window must complete before another is proposed |
| Revision not matching a §5 decision rule | Requires its own pre-registration and its own window |
| Revisions used so far | `<<update during the run: 0>>` |

## 8. Seal

Computed by `scripts/seal-preregistration.py` after sections 1–3 and 5 are complete.

| Field | Value |
|---|---|
| SHA-256 of this document | `<<written by the seal script>>` |
| Sealed at (UTC) | `<<written by the seal script>>` |

**After sealing, this document is immutable.** Amending it voids the run as evidence;
start a new run instead. Observations belong in `<run-id>-results.md`.
