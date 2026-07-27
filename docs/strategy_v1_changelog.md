# Strategy Changelog

> **Status:** Governance record.
> **Scope:** Version history for the canonical trading strategy.
> **Referenced by:** `docs/strategy_v1.md` §16 (Model / Versioning Discipline).
> **Created:** 2026-07-27

---

## 0. Purpose and Rules

This file is the version ledger for the canonical strategy document
(`docs/strategy_v1.md`). It was referenced by `strategy_v1.md` §16 and by
`STRATEGY_V1_1_PROPOSAL_v0_1.md` §14 before it existed; this file closes that
dangling reference.

Rules, per `strategy_v1.md` §16:

| Rule | Detail |
|---|---|
| Version format | `v<MAJOR>.<MINOR>.<PATCH>` (semantic versioning) |
| MAJOR bump | Governance boundary change (new asset class, autonomy level change) |
| MINOR bump | New signal, parameter change, new symbol added |
| PATCH bump | Clarification, typo fix, documentation improvement |
| Review gate | MINOR+ bumps require Chris's review before proposals may reference the new version |
| Rollback | Previous version remains in git history; revert by tag |

**No mutable state in this file.** Positions, fills, guard flags, and readiness
values are never recorded here — query the live system instead, per CLAUDE.md §0.

**Distinction from `CHANGELOG.md`.** The repository-level `CHANGELOG.md` records
the phase ledger, order history, and superseded decisions for the whole system.
This file records **only** versions of the canonical strategy document and the
proposals that target it.

---

## 1. Active Version

| Field | Value |
|---|---|
| Active strategy version | **`v1.0.0`** |
| Version ID | `strategy-v1-2026-07-09` |
| Document | `docs/strategy_v1.md` |
| Status | Advisory-only, Level 1, no order execution |
| Next review due | 2026-08-08 |

---

## 2. Version History

### v1.0.0 — 2026-07-09 — Active

Initial canonical strategy under Level 1 advisory-only governance. Supersedes
`docs/STRATEGY.md` as the pre-governance baseline.

| Area | Content |
|---|---|
| Allowlist | AAPL, META, NVDA, AMD |
| Instruments | US large-cap equities only; long-only |
| Excluded | Options, futures, forex, crypto, leveraged/inverse ETFs, penny stocks, non-US equities, short selling, US-domiciled ETFs for BUY (H4.1) |
| Session | RTH only, 15-minute open and close entry blackouts |
| Signals | 7 inputs; entry requires ≥2 of the first 4 to align; ATR(14) always required |
| Risk envelope | 5% notional per position, 2% risk per trade, 30% total exposure |
| Trade limits | 2 per day (Gate D) |
| Loss halts | −1% daily, −3% weekly (Gate E), close-only SELL exempt (P2b) |
| Stops | `max(entry − 2×ATR(14), swing low, 20-day low, entry × 0.95)`; mandatory broker-side child STP |

---

## 3. Proposals Targeting a Future Version

Proposals are **not** active strategy. They are listed here so the ledger shows
what is pending against which version.

### v1.1.0 — PROPOSED — not active

| Field | Value |
|---|---|
| Proposal | `docs/strategy-proposals/STRATEGY_V1_1_PROPOSAL_v0_1.md` |
| Proposal ID | `strategy_v1_1_proposal_v0_1` |
| Proposal version | `0.2` |
| Manifest | `docs/strategy-proposals/strategy_v1_1_proposal_v0_1.manifest.json` |
| Phase | 19A |
| Readiness | S0 |
| Execution scope | `NONE` |
| Design review | **COMPLETE** — 2026-07-27 |
| Promotion | **Blocked** — see below |

**Proposed changes:**

| Change | Detail |
|---|---|
| Allowlist breadth | 4 → 22 symbols across 10 GICS sectors |
| Regime gate | `RISK_ON` / `CAUTION` / `RISK_OFF` on a read-only SPY reference |
| Inverse-vol scalar | `clamp(vol_reference_pct / σ̂_ref, 0.25, 1.00)` applied to the advisory exposure budget |
| Cross-sectional filter | 60-day relative-strength top-half requirement |
| Gate I | Sector concentration cap, max 2 positions per sector |
| Leverage | Formally rejected in all forms, including instrument-embedded |
| Unchanged | Sizing formula, `calc_stop`, all YAML risk ceilings, all CLAUDE.md §3 invariants |

**Design review outcome (2026-07-27) — 6 defects found and corrected in v0.2:**

| # | Defect | Resolution |
|---|---|---|
| 1 | Draft claimed a 6-position maximum, which is wrong for the same reason v1.0.0's "2" is wrong — risk-capped positions are smaller than 5%, so more fit inside 30% | Position count declared **unconstrained**; Gates B and F bound total risk |
| 2 | `portfolio_vol_target_pct: 12` was mislabeled (portfolio tops out near 6.6% vol) and permanently binding (12/16 ≈ 0.75 in calm markets) | Renamed `vol_reference_pct`, set to **16%** — dormant in calm, responsive in stress |
| 3 | No data-quality thresholds for the new signals; regime gate needs 252 bars but `fetch_bars` defaults to `"30 D"` | Added §4.10 with thresholds and fail-safe rules (missing regime data → `RISK_OFF`, not `RISK_ON`) |
| 4 | No transition rule for positions held at activation | Added §6.2 — grandfathered, but count toward Gate F and Gate I |
| 5 | Implementation plan omitted the operator CLI checkpoint command required by convention | Added §9.6, blocked pending `main()` de-duplication in `ibkr_operator.py` |
| 6 | This changelog file did not exist despite being referenced | Created (this file) |

**Promotion blockers remaining:**

1. Open decisions 11.1 (H4.1 ETF BUY block), 11.3 (final allowlist), 11.5 (MSTR/BTC), 11.6 (definition of "learning")
2. Anti-overfit checks 2, 4, and 7 unmet — no out-of-sample or walk-forward evidence exists
3. Phases 19B–19E not started
4. Paper-run validation §10.1 not performed
5. `vol_reference_pct` still a reference estimate; requires recalibration from bridge `market/bars`

---

## 4. Known Defects in the Active Version

Recorded here rather than silently corrected, because `strategy_v1.md` is the
active governance document and changing it requires a version bump and review.

| ID | Location | Defect | Fix targeted at |
|---|---|---|---|
| `V1_DEFECT_POSITION_COUNT` | `strategy_v1.md` §8 | States "Maximum positions open simultaneously: 2 — *Implied by exposure cap + per-position limit*". The implication is invalid; no gate constrains position count. | v1.1.0 |
| `V1_DEFECT_H4_1_TENSION` | `strategy_v1.md` §2 vs §3 | §2 lists non-leveraged US-listed ETFs as an allowed instrument type while §3 hard-blocks US-domiciled ETFs for BUY. §3 is operative. | Open decision 11.1 |
| `V1_DEFECT_BREADTH` | `strategy_v1.md` §2 | A 4-symbol allowlist of correlated mega-cap tech names provides ~1.3 independent bets. Design limitation, not an error. | v1.1.0 |

---

## 5. Related Documents

| Path | Role |
|---|---|
| `docs/strategy_v1.md` | Active canonical strategy (v1.0.0) |
| `docs/STRATEGY.md` | Pre-governance baseline — superseded |
| `docs/strategy-proposals/STRATEGY_V1_1_PROPOSAL_v0_1.md` | v1.1 design proposal (PROPOSED) |
| `docs/strategy-proposals/MSTR_BTC_RESEARCH_PROPOSAL_v0_1.md` | MSTR/BTC research proposal (PROPOSED, S0) |
| `docs/AUTONOMY_CRITERIA.md` | Autonomy level gating |
| `docs/KPI_DASHBOARD.md` | Evidence and readiness dashboard |
| `CHANGELOG.md` | System-wide phase ledger |
| `CLAUDE.md` | Identity, safety invariants, architecture |
