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
| Proposal version | `0.4` |
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
| Gate I | Sector concentration cap, max **1** position per sector (11 sector groups) |
| Leverage | Formally rejected in all forms, including instrument-embedded |
| Unchanged | Sizing formula, `calc_stop`, all YAML risk ceilings, all CLAUDE.md §3 invariants |

**Design review outcome (2026-07-27) — 6 defects found and corrected in v0.2:**

| # | Defect | Resolution |
|---|---|---|
| 1 | Draft claimed a 6-position maximum, which is wrong for the same reason v1.0.0's "2" is wrong — risk-capped positions are smaller than 5%, so more fit inside 30% | Position count declared **unconstrained**; Gates B and F bound total risk |
| 2 | `portfolio_vol_target_pct: 12` was mislabeled (portfolio tops out near 6.6% vol) and permanently binding (12/16 ≈ 0.75 in calm markets) | Renamed `vol_reference_pct`, set to **16%** — dormant in calm, responsive in stress |
| 3 | No data-quality thresholds for the new signals; regime gate needs 252 bars but `fetch_bars` defaults to `"30 D"` | Added §4.10 with thresholds and fail-safe rules (missing regime data → `RISK_OFF`, not `RISK_ON`) |
| 4 | No transition rule for positions held at activation | Added §6.2 — grandfathered, but count toward Gate F and Gate I |
| 5 | Implementation plan omitted the operator CLI checkpoint command required by convention | Added §9.6. Was blocked pending `main()` de-duplication; **that blocker is now resolved** (see §5) |
| 6 | This changelog file did not exist despite being referenced | Created (this file) |

**Decision 11.3 — final allowlist (2026-08-01):** keep all 22 names, tighten Gate I from
2 to **1 position per sector**. Momentum clusters by sector, so a cap of 2 would let the
relative-strength filter fill two slots with a single bet — the universe contains four
near-duplicate pairs (NVDA/AMD ~0.80, META/GOOGL ~0.70, JPM/BAC ~0.80, XOM/CVX ~0.85).
No substitutions: keeping both members of each pair preserves ranker optionality while the
cap ensures only one is held.

**Breadth claim corrected (2026-08-01).** Proposal versions 0.1–0.3 asserted that 22 names
yields ~6.5 independent bets and a **2.24×** information-ratio improvement. Those figures do
not survive `N_eff = n / (1 + (n−1)·ρ̄)` and overstated the gain by roughly 80%.

| Component | Correlation basis | v1.0.0 `N_eff` | v1.1 `N_eff` | Relative IR |
|---|---|---|---|---|
| Directional (long-only beta) | raw returns | 1.36 | 2.11 | **1.24×** |
| Selection (cross-sectional RS) | beta-residual | 1.82 | 4.23 | **1.52×** |

The correct conclusion is that the allowlist expansion buys **selection breadth, not
diversification of market risk**. Market risk is controlled by the regime gate and the
inverse-vol scalar. The expansion remains worth making, for a different reason than
originally stated. All correlations are reference estimates pending recalculation from
bridge `market/bars`.

**Promotion blockers remaining:**

1. Open decisions 11.5 (MSTR/BTC) and 11.6 (definition of "learning"). **11.1 and 11.3 resolved 2026-08-01**; 11.2 and 11.4 resolved at design review.
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
| `V1_DEFECT_H4_1_TENSION` | `strategy_v1.md` §2 vs §3 | §2 lists non-leveraged US-listed ETFs as an allowed instrument type while §3 hard-blocks US-domiciled ETFs for BUY. §3 is operative, and under PRIIPs §2's line can never become true for this account. | **Resolved in principle 2026-08-01** — §2 line to be removed at v1.1.0 promotion (§11.1.2) |
| `V1_DEFECT_BREADTH` | `strategy_v1.md` §2 | A 4-symbol allowlist of correlated mega-cap tech names provides ~1.3 independent bets. Design limitation, not an error. | v1.1.0 |

---

## 5. Infrastructure Fixes Supporting Phase 19

Not strategy changes. Recorded here because Phase 19 work depends on them.

### 2026-08-01 — `ibkr_operator.py` `main()` de-duplication

`ibkr_operator.py` defined `main()` twice, at lines 49762 and 52332. Python binds
the later definition, so the first was unreachable — along with a repeated
section header and three other shadowed definitions.

| Item | Detail |
|---|---|
| Removed | Section header, `_PHASE18B_DIAGNOSIS`, `_PHASE18B_CHECKPOINT_SCRIPT`, `_phase18b_no_go`, a 32-line stub of `_run_level1_data_schema_provider_governance_checkpoint`, and the shadowed `main()` |
| Lines removed | **1,800** (57,095 → 55,295) |
| Commands in dead `main()` | 195 — a **strict subset** of the live `main()`'s 205 |
| Commands lost | **None** |

**Why it was safe:** the removed code was unreachable, so deleting it cannot change
runtime behavior. This was confirmed rather than assumed — `--help` output is
byte-identical before and after, the 205-command list is unchanged, duplicated
top-level names went 3 → 0, and `phase18a`, `phase18b`, and `phase18r1` all still
execute successfully.

**Root cause:** a merge appended a newer `main()` instead of replacing the older
one. The live `_run_level1_data_schema_provider_governance_checkpoint` (341 lines)
implements the checkpoint inline; the dead stub (32 lines) shelled out to an
external script via `_PHASE18B_CHECKPOINT_SCRIPT`, which had no other consumer.

**Unblocks:** the `phase19a` operator CLI checkpoint command (proposal §9.6).

**Regression guards added** in `tests/test_phase19a_strategy_v1_1_proposal_governance.py`:
one test asserts no duplicated top-level definitions exist in `ibkr_operator.py`,
and another asserts the manifest's record of this defect matches the file's actual
state in both directions.

### 2026-08-01 — H4.1 blocklist moved to `regulatory baseline | YAML`

Closes an H2 single-source-of-truth violation. CLAUDE.md §5 states "no hardcoded
duplicates exist" and that all parameters are read from the YAML at enforcement
time, but `guard.py` held `_US_ETF_BLOCKLIST` as a hardcoded 39-symbol set, so
changing it required a Tier-1 code edit.

**Tier 1 change to `guard.py`** (safety-critical per CLAUDE.md §6), approved by
Chris 2026-08-01.

| Aspect | Behavior |
|---|---|
| Effective blocklist | `_US_ETF_REGULATORY_BASELINE \| yaml.us_etf_blocklist.symbols` |
| YAML may add symbols | **Yes** |
| YAML may remove symbols | **No — by design** |
| YAML key required | **No** — a missing section can never stop the bridge starting |
| Absent / empty / malformed YAML | Resolves to the baseline alone, never to an empty set |
| Legacy call signature | Preserved — `_reject_us_domiciled_etf(symbol)` still works |
| Check ordering | Unchanged — rules load lazily inside the function, so the ETF check still runs before `load_rules()` |

**Why the floor stays in code.** A pure YAML replacement would create a fail-open
path: deleting one line would silently legalize an instrument the account is not
permitted to hold. PRIIPs is law, not a risk preference, so the baseline is not a
tunable. The YAML is now the sole source for the *mutable* part — extensions —
which is the part H2 is actually about.

Eight malformation shapes are tested to confirm none can weaken the floor:
section absent, null, empty; list empty, null; section wrong type; list wrong
type; entries wrong type. Covered by `tests/test_us_etf_blocklist_source.py`
(53 tests).

### 2026-08-01 — safety-invariant fix in `scripts/`

`scripts/gen_strategy_v1_1_manifest.py`, added earlier the same day, embedded the
literal string `/etc/ibkr-bridge/h1_token` inside a prose "explicit non-actions"
entry. This violated invariant T7
(`test_ci_invariant_assertions.py::test_no_h1_token_file_read_in_scripts`), which
forbids any script except `ibkr-trade-window` from referencing that path.

Fixed by rewording the entry to "the root-owned H1 token file", preserving meaning
without embedding the path. The invariant test was **not** weakened and the script
was **not** added to its allowlist — the test is a genuine safety control and the
generator had no legitimate need for the literal path.

---

## 6. Related Documents

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
