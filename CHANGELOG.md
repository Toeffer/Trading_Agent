# CHANGELOG — OpenClaw / Werner / IBKR Bridge

History, order records, and superseded decisions. **`CLAUDE.md` holds no history** — when
a fact there changes, its old form lands here with a date. Append-only.

> Reconstructed 2026-06-09 from the prior monolithic CLAUDE.md. Phase boundaries are
> preserved; exact per-phase dates were not all recorded in the source and are marked
> where uncertain. Items needing live confirmation are collected in **§ Verification Queue**.

---

## 2026-06-18 — Step 15C: Bridge Liveness / Load-Shed Hardening (v1→v2→v3)

### Pre-fix OOM timeline (failure evidence)

All OOM kills were systemd-managed events where the bridge process was selected by
the kernel OOM killer:

| Timestamp (UTC) | Trigger | Root cause |
|---|---|---|
| 07:39:08 | Endpoint storm (8 HTTP calls × concurrent gates) | No snapshot cache; each call was independent |
| 09:35:33 | Runtime gate loop | Snapshot `_build_snapshot()` called `reconcile_snapshot()` (5 large JSON files) + `_check_liveness()` (subprocess forks) |
| 09:46:30 | Runtime gate loop | Same — snapshot amplified load, reconciliation allocated per-call |
| 10:01:31 | Runtime gate loop | v2 didn't fix it: `_build_snapshot` was declared lightweight but still spawned subprocesses |
| 10:52:18 | Live stress `test_08` | v2 `_check_liveness()` spawned `systemctl show` + `journalctl` — fork under memory pressure → OOM |
| 12:34:58 | Runtime gate loop | v2 code still had subprocess forks in liveness; gates 2/3 failed because bridge was gone |

Each kill: `Main process exited, code=killed, status=9/KILL`, `Failed with result 'oom-kill'`.

### v1 (initial)

Added snapshot cache with 5s TTL, `/snapshot` endpoint, `/monitor/liveness` endpoint,
fast-fail `/positions` and `/account`. Snapshot used `_build_snapshot()` which called
`reconcile_snapshot()` (5 large JSON reads) and `_check_liveness()` (systemctl/journalctl
subprocesses). This **amplified** memory load under concurrent calls rather than reducing it.

### v2 (lightweight snapshot + cached liveness)

Rewrote `_build_snapshot_lightweight()` to remove reconciliation and subprocess calls.
Added separate `_liveness_cache` with 60s TTL. Increased snapshot cache to 30s TTL.
Made `/positions`/`/account` immediate fast-fail (HTTP 200, `ok=False`).
Reconciliation downgraded to HOLD when IBKR disconnected.

**v2 still OOM'd** because `_check_liveness()` spawned `systemctl show` and `journalctl`
subprocesses — each a `fork()` of the Python process. Under memory pressure, fork
duplicates page tables and triggers OOM. The 30-min journal scan was especially expensive.

### v3 (zero-fork liveness + variable fixes) — ACCEPTED

- `_check_liveness()` rewritten to read `/proc/self/status` directly — zero subprocess forks.
- `/monitor/liveness` reads VmRSS/VmPeak/VmSize from proc; skips all systemctl/journalctl calls.
- Systemd-level OOM detection delegated to K17 check in `_collect_lightweight_evidence()`.
- Fixed `hold_reasons` double-initialization bug (line 2596 init wiped by line 2652 re-init).
- Fixed stray `liveness = None` before docstring (moved to proper scope).
- Added snapshot instrumentation: `cache_hit`, `build_ms`, `cache_age_seconds`, `in_flight_collapsed`.
- `test_08` asserts 4+ cache hits across 5 repeated calls.
- `test_09` verifies `run_kpi()` returns structured NO-GO/HOLD when bridge is dead.

**Acceptance** (from systemd restart 2026-06-18 18:14:04):
- 3 full runtime gates: Doctor PASS(10/10), KPI HOLD, Rehearsal HOLD, Candidate HOLD
- Journal: 0 OOM/killed/Failed with result/address already in use since restart
- Bridge RSS: 151MB stable, MemoryPeak 257MB (well under 2500M limit)
- 32 CI tests pass, 9 live stress tests pass
- `IBKR_ALLOW_ORDERS=false`, `rules.enforced=false`

---

## 2026-06-17 — Step 15B: OOM + trade_count_mismatch repair

**OOM fix:** Raised `MemoryMax` from 2000M → 2500M in `systemd/ibkr-bridge.service`
and `/etc/systemd/system/ibkr-bridge.service`. The bridge was intermittently OOM-killed
under memory pressure from uvicorn worker respawns. Host has 7872MB total / ~6GB available;
2500M is a safe envelope. `MemorySwapMax=0` and `OOMPolicy=stop` retained (fail-closed).
No `MemoryHigh` (throttling previously caused active-but-unresponsive behavior).

**trade_count_mismatch fix:** `guard.py:_rollover_guard_state()` excluded only
`order_id ∈ {12345, 99999}` from daily trade count restoration. The bridge's startup
self-test writes events with `order_id=1001`, `permId=5001`, and `approval_id=test-*`.
These test artifacts were NOT excluded, inflating `daily_trade_count` to 2-3 on every
bridge restart, triggering a persistent `trade_count_mismatch` alert → KPI NO-GO.

Added exclusions for:
- `order_id` 1001 (test-bracket shared fake order_id)
- `permId` 5001 (test-bracket shared fake IBKR permId)
- Any `approval_id` starting with `"test-"` (test-bracket, test-double, test-killswitch, test-failclosed)

**Repair:** `ibkr-operator kpi-repair --live` corrected `daily_trade_count` 3→0 and
cleared 58 orphan approvals. Requires bridge restart (`sudo systemctl restart`) for
new `guard.py` to take effect in the running process.

---

## Order history (paper account DUQ542875) — Phase H3 authoritative ledger

> **H3 reconstructed 2026-06-10** from `guard-events.jsonl` `order_submitted` events
> filtered to `ibkr_metadata.status=Filled`. Non-filled submissions excluded.

| Date | Symbol | Action | Qty | Fill | ib_oid | permId | Approval (short) |
|---|---:|---:|---:|---:|---:|:---|
| 2026-06-03 | AAPL | SELL | 1 | $314.50 | 36 | 551562267 | `aprv_519fb1f8` |
| 2026-06-03 | AAPL | BUY | 1 | $314.28 | 8 | 551562294 | `aprv_305f24cc` |
| 2026-06-04 | AAPL | SELL | 1 | $310.98 | 16 | 1657699826 | `aprv_c871f6b7` |
| 2026-06-08 | AAPL | BUY | 1 | $310.34 | 24 | 75943855 | `aprv_b81da452` |
| 2026-06-09 | META | BUY | 72 | $596.28 | 24 | 71835605 | `aprv_3a934a5c` |
| 2026-06-11 | META | SELL | 72 | PENDING | — | — | (Phase 6A EXIT — Chris approved) |

> **Non-filled submissions (excluded from ledger):**
> - AAPL SELL order 24 (permId 1529342545, 2026-06-09) — Submitted, 0 filled.
>   The ~$300.30 reference price was an estimate, not a fill.
> - AAPL SELL order 16 (permId 2055135190, 2026-06-04) — PreSubmitted, 0 filled.
>   Retried as permId 1657699826 which filled.

> **QQQ cancellation remnants:** 5 unconfirmed orders (IDs 40, 46, 52, 60, 71) across
> 2 approval attempts — all KID/PRIIPs blocks. None reached IBKR; none increment
> `daily_trade_count`. The prior CHANGELOG entry "2 cancelled, IDs 52/60/71" was
> doubly incorrect: actual count is 5, not 2 or 3.

> **ID type map (H3):**
> - `approval_id` — guard-internal UUID linking preflight → approve → submit
> - `local_order_id` — ephemeral integer assigned by bridge per submit call
> - `ib_oid` — IBKR internal order ID (reused across days/symbols — normal)
> - `permId` — IBKR permanent order ID (globally unique per order)

> **Gate D semantics (H3):** `daily_trade_count` increments only on IBKR-acknowledged
> fills. Rejected attempts, blocked submits, and unconfirmed (ACK_TIMEOUT) orders do
> NOT increment the count. Gate D uses `current >= max_trades` so the (N+1)th attempt
> is always blocked once the cap is reached.

Known test artifacts (order_ids 12345, 99999; approvals `aprv_noexec`, `aprv_7`):
excluded from ledger — no ibkr_metadata.

---

## Superseded decisions

- **Risk limits.** Earlier drafts referenced 25% per symbol, 60% total exposure, 2.5×ATR
  stops, and 1% max risk. **Superseded by v1.3-draft:** 5% notional, 2% risk, 30% total
  exposure, 2×ATR in the long-stop formula.
- **Allowlist.** Was AAPL/SPY/QQQ. **2026-06-09:** SPY and QQQ removed (KID/PRIIPs blocks
  US-domiciled ETFs on this EU paper account); META, NVDA, AMD added. `guard.py`
  `ALLOWED_SYMBOLS` synced to YAML.
- **SELL.** Originally "BUY only." **Phase 2G:** extended to close-only SELL (Gate G).
- **Account-summary bug.** `ibkr_account` once returned `values_count: 0`; fixed — now
  returns the full values array (121 values) with required summary fields.
- **Crypto/Kraken/grid/regime.** Entire prior project — archived and disabled.

---

## Phase ledger

### Phase 1 — Read-only setup & planning — COMPLETE
Bridge health, account summary, positions, contract lookup, delayed quotes, 30-day daily
bars, ATR(14)/20-day-low/swing-low computation, and concrete sizing formulas all verified.
Audit PASSED. Watchlist conIds captured (AAPL 265598, MSFT 272093, SPY 756733, QQQ
320227571, VOO 136155102, IVV 8991352, VTI 12340041).

Verified account state (€-base, EUR/USD 1.00 at capture): NetLiquidation €1,000,000;
TotalCashValue €1,000,000; AvailableFunds €1,000,000; BuyingPower €6,666,666.67;
AccountReady true.

Validated read-only sizing baseline (notional cap binding for all three; 2×ATR was the
final stop throughout; −5% floor not binding; totals inside the 30% / aggregate-risk caps):

| Symbol | Ask | Stop | Dist | Shares | Notional | Risk | Binding |
|---|---:|---:|---:|---:|---:|---:|---|
| AAPL | $307.00 | $296.56 | $10.44 / −3.4% | 162 | $49,734 / 4.97% | $1,691 / 0.17% | notional |
| SPY | $757.81 | $744.19 | $13.62 / −1.8% | 65 | $49,258 / 4.93% | $885 / 0.09% | notional |
| QQQ | $742.54 | $720.78 | $21.76 / −2.9% | 67 | $49,750 / 4.98% | $1,458 / 0.15% | notional |
| Total | | | | | $148,742 / 14.87% | $4,035 / 0.40% | |

*(SPY/QQQ later removed from the allowlist — see Superseded decisions.)*

### Phase 2 — Guarded order pipeline
- **2 / 2A–2B** Preflight design + implementation. `/order/preflight` active,
  validation-only. 12/12 safety checks passed. Strict mode; no executable payloads.
- **2C** Approval records: lifecycle + `POST /order/approve` (approve/deny by
  `approval_id`); live chain verified preflight→approve→confirm.
- **2D** `POST /order/submit` implemented, tested, live-executed.
- **2E** Persistence: `submitted-approvals.json` + startup reconciliation.
- **2F** Monitoring: 5 GET endpoints (`/monitor/health`, `/reconciliation`,
  `/events?type=&since=`, `/alerts`, `/positions/drift`); alert classification
  (`source`/`historical`/`requires_action`); drift detection. All GET-only, read-only,
  work without an IBKR connection.
- **2G** Close-only SELL (Gate G: position exists, qty ≤ position, no shorts; SELL runs
  A/D/E/G, skips B/C/F) **+ ack-hardening**: `_internal_place_order` requires IBKR ack
  before `success=True`; polls ≤15 s on `orderStatus.status` / `openTrades` / `trades` /
  `fills`; accepts Submitted/PreSubmitted/Filled/PartiallyFilled; `IBKR_ACK_TIMEOUT` on
  no ack → writes `order_unconfirmed`, does **not** increment `daily_trade_count`; on
  success captures `ib_order_id`/`permId`/`status`/`filled`/`remaining`/`avgFillPrice`.
  Startup reconciliation auto-corrects legacy unconfirmed orders; `position_drift_check()`
  excludes unconfirmed orders.

### Phase 3 — Hardening, audit, recovery, status
*(Per-phase regression totals as recorded; cumulative reached 138/138.)*
- **3E** `GET /readiness` (GO/NO-GO) + RTH calendar check.
- **3F** 39/39 regression (7 RTH + 10 readiness + 22 existing).
- **3G** Startup safety: 10 checks on module load, logged event, wired to `/health` +
  `/readiness` (46/46).
- **3H** `GET /audit/bundle` + offline `bundle_audit.py` (4 files + 5 endpoints + code
  hashes; 5 tests).
- **3I** `GET /audit/verify` — 7 consistency checks; CLI `--verify` (7 tests).
- **3J** Release tagging: `GET /audit/release` + `/release/latest`; CLI `--tag`;
  provenance with source hashes (7 tests).
- **3K** Git init; signed tags `phase3j_verified`, `phase3k_git_init`; git provenance in
  release tags (4 tests).
- **3L** Restore drill (clone + rebuild + restore): 3 tests, 67/67.
- **3M** Disaster-recovery runbook: 12-step checklist + one-liner; failure modes documented.
- **3N** `POST /connect` validation: 7 tests, 81/81; graceful gateway-down handling.
- **3O** `GET /status` dashboard (aggregates health/readiness/git/audit/release/monitoring):
  7 tests.
- **3P** Status hardening: resilient under partial failures, per-section status (7 tests).
- **3Q** `ibkr-status` CLI (bridge + fallback modes): 7 tests, 95/95.
- **3R** Model-routing safety policy: 3 tiers, edit/state/bridge guards, escalation rules.
- **3S** Policy surfaced in `ibkr-status` (Model Policy section), `CLAUDE.md` identity,
  runbook Step 0: 95/95.
- **3U** `/order/dry-run` harness: `dry_run_order` event, drift integration: 7 tests, 102/102.
- **3V** Dry-run isolation: `include_dry_run=False` default, `dry_run_preview` in drift,
  `simulation_evidence` in bundle: 7 tests, 109/109.
- **3W** Dry-run scenario library: `dry_run_scenarios.py`, 10 named scenarios, GET list +
  POST execute: 14 tests, 123/123.
- **3X** Scenario report: `GET /report` + `/report/all`: 6 tests, 129/129.
- **3Y** Dry-run checkpoint: `/audit/release` includes `dry_run_simulation`: 9 tests, 138/138.

> Phase-letter note: within Phase 3 there is no recorded 3T or 3Z. The 3K–3Y track ran on
> `bridge.py`/`guard.py` (above). The 4-series (below) is a separate component — the
> `ibkr-operator` CLI — so the two share the 3H–3J audit tags and then diverge. 4A is not
> recorded; 5A is not separately described (5B is the first documented Phase-5 sub-phase).

### Phase 4 — `ibkr-operator` operator CLI (read-only)
Source: RUNBOOK tag timeline. A separate read-only operator tool wrapping the bridge, with
its own AST safety checks (no `placeOrder`/`cancelOrder`/`/order`, no guard-state mutation,
protected files never touched, secrets redacted on export, pruning opt-in via explicit flags).
- **4B** `phase4b_operator_checklist` — daily checklist CLI (auto-detects state).
- **4C** `phase4c_checklist_release_evidence` — checklist evidence in release metadata.
- **4D** `phase4d_maintenance_prune` — audit/release maintenance & pruning (`--dry-run` default-safe).
- **4E** `phase4e_resource_guard` — resource health monitoring.
- **4F** `phase4f_daily_report` — consolidated daily report.
- **4G** `phase4g_daily_report_evidence` — daily-report snapshot in audit bundle.
- **4H** `phase4h_operator_export` — operator evidence export.
- **4I** `phase4i_export_retention_verify` — export retention & verify.
- **4J** `phase4j_help_runbook` — help output & runbook.
- **4K** `phase4k_doctor_command` — operator self-test / doctor.
- **4L** `phase4l_operator_release_freeze` — release freeze / full CLI evidence snapshot.

### Phase 5B — Hermes Advisory Guard (5B.0) & Invocation Adapter (5B.1)
Source: RUNBOOK + `~/.openclaw/memory/hermes-advisory-guard-policy.md`. Hermes is
**advisory-only**: it analyzes markets, ranks candidates, produces theses, calculates risk,
and drafts proposals via a mandatory 14-field template; it writes post-trade learning notes
only on Chris's explicit request. Hermes must never enable/submit/approve orders, call IBKR
or `/order*` directly, edit `.env`/rules/guard-state/approvals, or bypass Werner /
`ibkr-operator` / the bridge/guard. Every proposal requires Chris approval.

Phase 5 pilot advisory rails (the envelope Hermes proposes *within*): max position 5% Net
Liq, max exposure 25%, max risk/trade 0.25%, max 2 trades/day and 5/week, no trade without a
stop or while drift/open-order/live-alert is present, NO TRADE at daily loss ≥1% or weekly
≥3%. **These diverge from the guard's v1.3-draft caps — see Verification Queue item 6.**

### Phase H4.1 — Operational Hygiene — COMPLETE (2026-06-11)
- Stale guard-event reconciliation: 2 stale events (>48h) reconciled against IBKR live
  orders (ibkr_live_count=0). AAPL SELL 24/perm 1529342545 → NotFoundInIBKR; META BUY
  24/perm 71835605 → Filled (position confirmed). Both appended to
  `manual-order-reconciliations.jsonl` as manual_terminal.
- trade_date rollover: guard-state.json trade_date rolled to 2026-06-11,
  day_start_nl_eur captured at 998,133.
- Stop-breach advisory rule: if stop_breach==true, suppress new BUY proposals; only HOLD
  or EXIT may be proposed. Applied to META stop-breach (stop $579.22, current $559.48).

### Phase 6A — META Stop-Breach Review — COMPLETE (2026-06-11)
- Structured stop-breach response process established: Step 0 breach confirmation, Step 1
  artifacts-only thesis reconstruction, Step 2 current state, Step 3 Hermes adversarial
  review (steelmanned EXIT/HOLD, blind re-underwrite, decision-quality vs outcome-quality),
  Step 4 exactly one recommendation (EXIT default), Step 5 trade journal.
- META breach confirmed: $559.48 below recorded stop ($579.22) and -5% floor ($566.47);
  -10% absolute floor ($536.66) remained intact and anchored the "risk if held" vs
  "risk if exited" decision calculus. 5 straight red candles. AI capex quantified at $125-145B.
- Hermes adversarial review: strongest case for EXIT (honor pre-committed stop regime);
  case for HOLD (stop at 0.91×ATR was tight, ordinary volatility); blind re-underwrite
  returned NO (would not buy today); "holding is largely not different from buying."
- ⚠️ Hermes was invoked as sessions_spawn subagent (deepseek-v4-pro), NOT via Codex CLI
  with its configured GPT-5.5 model. Chris noted: for future, invoke Hermes via default
  model path (Codex/GPT-5.5). Noted as process gap.
- Recommendation: EXIT (Chris approved). Execution pending.
- Trade journal: `~/.openclaw/memory/trade-journal/META-2026-06-09.md`
- 5 process gaps logged (thesis fields unrecorded: reason to trade, reason not to trade,
  sizing rationale narrative, market context, Hermes session reference).
- Lesson: thesis archiving is mandatory — approval record schema should include a
  `proposal_rationale` field from Hermes proposal.

### Phase 5C — Dual decision cycles — COMPLETE (2026-06-09)
- Two live paper cycles: AAPL SELL filled (close-only) + META BUY 72 @ $596.28 filled;
  QQQ BUY blocked by KID/PRIIPs. Both kill switches rolled back after each cycle.
- Mandatory position-sizing-rationale section added to every proposal.
- Data-provenance policy: Hermes source-labeling, IBKR = truth.
- Allowlist updated to AAPL/META/NVDA/AMD (SPY/QQQ removed).

### Phase 19B — `strategy_v1_1_core.py` deterministic pure evaluation library (B1/B2)
- Chris added `strategy_v1_1_core.py` (Gate 0.1, HIQ-001–012 resolved 2026-08-01): a
  standalone, pure module (no network/filesystem/current-time/side effects) implementing
  regime state, realized-vol/gross-scalar, cross-sectional RS ranking, budget computation,
  and `gate_sector_concentration` (Gate I) — plus 257 B2 unit/golden-vector tests, all in
  commit `5dbc726`. `Execution: NONE` — not yet wired into `guard.py` or `bridge.py`;
  wiring is deferred to B4 (out of scope here).
- **Note — architecture diverges from `STRATEGY_V1_1_PROPOSAL_v0_1.md` §9.3/§9.4.** The
  proposal's original plan assigns this logic to `hermes_advisory.py` (Phase 19C) and a
  `guard.py`-resident `gate_sector_concentration` (Phase 19D, Tier 1). `strategy_v1_1_core.py`
  is a third, independent implementation of the same regime/vol/RS/Gate-I logic, built to
  the proposal's frozen 22-symbol/11-sector universe but not following its file layout.
  Both this module and the unmerged `phase19c-advisory-layer` branch (`hermes_advisory.py`
  + `guard.py` Gate I, commits `8609691`/`fd21617`/`16a1483`) existed unmerged and
  unreconciled at the same time.
- **Decision (2026-08-06, Chris — "as long as Hermes still works as a learning brain, you
  decide what's best"):** `strategy_v1_1_core.py` is canonical. It is pure (no network, no
  side effects), has a fuller reason-code inventory and tie-break spec, and — critically —
  never invokes Hermes or replaces its signal generation; it only validates Hermes's
  already-produced `signal_alignment` output (`validate_hermes_output`, HIQ-010) and
  computes portfolio-level scaffolding around it, so Hermes remains the sole "brain."
  `hermes_advisory.py` mixed network I/O (`fetch_reference_bars` calling `guard.py`'s
  `_bridge_post`) into the same functions it wanted tested deterministically, and its
  `guard.py` Gate I duplicate carries the harder Tier-1/git-tag + 19B-ordering hazard for
  no added benefit now that an equivalent gate exists in `strategy_v1_1_core.py`.
  `phase19c-advisory-layer` is **superseded — do not merge**; the branch is left pushed
  and unmodified for reference only. Any future wiring phase (B4) should call into
  `strategy_v1_1_core.py`'s pure functions from a thin, separately-tested I/O layer rather
  than reintroducing `hermes_advisory.py`'s design.
- **2026-08-06 fixes (this entry):** corrected a stale module docstring claiming
  `Tests: NOT AUTHORIZED (B2 separately gated)` while the same commit already contained
  and passed 257 B2 tests; registered all 7 new test files
  (`test_strategy_v1_1_core.py`, `test_phase19b_{budget,gate_i,golden_vectors,regime,
  rs_rank,vol_scalar}_unit.py`) in `scripts/run-ci-portable` — they existed but were never
  part of the curated CI gate, so the branch's prior green CI run did not actually exercise
  them.
- **2026-08-06 — `vol_reference_pct` recalibrated from real data, per Chris's request to
  fill the proposed YAML with the financially/scientifically best values.** §4.6.1
  instructs recomputing SPY's median 20-day annualized realized vol from ≥5 years of data
  and setting the constant to that measured median — not fitting it to P&L. Computed from
  FMP SPY daily history (2019-01-02 to 2026-08-06, 1,909 bars, not IBKR-sourced): median
  20d realized vol = 13.23% (full sample), 13.40% (last ~5y), 13.26% (excluding the 2020
  COVID tail) — consistent across all three windows. `advisory.vol_reference_pct` in the
  proposed YAML (`docs/strategy-proposals/PHASE19B_PROPOSED_YAML_CHANGES_v0_1.md`) is now
  `13`, down from the proposal's `16` placeholder (which was closer to the *mean*, pulled
  up by the 2020 tail, than the *median* the proposal specifies). This can only tighten
  the advisory-suggested exposure budget relative to the placeholder, never loosen it
  (design principle 1). `strategy_v1_1_core.py`'s own `DEFAULT_VOL_REFERENCE_PCT` module
  constant was deliberately **left at 16.0** — `TestComputeGrossScalar` /
  `TestGrossScalarExtended` in B2 hardcode numeric assertions built on that exact default,
  and HIQ-008 already specifies the value comes from advisory config at runtime, not the
  module fallback. Every other advisory parameter (200d SMA, 12mo momentum, 60d RS
  lookback, 0.25 floor, 0.5 top-fraction, 1-per-sector cap) is intentionally left at the
  proposal's conventional/field-standard value — design principle 4 forbids fitting them,
  and `max_positions_per_sector` is already a separately-resolved decision (§11.3).
  Full methodology and per-parameter rationale in the proposed-YAML doc.
- **2026-08-10 — Phase 19B confirmed APPLIED LIVE.** Chris edited
  `/home/chris/.openclaw/risk-rules/paper-trading-rules.yaml` himself; Werner walked
  through the diff but never wrote the file (invariant 6 held throughout — confirmed
  explicitly after Chris initially offered to have Werner perform the write directly,
  which was declined per CLAUDE.md §3's own bar against ad hoc verbal exceptions to a
  safety invariant). First attempt landed only the `advisory` section (with a mangled/
  mis-indented `min_symbol_bars_for_rs` field, corrected before saving); a follow-up
  check found the allowlist expansion, `symbol_sectors`, and `max_positions_per_sector`
  hadn't actually been applied despite an earlier walkthrough describing them — caught by
  cross-referencing section-header line numbers before assuming completion. Final
  verification, field-by-field, via Werner's read-only output: 22-symbol allowlist in
  spec order with updated rationale text; `symbol_sectors` — 22 entries, exact 1:1 match
  with the allowlist, 10 distinct sectors, no orphans; `max_positions_per_sector.value: 1`
  (labeled `9a`/`9b` to avoid colliding with the file's existing rule 10); `advisory` — all
  14 fields, correctly nested, `vol_reference_pct: 13`; NOTES line added;
  `yaml.safe_load()` parses cleanly; `/health` and `/readiness` unchanged in shape before
  and after (still `startup_safety: 11/11`, no drift, no new blocks) — the live edit had
  zero effect on bridge behavior, exactly as expected for a purely additive, not-yet-wired
  change. `docs/strategy-proposals/PHASE19B_PROPOSED_YAML_CHANGES_v0_1.md` updated to
  reflect applied status.

---

## Verification Queue (resolve against the live system)

0. ✅ **RESOLVED (H2): Risk-rails divergence.** Reading (A) confirmed — guard.py enforces
   the v1.3-draft YAML caps (2% risk, 30% exposure) as the hard ceiling; Hermes proposes
   inside a tighter advisory envelope (0.25% risk, 25% exposure, 5 trades/week). CLAUDE.md
   §5 now documents the two-tier model explicitly. See `CLAUDE.md §5 Two-Tier Risk Model`.
1. ✅ **RESOLVED (H3): AAPL close discrepancy.** The authoritative AAPL close is order 36
   @ $314.50 (2026-06-03, permId 551562267, status=Filled). Order 24 @ ~$300.30
   (2026-06-09, permId 1529342545) was Submitted but not filled — the price was an
   estimate, not a fill. Reconstructed ledger in § Order History above.
2. ✅ **RESOLVED (H3): QQQ remnant count.** The actual count is 5 unconfirmed orders
   (IDs 40, 46, 52, 60, 71) across 2 approval attempts. The prior note "2 cancelled"
   was doubly incorrect — it said 2 but listed 3 IDs, and the real count is 5. All five
   are KID/PRIIPs artifacts that never reached IBKR. See § Order History above.
3. **Model identity** — source listed `openrouter/deepseek/deepseek-v4-flash` as Tier 1
   (Strong); "flash" usually denotes a fast tier. Confirm the router resolves
   safety-critical edits to a genuine strong model.
4. **`/account/summary`** — source hedged "if present." Confirm whether the endpoint exists.
5. **MCP/OpenClaw path** — much of the read-only capability was verified via local server
   commands (`curl`/`systemctl`/`journalctl`/`py_compile`), not the MCP path. Re-verify
   MCP separately if strict evidence is needed.
6. **Hermes 14-field template** — RUNBOOK references a "mandatory 14-field template" for
   proposals; `CLAUDE.md §8` only requires a "position-sizing rationale" section. Confirm
   the 14 fields (likely in `hermes-advisory-guard-policy.md`) and reconcile the two.
7. **SPY in CLI help** — `hermes-proposal --help` may still print `--symbol SPY` as its
   example; SPY is off the allowlist. Update the CLI's example string if so.
8. **⏳ PROPOSAL: Stop-breach → default EXIT.** Phase 6A established that a confirmed
   stop breach triggers an automatic EXIT recommendation within 30 min of RTH. HOLD
   requires written Chris override (`STOP_OVERRIDE_REQUESTED`). Add this as a standing
   policy rule in `CLAUDE.md §3` and `paper-trading-rules.yaml` if Chris approves.
