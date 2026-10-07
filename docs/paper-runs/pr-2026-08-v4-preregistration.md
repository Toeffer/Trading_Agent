# Paper Run Pre-Registration — `pr-2026-08-v4`

> **Status:** DRAFT until sealed. Sealed documents must not be amended.
> **Governing sections:** proposal §10.4 (protocol), §10.1 (falsifiers), §11.6 (rationale).
> **Created:** 2026-08-10
> **Sealed:** not yet
>
> Run ID `pr-2026-08-v4` is a placeholder Werner picked to name this file — rename the
> file and this header together if you want something else. That's an administrative
> choice, not a prediction, so it's fine for Werner to propose a default.

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
| Run ID | `pr-2026-08-v4` — rename if you'd rather |
| Start date | `2026-08-17` |
| Minimum window | 60 trading days, or until every §10.1 check has been exercised at least once — whichever is **longer** (§10.5) |
| Planned end date | `2026-11-13` |
| Operator | Chris |

**Note on start date:** before this window opens, two things must be true:
(1) the runtime-safety paths listed in §2 must resolve to the exact Git
runtime-safety pin recorded there on the live bridge host; and
(2) `paper-trading-rules.yaml` on the bridge host must match the configuration
pin defined in §2. A GitHub tag or documentation-only commit does not by itself
change the runtime-safety baseline.

## 2. Strategy version under test

| Field | Value |
|---|---|
| Strategy version | v1.1.0 *(not yet "active" per the 19A manifest — this run is what would produce the evidence to promote it)* |
| Proposal version | 0.9 |
| Manifest `deterministic_manifest_hash` | `33bfa9f8ababd4153e7f1ebc0ece0e93a0aba719cf470977514420682fe2ef62` |
| paper-trading-rules.yaml normalized configuration SHA-256 | `fadb4402f0a7c286945fab5f1d429113063200532e3936f47f0f8ed555a0442b` |
| Git runtime-safety pin | `ff7973328184df73b31c4d8d27adeee5d83620c9` |

Recording all strategy/runtime pins exactly defines what is under test. A change
to any pinned strategy/runtime input ends the run unless the change is explicitly
excluded by the pin definitions below.

**Git runtime-safety pin.** This is the most recent commit that changed any of
the enumerated runtime-safety paths, not repository HEAD. Documentation-only
commits may be layered above it without invalidating this pin, provided none of
the enumerated runtime-safety paths change.

Compute it with:

```bash
git log -1 --format=%H -- \
  bridge.py guard.py monitor.py ibkr_operator.py \
  strategy_v1_1_core.py strategy_v1_1_advisory.py
```

If this command returns a different commit during the run, the runtime-safety
baseline has changed and the run ends.

**YAML configuration pin.** The YAML pin is computed after normalizing only the
operational `enforced` boolean to `false`. This permits the documented
`false → true → false` order-enablement cycle without changing the strategy/risk
configuration under test. No other YAML field, comment, mapping, limit, allowlist,
sector assignment, or byte content is excluded from the pin.

The normalized pin is computed by replacing exactly one `enforced: true|false`
value with `enforced: false` before SHA-256 hashing. If zero or more than one
`enforced` field is found, verification fails closed.

Any change that causes the normalized SHA-256 to differ from the §2 pin ends the run. 

## 3. Expected observations — YOUR PRIOR, WRITTEN BEFORE THE RUN

State each as a **range**, not a point. A range you would be surprised to fall outside.

| # | Quantity | Your expected range | Basis for the estimate |
|---|---|---|---|
| 3.1 | Median slippage vs entry reference (bps) | `5-15` | Observed bid-ask spread on the allowlist during RTH, not on hope |
| 3.2 | Worst-case single-trade slippage (bps) | `75-250` | Widest spread seen outside the blackout windows |
| 3.3 | Share of trades where the **risk** cap binds (vs notional) | `0-10` % | §4.8 — depends on whether ATR stops exceed the 5% floor for your names |
| 3.4 | `RISK_ON` frequency over the window | `55-75` % | SPY vs its 200d SMA and 12m momentum over comparable historical periods |
| 3.5 | Median `gross_scalar` | `0.85-1.00` | `16% ÷ realised SPY vol`, clamped to `[0.25, 1.00]`; scalar = 1.0 when the unclamped ratio is ≥1.0 |
| 3.6 | Trades reaching preflight per week | `2-6` | Signal stack: 2-of-4, RS top-half, regime, Gate I. Gate D caps at 2/day |
| 3.7 | Share of cycles ending `NO_TRADE` | `90-98` % | A high number is not failure — it is the filters working |
| 3.8 | Gate I rejections over the window | `0-2` | Zero would mean the sector cap never bound; that is informative either way |
| 3.9 | Data-quality failures per week | `0-5` | §4.10 thresholds, 23 series fetched per cycle |

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
| Slippage exceeds 3.2 | `Investigate execution quality first: reference-price timing, bid-ask spread, order type, market-data freshness, and concentration by symbol/time of day. Do not change strategy-selection parameters based on slippage. If a reproducible execution defect is identified, fix that defect and restart the validation window; otherwise record the miss and make no strategy revision.` |
| `RISK_ON` frequency far outside 3.4 | `Verify the SPY input series, 200-day SMA calculation, 12-month momentum calculation, and regime classification implementation. Do not tune the conventional regime parameters to fit this single window. If implementation/data are correct, record the prior mismatch and change nothing.` |
| Trade frequency far below 3.6 | `Measure which eligibility stage most frequently prevents proposals from reaching preflight (signal alignment, RS eligibility, regime state, Gate I, or another existing gate). Investigate the dominant blocker first and do not loosen multiple filters together. Any proposed strategy-rule change must fit the one-revision budget and requires a fresh validation window after the revision.` |
| Data-quality failures exceed 3.9 | `Identify the failing series/provider/path and determine whether required strategy inputs were missing, stale, malformed, or incomplete. If failures compromise a cycle's required inputs, treat that cycle as invalid evidence. Fix any reproducible data-path defect and restart the validation window if the run's plumbing claims can no longer be evaluated cleanly; do not weaken data-quality thresholds merely to reduce failure counts.` |
| Gate I never binds | `Record that Gate I was not exercised naturally during this window. Do not remove or loosen the sector cap solely because it was inert. Exercise the Gate I falsifier separately under a controlled validation scenario if needed to satisfy the requirement that every §10.1 check be positively exercised.` |
| Nothing unexpected happens | `Complete the full minimum validation window and ensure every F1–F15 plumbing check has been positively exercised at least once. If all falsifiers remain unrefuted, evaluate the next governance/promotion step using the pre-registered engineering evidence only; do not use paper P&L, win rate, Sharpe, or largest winner/loser as promotion evidence.` |

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
