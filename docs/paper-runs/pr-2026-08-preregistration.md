# Paper Run Pre-Registration — `pr-2026-08`

> **Status:** DRAFT until sealed. Sealed documents must not be amended.
> **Governing sections:** proposal §10.4 (protocol), §10.1 (falsifiers), §11.6 (rationale).
> **Created:** 2026-08-10
> **Sealed:** not yet
>
> Run ID `pr-2026-08` is a placeholder Werner picked to name this file — rename the
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
| Run ID | `pr-2026-08` — rename if you'd rather |
| Start date | `<<FILL IN — your call; see note below>>` |
| Minimum window | 60 trading days, or until every §10.1 check has been exercised at least once — whichever is **longer** (§10.5) |
| Planned end date | `<<FILL IN — start date + ~60 trading days, adjust for your calendar>>` |
| Operator | Chris |

**Note on start date:** two things should be true before this window opens, neither of
which this document can verify for you — (1) the Gate I wiring
(`phase19-b4-gate-i-guard-wiring`, commit `b712f71`, tag `phase19b4_gate_i_chris_approved`)
is actually merged to `master` and **deployed to the live bridge host**
(`~/agents/ibkr-bridge/guard.py`) — a git tag on GitHub does not deploy anything by
itself; (2) `paper-trading-rules.yaml` on the bridge host still matches what's pinned in
§2 below. Falsifier F2 (Gate I) can't be meaningfully exercised until the deployed
`guard.py` actually contains it.

## 2. Strategy version under test

| Field | Value |
|---|---|
| Strategy version | v1.1.0 *(not yet "active" per the 19A manifest — this run is what would produce the evidence to promote it)* |
| Proposal version | 0.9 |
| Manifest `deterministic_manifest_hash` | `33bfa9f8ababd4153e7f1ebc0ece0e93a0aba719cf470977514420682fe2ef62` |
| `paper-trading-rules.yaml` SHA-256 | `<<FILL IN — run `sha256sum` on the live file yourself at deploy time>>` |
| Git commit | `b712f71e70d7a824e54b056281b08b3ff46ea2db` *(on `phase19-b4-gate-i-guard-wiring` — update this if it gets merged/rebased before deploy; it must match what's actually on the bridge host at run start, not what's on GitHub)* |

Recording all five pins exactly what was under test. If any changes mid-run, the run
ends and a new one begins.

**On the YAML hash specifically:** an earlier hash was captured mid-edit, before the
allowlist/`symbol_sectors`/`max_positions_per_sector` corrections landed — using it here
would pin the wrong file. Get a fresh one from the live host once everything above is
confirmed deployed, not from anything captured earlier in this conversation.

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
