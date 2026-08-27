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
- **2026-08-10 — Phase 19B YAML confirmed APPLIED LIVE.** Chris edited
  `/home/chris/.openclaw/risk-rules/paper-trading-rules.yaml` himself; Werner walked
  through the diff but never wrote the file (invariant 6 held throughout, including
  after Chris explicitly offered to have Werner perform the write directly, which was
  declined per §3's bar against ad hoc verbal exceptions to a safety invariant). Two
  real gaps caught during verification: a first save landed only the `advisory` section
  with a mangled/mis-indented `min_symbol_bars_for_rs` field (corrected before saving);
  a later save's walkthrough described all five changes as applied, but cross-referencing
  the file's section-header line numbers showed the allowlist expansion, `symbol_sectors`,
  and `max_positions_per_sector` hadn't actually landed. Final state verified
  field-by-field: 22-symbol allowlist, `symbol_sectors` 22/22 exact match across 10
  sectors, `max_positions_per_sector.value: 1`, `advisory` 14/14 fields with
  `vol_reference_pct: 13`, NOTES line added. `/health`/`/readiness` unchanged in shape
  before and after — zero effect on bridge behavior, as expected for an additive,
  not-yet-wired change at that point.

### Phase 19B/B4 — Gate I wired into `guard.py` (Tier 1, Chris-approved 2026-08-10)
- **Resolved the open "is Gate I a real gate or advisory-only" question**, delegated
  explicitly by Chris ("resolve the gate issue for me... afterwards handle guard.py").
  Not a new architectural call — the proposal's own §10.1 check #2 ("Gate I rejects 3rd
  same-sector position, 100% rejection") is a paper-run pass/fail criterion that cannot
  be satisfied unless something actually rejects the order at preflight. B3's
  `strategy_v1_1_advisory.py` computes the same sector-eligibility check but wraps every
  result `advisory_only: True, execution_authorized: False` by design — it structurally
  never blocks anything. So the real, order-rejecting gate has to live in `guard.py`,
  matching the original 19D template (§9.4) almost exactly.
- `guard.py` now imports `strategy_v1_1_core.gate_sector_concentration` directly (aliased
  `_core_gate_sector_concentration`) and adds a thin adapter,
  `guard.gate_sector_concentration(symbol, positions, rules)`, that extracts
  `symbol_sectors`/`max_positions_per_sector` from the rules dict, filters positions to
  currently-held (qty > 0) entries, and delegates — zero duplicate counting/precedence
  logic in `guard.py` (H2 invariant). Wired into `run_preflight`'s BUY branch as Gate I,
  right after Gate F (exposure), following §9.4's placement plan.
- **Fails closed on missing position data.** Unlike the pre-existing `gate_exposure` call
  (which runs with a hardcoded `[]` — a known, out-of-scope simplification), Gate I
  actually fetches live positions via `position_provider()` and rejects the whole
  preflight if that fails, returns `None`, or isn't a list — an empty-positions default
  would make the concentration cap unenforceable exactly when position data is least
  trustworthy.
- `load_rules()`'s `required_keys` now includes `symbol_sectors` and
  `max_positions_per_sector` — safe now that the live YAML has carried both since the
  2026-08-10 confirmation above (the §9.9/§9.7 ordering hazard this was originally held
  against is resolved). Added validation that every allowlisted symbol has a sector
  mapping, failing closed at load time rather than assuming it at enforcement time.
- New test module `tests/test_phase19_b4_gate_i_guard_wiring.py` (24 tests): the adapter
  delegates without reimplementing (no hardcoded counting loop), `load_rules()` rejects
  documents missing the new sections or with an unmapped allowlist symbol, `run_preflight`
  actually rejects a 2nd same-sector BUY and allows the 1st and a different-sector BUY,
  SELL never reaches Gate I, and position-fetch failure/absence fails closed (four
  separate failure modes: raising provider, `None` provider, `None` return, non-list
  return).
- Fixed `test_phase19a_strategy_v1_1_proposal_governance.py`'s
  `test_gate_letter_i_is_actually_free`, which pinned the pre-B4 "Gate I still unclaimed"
  state — rewritten as `test_gate_letter_i_is_actually_fulfilled` to verify the letter
  landed exactly once, on the right function. Renamed the manifest's
  `verified_against_code.gate_letter_i_free` to `gate_letter_i_fulfilled` to match, with
  `deterministic_manifest_hash` recomputed.
- **Also registered B3's 5 test files in `scripts/run-ci-portable`**
  (`test_phase19b_b3_{contract,golden_vectors,orchestration,precedence,safety}.py`) —
  same gap as the earlier B1/B2 fix: they existed on master (merged via PR #3) but were
  never part of the curated CI gate. Extended the compile check to
  `strategy_v1_1_core.py`/`strategy_v1_1_advisory.py`.
- Full curated suite: 2436 passed, 3150 subtests passed (0:22:46).

---

## 2026-08-11 — `/readiness` drift-masking bug fixed (Tier 1)

### Bug

`bridge.py`'s `/readiness` handler computed its `drift` summary from the bare
`monitor.position_drift_check()` — a file-only helper that returns
`expected_positions` (a dict), `symbols`, `unconfirmed_count`, and
`unconfirmed_approval_ids`, and **nothing else**. It has no `drift_detected` key and no
`mismatches` key. Every downstream read in `/readiness` —
`drift_info.get("drift_detected", False)`, `drift_info.get("mismatches", [])` — was
therefore reading keys that don't exist and silently taking the `.get(...)` default.
`/readiness` reported `drift_detected: false, mismatches: 0` unconditionally,
regardless of real state, on every call.

The real comparison against live IBKR positions already existed, in a separate
function: `monitor_positions_drift()` (`@app.get("/monitor/positions/drift")`,
`bridge.py:2598`), which wraps `position_drift_check()`, fetches live positions when
connected, computes true per-symbol `mismatches`, and sets
`drift_detected = len(mismatches) > 0`. `/readiness` never called it.

### Discovery

Caught during a readiness audit prompted by a third-party status report (channel
running `opencode-go/deepseek-v4-pro`, OC_DEFAULT binding per
`OPENCLAW_ROUTING_BINDINGS_v0_1.json`) that claimed an active AAPL position-drift alert
and 5 unconfirmed QQQ/1 AAPL legacy orders. Verified independently, side by side, with
live output from Chris's terminal:

```
/monitor/positions/drift  → drift_detected: true,  mismatches: [{AAPL: expected 1.0, actual 0}]
/readiness (same moment)  → drift_detected: false, mismatches: 0
```

`guard-events.jsonl` confirms the underlying `position_drift` alert (`severity:
critical`) had been re-firing every ~15 minutes for at least ~2 hours before discovery,
unresolved, because the one endpoint meant to surface it was masking it the entire
time. Root order: `order_id 24` (AAPL) sits in `legacy_unconfirmed` — cross-referenced
against the existing H3 note above (§ Verification Queue item 2 lineage): order 24 was
"Submitted but not filled," distinct from order 36 (the real, filled AAPL BUY @
$314.50). The confirmed-fill netting in `position_drift_check()` still shows
`AAPL: +1` from order 36 with nothing confirmed to net it back to 0, while live IBKR
genuinely shows 0 — a real bookkeeping gap, not a live broker risk (orders remain
triple-blocked regardless).

### Fix

- `bridge.py`: `readiness()` now calls `monitor_positions_drift()` instead of the bare
  `position_drift_check()`. One-line change; the correctly-shaped dict already flows
  through the existing `drift_status` construction unchanged. Safe when IBKR is
  disconnected — `monitor_positions_drift()` already guards on `is_connected()`
  internally (Step 15C — no blocking on IBKR calls).
- `monitor.py`: added **G11** to the readiness self-test section — asserts
  `/readiness`'s drift block agrees with `/monitor/positions/drift`'s real output
  (`drift_detected` and `mismatches` count). Regression coverage for this exact class
  of bug; requires a live bridge to run (same as G1–G10).

### Still open (not fixed by this change)

- The AAPL phantom position itself (order 24 stuck unconfirmed) is a separate data
  cleanup, not a code bug — needs a position-level reconciliation path (no existing
  `ibkr-operator` subcommand covers this; the existing `guard-state-reconcile` is
  trade-count/date only).
- The QQQ 5-unconfirmed-order artifacts (order IDs 40/46/52/60/71) are unrelated
  historical KID/PRIIPs artifacts, already root-caused above (§ Verification Queue
  item 2) — no new action needed there.
- `canonical_trade_date` in `guard-state.json` remains a permanently-stale legacy field
  (`stale_trade_date_repaired` repairs update `trade_date` but never touch it) — has now
  caused two separate false "stale date" reports from different channels. Not fixed
  here; worth a follow-up.

---

## 2026-08-11 — Phase 19F: Position-Drift Reconciliation for Unconfirmed-Order Mismatches

### Why

Follow-up to the `/readiness` drift-masking fix above. Fixing the masking bug makes
the AAPL phantom-position drift (§ above) *visible* on every `/readiness` call instead
of hidden — an improvement, but on its own that just converts a hidden problem into a
permanently-firing, never-resolved critical alert every ~15 minutes. `guard-state.json`
has no per-symbol position field to edit (expected quantity is computed fresh on every
call by `monitor.position_drift_check()` replaying `guard-events.jsonl`), so closing
this out needed a new, general repair path — not a one-off edit.

### Design constraint (important — read before extending this)

This tool does **not** assert that any unconfirmed order actually filled at the
broker. It only asserts that live IBKR is ground truth, and records — with a full
audit trail of which unconfirmed `approval_id`s were open for that symbol at the time
— that the computed expected quantity was adjusted to match it.

This distinction matters concretely: the existing Verification Queue items 1–2 above
show that assuming an unconfirmed order "must have filled because the final numbers
work out" can be wrong even when it happens to produce the right answer — order 24
(AAPL) is on record as "Submitted but not filled," a different order (36) was the real
fill, and the QQQ unconfirmed orders are unrelated KID/PRIIPs artifacts. Recording an
evidenced adjustment (delta only, no claim about *why*) instead of "marking the order
as confirmed" avoids inventing a fill that may never have happened, regardless of
whether that story happens to be tidy.

### Implementation

- **`monitor.py`**: new `POSITION_RECONCILIATIONS_PATH` /
  `load_position_reconciliations()` (fails open to empty on missing/corrupt file — an
  adjustment overlay must never crash or mask real drift). `position_drift_check()`
  now applies each recorded reconciliation's `qty_delta` on top of the existing
  fill-derived netting, additively — no event is removed or reinterpreted, and the
  return dict now carries `applied_reconciliations` for transparency. This flows
  through `monitor_positions_drift()` and therefore the now-fixed `/readiness`
  automatically — one adjustment point.
- **`ibkr_operator.py`**: new `position-drift-reconcile` command (aliases
  `position-drift-repair`, `reconcile-position-drift`), sibling to Step 15O
  (`guard-state-reconcile`) — same architectural pattern: dry-run by default,
  `--apply --confirm-local-state-repair` required to write, automatic backup before
  first write, audit export, evidence hash. Per-symbol repair evaluation: requires
  IBKR connected (never reconcile against unknown state), requires at least one
  unconfirmed order on record for that *exact* symbol (a mismatch with zero
  unconfirmed-order evidence is left alone — an unexplained drift is not this tool's
  job), 0 live/open orders, `IBKR_ALLOW_ORDERS=false`, `rules.enforced=false`.
- **`tests/test_phase19f_position_drift_reconcile.py`** (16 tests, all offline/unit —
  no live bridge needed, unlike the G11 test added to the previous fix): dry-run
  detection, refusal on unexplained mismatches, refusal when the unconfirmed order is
  for a different symbol, all four safety gates, apply-without-confirmation stays
  dry-run, apply writes the file and is honoured by `position_drift_check()` end to
  end (not just the tool's own re-verify step), missing/corrupt reconciliations file
  fails open, explicit non-actions present.

### Verification

- `python3.12 -m py_compile ibkr_operator.py monitor.py bridge.py` — clean. (This
  sandbox's default `python3` is 3.11, which rejects backslashes inside f-string
  expressions on a pre-existing, unrelated line elsewhere in `ibkr_operator.py` —
  confirmed via `.github/workflows/*.yml` that CI actually targets 3.12, where that
  line is valid; used 3.12 here to match.)
- `python3.12 -m pytest tests/test_phase19f_position_drift_reconcile.py -v` — 16/16
  passed.
- `python3.12 -m pytest tests/test_step15o_guard_state_reconcile.py
  tests/test_step15u_guard_state_drift_sentinel.py -v` — 51/52 passed; the one failure
  (`test_aliases_registered` in the 15U suite) hardcodes
  `/home/chris/agents/ibkr-bridge`, which doesn't exist in this sandbox — pre-existing,
  environment-specific, unrelated to this change.
- Did **not** run this against the live bridge — no IB Gateway in this sandbox. The
  actual AAPL reconciliation (running `position-drift-reconcile --apply
  --confirm-local-state-repair` for real) is Chris's to run against the live system,
  not something to execute unreviewed from here.

### Still open

- Running the actual repair against the live AAPL mismatch — this PR ships the tool,
  not the applied fix. Chris runs `ibkr-operator position-drift-reconcile` (dry-run
  first) against the live bridge to close out the real AAPL drift.
- `canonical_trade_date` stale-field cleanup (noted in the entry above) — still not
  addressed.

---

## 2026-08-11 — Phase 19G: Weekly Loss-Halt Rollover (Tier 1)

### Bug

`guard._rollover_guard_state()` handled the daily calendar rollover (`trade_date`,
`daily_trade_count`, `daily_halt_active`, `day_start_nl_eur`) but had no weekly
equivalent. `week_start_date` and `week_start_nl_eur` were set exactly once, in
`default_guard_state()`, and never rolled forward by anything. Since
`gate_loss_halts()` only evaluates its weekly branch `if week_start and week_start > 0`,
and `week_start_nl_eur` stayed `None` indefinitely, **the −3% weekly loss halt has been
structurally inert since whatever session last created a fresh `guard-state.json`** —
not a display bug, a dead safety check. `week_start_date` showing a stale value (first
noticed as `"2026-06-01"` during tonight's readiness audit, now over two months old)
was the visible symptom; the actual defect was the missing rollover, not the stale
display value itself.

### Fix

`guard.py`: `_rollover_guard_state()` now evaluates both the daily and weekly
staleness conditions before doing anything (so the common case — neither stale —
stays a zero-cost no-op, same as before). When the current UTC week's Monday
(`_current_week_monday_utc_str()`, already existed, previously only called from
`default_guard_state()`) is later than the stored `week_start_date`: clears
`weekly_halt_active`, updates `week_start_date`, and captures `week_start_nl_eur` from
a live account fetch — mirroring the daily capture exactly. A weekly halt clears on
week rollover the same way a daily halt clears on day rollover; there's no count to
restore for the weekly side (only day has a trade-count rule). When both are stale at
once, `fetch_account()` is called once and shared, not once per rollover type. The
`guard_calendar_rollover` event payload now carries both daily and weekly fields,
`None` for whichever side didn't roll over.

### Test coverage

`_rollover_guard_state()` had **zero direct test coverage before this change** —
daily rollover was only ever exercised indirectly through `run_preflight()`
integration, never asserted against directly. `tests/test_phase19g_weekly_loss_halt_rollover.py`
(12 tests) covers both: the pre-existing daily behavior (locking in current behavior
that was previously untested) and the new weekly behavior — no-op when neither is
stale (and no live account call at all on that path), daily-only, weekly-only, both
together (single shared account fetch, asserted via call count), account-fetch failure
degrading gracefully on either side, event-payload shape for each combination, and an
end-to-end check that `gate_loss_halts()` actually triggers the weekly branch once
`week_start_nl_eur` is populated — the exact path that was unreachable before.

### Also fixed: the same curated-CI-gate gap as B1/B2/B3, recurring

`tests/test_phase19f_position_drift_reconcile.py` (added earlier tonight, already
merged) was never added to `scripts/run-ci-portable`'s curated `TESTS` array — the
exact gap the B1/B2/B3 phases already hit and got flagged for above. CI's green
checkmark on that merge did not actually exercise those 16 tests; `--collect-only`
against the curated list would have shown it missing. Registered both that file and
this one's `test_phase19g_weekly_loss_halt_rollover.py` now. Worth a standing habit:
`scripts/run-ci-portable --collect-only` (or just grepping the new file's name against
the script) after adding any new test file, not just running it standalone.

### Verification

- `python3.12 -m py_compile bridge.py guard.py ibkr_operator.py strategy_v1_1_core.py
  strategy_v1_1_advisory.py` — clean.
- `python3.12 -m pytest tests/test_phase19g_weekly_loss_halt_rollover.py
  tests/test_ci_invariant_assertions.py` — 31/31 passed.
- Confirmed `tests/test_p5_bracket_stops.py`'s unrelated `FileNotFoundError:
  paper-trading-rules.yaml` failures (14 of them) are pre-existing and environment-only
  — reproduced identically on unmodified `guard.py` via `git stash`. This sandbox has
  no `~/.openclaw/risk-rules/paper-trading-rules.yaml`; not something to fix here.
- Full curated suite (`scripts/run-ci-portable`'s exact `TESTS` array, 38 files after
  the two registrations above, `--collect-only` confirms 2464 tests collected, zero
  collection errors) run locally under Python 3.12 to match CI — result pending at
  time of writing this entry; will not push until it's actually green, not assumed
  green from the file-by-file checks above.

### Still open

- The weekly halt will now start tracking correctly going forward, but
  `week_start_nl_eur` for *this* week won't be captured until the next preflight call
  after this deploys (rollover only runs inside `run_preflight()`) — the very first
  preflight after deploy will both roll the stale week forward and capture a fresh
  start value in the same call, per the new test coverage.
- `canonical_trade_date` stale-field cleanup — still open, unrelated to this fix.

---

## 2026-08-13 — Phase 19H/19I: Three tooling bugs found during a live paper-mode
readiness check (Tier 2 — read-only tooling, no runtime-safety files touched)

**Bug 1 (19F follow-up) — `position-drift-reconcile` trusted never-approved
approvals as fill evidence.** Live-checked ahead of the 2026-08-17 run start:
`/monitor/positions/drift` reported AAPL expected=1.0, actual=0, and
`position-drift-reconcile` named `aprv_d39f1f84-b8fd-4d6a-9a99-0485b677dd4f`
(order_id=24) as the candidate explanation. Inspecting the approval record
directly showed `"status": "pending", "ruled_by": null`, expired 2026-06-03 —
it was never approved, so per the order path (preflight → approve → submit)
it could not possibly have reached the broker. The tool's candidate selection
only matched `order_submitted` events against the drift endpoint's
`unconfirmed_approval_ids`; it never checked whether the matched approval had
actually been ruled. Fixed: `_filter_ruled_unconfirmed_approvals()` in
`ibkr_operator.py` looks up each candidate's own `approval-records.jsonl`
status and excludes anything not `"approved"` from repair consideration,
surfacing a new `only_legacy_unruled_evidence` blocker and an
`excluded_unruled_approval_ids` field on the result for audit visibility
instead of silently treating implausible evidence as ordinary.

**Bug 2 — `legacy_unconfirmed` re-flagged the same resolved item on every
startup, forever.** The same order_id=24/AAPL event has an
`order_submitted` entry with no `ibkr_metadata` — the exact "legacy pre-fix
submission" case `guard.py`'s own comment already named. A human
(Werner-H4.1) manually reconciled it as `NotFoundInIBKR, filled=0.0` on
2026-06-11 via `monitor.append_manual_reconciliation()`. But
`reconcile_approvals_on_startup()`'s legacy-detection scan never consulted
that reconciliation record, so it kept re-flagging the identical entry on
every single bridge restart for two more months (~32,000 matching lines in
`guard-events.jsonl` by the time this was caught) — almost certainly the
source of the stale `expected_qty: 1.0` for AAPL that motivated the live
drift investigation in the first place. Fixed: the scan now loads
`monitor.load_manual_reconciliations()` and excludes any `(order_id, symbol)`
pair already carrying a manual-terminal record; fails open to the old
behavior if the reconciliations file can't be read.

**Bug 3 — checklist `reconciliation_pass` read the wrong key, always `False`.**
`ibkr_operator._build_summary()` read `recon.get("pass", recon.get("ok",
False))`, but `/monitor/reconciliation` (`monitor.reconcile_snapshot()`) has
only ever returned its verdict under `"passed"`. Neither `"pass"` nor `"ok"`
has ever existed in the real response, so `reconciliation_pass` silently
defaulted to `False` on every checklist run regardless of actual state —
caught live when a same-moment `/monitor/reconciliation` call showed
`"passed": true` with all six sub-checks true, while the checklist reported
`reconciliation_pass: false`. Fixed: reads `"passed"` first, falls back to
the old keys defensively.

### Discovery path

All three surfaced from one live investigation, not a code review: Chris ran
a paper-mode readiness check; `/monitor/positions/drift` showed a real
AAPL mismatch once IBKR was genuinely connected (an earlier "clean" read had
been a disconnected-state placeholder). The tool's named candidate turned out
to be provably wrong (bug 1), tracing *why* led to the stale legacy-flag
computation (bug 2), and cross-checking the checklist's own summary against
the endpoints it aggregates surfaced the key mismatch (bug 3). The AAPL
position itself was separately corrected via `position-drift-reconcile
--apply --confirm-local-state-repair`, grounded in the live IBKR read and
Chris's direct operator confirmation the account was flat — not in the
disproven candidate-approval reasoning.

### Verification

- `python3.12 -m py_compile bridge.py guard.py ibkr_operator.py
  strategy_v1_1_core.py strategy_v1_1_advisory.py monitor.py` — clean.
- New tests: `tests/test_phase19h_checklist_reconciliation_key_fix.py` (6),
  `tests/test_phase19i_legacy_unconfirmed_manual_reconciliation.py` (5);
  `tests/test_phase19f_position_drift_reconcile.py` extended with the
  never-ruled-candidate regression and an approval-status fixture threaded
  through the existing dry-run/apply tests. Both new files registered in
  `scripts/run-ci-portable`'s curated `TESTS` array.
- Full curated suite run locally under Python 3.12 before push — see commit
  for pass/fail count, not assumed green from the file-by-file checks above.

### Still open

- No code in this repo yet *computes* the normalized-YAML-hash pin the
  `pr-2026-08-v4` pre-registration document describes (replace exactly one
  `enforced: true|false` with `enforced: false`, hash, fail closed on
  zero/multiple matches) — it was verified by hand against the live host
  tonight. Worth a real `ibkr-operator` read-only check before it's leaned on
  again for a run boundary.
- `TEMPLATE-preregistration.md` still has the original, unfixed §2 wording
  (bare Git-commit/YAML-hash `<<FILL IN>>`, no pathspec/normalization
  guidance) — `pr-2026-08-v4`'s improved approach was never folded back into
  the reusable template.

---

## 2026-08-13 — Phase 19J: pre-registration pin verification, implemented (Tier 2
— read-only tooling)

Both items left open above are closed by this entry.

**New `ibkr-operator preregistration-pin-verify` command** (alias
`prereg-pin-verify`) implements, as actual executable code, the pin-computation
procedure `pr-2026-08-v4-preregistration.md`'s §2 describes — until now verified
by hand against the live host:

- **Git runtime-safety pin**: `git log -1 --format=%H --` filtered to
  `bridge.py guard.py monitor.py ibkr_operator.py strategy_v1_1_core.py
  strategy_v1_1_advisory.py`. Immune to docs-only commits landing on top of it —
  verified against a throwaway git repo in the test suite, not just asserted.
- **YAML normalized configuration pin**: `paper-trading-rules.yaml`'s SHA-256
  after replacing exactly one `enforced: true|false` field with
  `enforced: false`. Fails closed (returns an error, not a guessed hash) on zero
  or more than one `enforced:` match.
- With `--doc <path>`, parses a pre-registration document's own §2 table and
  compares live pins against what it recorded — `MATCH`/`MISMATCH`/`NOT_FOUND_IN_DOC`
  per pin, non-zero exit on any mismatch. Without `--doc`, just prints the live
  pins. Read-only: no protected file, no order path, no H1 token, no writes
  anywhere.
- The YAML rules path is read from `guard.RULES_PATH` by reference (not a copied
  default), so an `IBKR_RULES_PATH` override on the live host is honoured
  automatically rather than risking a second, independently-drifting constant —
  worth calling out because `ibkr_operator.py` already had an unrelated,
  differently-valued `_RULES_PATH` constant (`BRIDGE_DIR / "rules" / ...`) that
  this deliberately does not reuse.

**`TEMPLATE-preregistration.md` updated** to match: §2's Git-commit/YAML-hash
rows renamed to "Git runtime-safety pin" / "paper-trading-rules.yaml normalized
configuration SHA-256," with the pathspec command, the normalization procedure,
and the `pr-2026-08-v2` self-referential-pin incident cited as the concrete
reason for both, plus a pointer to the new command for sealed-document
verification. Only the template changed — `pr-2026-08-v2` and `pr-2026-08-v4`
themselves are sealed and were not touched (and, per their own rule, must not
be).

### Verification

- `python3.12 -m py_compile ibkr_operator.py` — clean.
- Manually cross-checked both pin functions against tonight's independently
  hand-verified live-host values (`ff7973328184df73b31c4d8d27adeee5d83620c9`,
  `fadb4402f0a7c286945fab5f1d429113063200532e3936f47f0f8ed555a0442b`) before
  writing the formal suite.
- `tests/test_phase19j_prereg_pin_verify.py` (19 tests): pathspec-filtered pin
  matches an independent raw `git log` call; a real throwaway-repo commit
  proves a docs-only commit doesn't move the pin; YAML pin fails closed on
  zero/two `enforced:` matches; `true`/`false` normalize identically (proving
  the trade-window cycle doesn't void a run) while any other field change still
  moves the pin; document-comparison MATCH/MISMATCH paths, including a direct
  regression using zeroed-out pins for the exact class of staleness the
  `pr-2026-08-v2` incident produced; CLI alias registration and `--json` output
  validity. Registered in `scripts/run-ci-portable`.

---

## 2026-08-17 — Phase 19K: heartbeat systemd timer tracked in git, staleness
threshold tightened, failure alerting wired (Tier 2 — read-only tooling)

Chris asked whether a cron/timer was needed for the heartbeat, or whether the
interval was worth reducing for trading purposes — investigation found a
timer already existed, deployed directly on the live host since 2026-06-13
(Phase 7), never checked into this repo. `tests/test_p7_heartbeat.py` had
been written expecting exactly this (`~/.config/systemd/user/ibkr-heartbeat.
{service,timer}`, `systemctl --user is-enabled`) and is deliberately excluded
from portable CI as a host/workstation acceptance test — but the unit files
themselves were never committed, so the repo carried a test spec for an
implementation it didn't track.

**`systemd/ibkr-heartbeat.service` and `.timer` added**, copied verbatim from
the live, active deployment (confirmed via `systemctl --user list-timers`
before this was written): `OnCalendar=*:0/15` (every 15 min),
`RandomizedDelaySec=30`, `Persistent=true`; the service runs `ibkr-operator
heartbeat --json --quiet` read-only, hardened (`ProtectSystem=strict`,
`NoNewPrivileges=true`, no `ExecStartPre/Post`, no forbidden endpoints).
15 minutes was kept as-is rather than shortened — every order this system
executes requires a human to personally initiate and approve each step, so
the heartbeat's job is "notice infrastructure is down before it's used," not
real-time safety monitoring; a 15-min worst-case lag ahead of an
actively-driven session doesn't need shrinking, and doing so mostly adds log
volume for little benefit.

**Two real gaps did need fixing, found by reading `run_kpi()` and
`_run_heartbeat()` against the actual deployed cadence:**

1. `HEARTBEAT_STALE_THRESHOLD_SECONDS` (new named constant, `2700` = 45 min)
   replaces two independently-hardcoded `86400` (24h) literals in
   `run_kpi()` — one gating a `heartbeat_stale` HOLD, one setting
   `heartbeat.recent`. 24h tolerated silence for nearly a full day on a
   system whose real cadence is 15 minutes; 45 min tolerates a few missed/
   slow cycles without a false HOLD while catching a real outage the same
   trading day.
2. A failing heartbeat never surfaced anywhere — `_run_heartbeat()` only
   wrote its own JSON artifact, invisible to `/monitor/alerts`, doctor, or
   checklist until the (old, 24h) staleness threshold elapsed. Endpoint
   failures now log a `monitor_alert` event via a new
   `monitor.append_heartbeat_alert()`, the same pipeline every other alert
   in this codebase already flows through. Deliberately keyed on the
   bridge's own endpoints failing, not on IBKR `connected` — a disconnected
   Gateway overnight/pre-market is routine, not an infrastructure failure,
   and alerting on it every 15 minutes would just be noise.

**Why `monitor.append_heartbeat_alert()` and not a direct call from
`ibkr_operator.py`:** `append_guard_event` is on `ibkr_operator.py`'s own
AST-level `_FORBIDDEN_NAMES` safety check (`_enforce_safety()`, module import
time) — it must stay strictly read-only, and the check caught the first
draft of this fix immediately (`SystemExit(99)` on import). `monitor.py`
already owns the one write path in this layer (`append_manual_
reconciliation`); `append_heartbeat_alert` follows the same pattern next to
it, and `ibkr_operator.py` calls that instead.

### Verification

- `python3.12 -m py_compile bridge.py guard.py ibkr_operator.py
  strategy_v1_1_core.py strategy_v1_1_advisory.py monitor.py` — clean, and
  confirms `_enforce_safety()`'s AST check passes (`ibkr-operator heartbeat
  --help` exits 0, not 99).
- New: `tests/test_phase19k_heartbeat_alerting.py` (20) — threshold value
  pinned as a deliberate regression guard; `_heartbeat_age_seconds()`
  exercised against real controlled artifact mtimes (not a mocked
  `run_kpi()`) at fresh/just-past-threshold/old-would-have-passed
  boundaries; alert wiring covered for all-ok (no alert), one endpoint
  failing (alert fires, detail includes the failing endpoint), alert-path
  itself failing (heartbeat still succeeds), and IBKR-disconnected-alone
  (no alert — the routine case). Plus repo-side sanity checks that the
  tracked systemd files match what's deployed (interval, hardening flags,
  no forbidden endpoints). Registered in `scripts/run-ci-portable`.

### Still open

- `tests/test_p7_heartbeat.py` and `test_p8_systemd_hardening.py` remain
  host-only, excluded from portable CI by design — they validate the live
  `~/.config/systemd/user/` deployment directly, not the repo copies added
  here. Worth periodically diffing the two by hand if the live units are
  ever hand-edited without a matching repo commit, to avoid this exact gap
  recurring.

---

## 2026-08-17 — Phase 19L: preflight's rollover write needed H1 scope (Tier 1)

Live incident, on the run's own start day. `run_preflight()` returned HTTP
500 (via OpenClaw, cross-checked against source before acting): `guard-state
.json`'s `trade_date` was stale (2026-08-11 vs 2026-08-17). Repaired via the
existing `ibkr-operator guard-state-reconcile --apply --confirm-local-state-
repair` (safe, non-H1, its own independent gates — daily trade_date only, by
design). Preflight still 500'd — `week_start_date` (2026-06-01) was *also*
stale, and `guard-state-reconcile` has never covered week fields.

**Root cause, traced directly, not taken on report:** `run_preflight()` ->
`load_guard_state()` -> `_rollover_guard_state()` -> `save_guard_state_atomic
()` writes `guard-state.json`, a Phase H1.2 protected path, whenever either
the daily or weekly rollover actually fires (guard.py:2392, unchanged since
Phase 19G). Preflight itself never carries H1 authorization — H1 is scoped
to `/order/approve` and `/order/submit` only (invariant #17). The call was
unwrapped, and `run_preflight()`'s surrounding `except` only caught
`RuntimeError`/`ValueError`/`FileNotFoundError`, not `PermissionError`, so
the unauthorized write raised straight through the request handler instead
of the documented validation-only response. No CHANGELOG entry, code
comment, or test anywhere tied H1 enforcement to this call site — a latent
gap between two features (H1 protected-path enforcement, Phase H1.2; and
preflight-triggered rollover, Phase 19G) built at different times and never
reasoned through together, which had simply never manifested before: it
needs guard-state.json to have gone stale *and* H1 enforcement active *and*
someone to actually call preflight, and this is the first time all three
lined up.

**Fix:** the rollover is deterministic, wall-clock-driven housekeeping with
no adversarial degrees of freedom — not an order mutation — so it now gets
its own narrow `with h1_authorized_scope():` around the one call, exactly
the pattern that context manager's own docstring describes
(`h1_authorized_scope()`: "Sets authorization only for the narrow critical
section"). Authorization ends the instant the `with` block exits; nothing
else in the request gains it.

### Why not `guard-state-reconcile` extended to cover week_start_date instead

Considered and rejected as the primary fix: it would duplicate logic that
already exists correctly in `_rollover_guard_state()`, in a second,
hand-maintained tool, rather than fixing the actual call site that fails.
The narrow scope fix resolves the daily case, the weekly case, and any
future field the rollover grows, in one place.

### Verification

- `python3.12 -m py_compile bridge.py guard.py ibkr_operator.py
  strategy_v1_1_core.py strategy_v1_1_advisory.py monitor.py` — clean.
- New: `tests/test_phase19l_preflight_rollover_h1_scope.py` (7) —
  reproduces the original bug directly (`_assert_h1_authorized_for_path`
  raises under real enforcement, unscoped); confirms the scope suppresses
  it and doesn't leak past its `with` block; exercises
  `_rollover_guard_state()` both unwrapped (raises, the exact live
  incident shape) and wrapped (succeeds, persists both trade_date and
  week_start_date) against a real, isolated protected path (not mocked
  away — `PROTECTED_PATHS` is a module-level set, extended with a tmp
  path and restored after, so the test can't pass by accident with
  enforcement silently disabled); an end-to-end `run_preflight()` call
  with a doubly-stale state under real enforcement, confirming no
  exception and that both fields actually rolled; a source-text regression
  guard pinning the `with h1_authorized_scope():` wrapper in place.
  Registered in `scripts/run-ci-portable`.
- 5 pre-existing failures in `test_contextvar_h1_race.py` (`ModuleNotFound
  Error: fastapi`, this sandbox only) reproduced identically against
  unmodified `guard.py` via `git stash` before being dismissed as
  unrelated — not assumed.

### Still open

- **Requires a bridge restart to take effect** — unlike Phase 19H-19K
  (`ibkr_operator.py`-only, fresh subprocess every invocation), `guard.py`
  is imported by the long-running `ibkr-bridge.service` process at module
  load. Pulling this commit alone does not change live preflight behavior;
  `systemctl restart ibkr-bridge.service` is required. Per invariant #12
  this invalidates any in-memory pending/approved-but-unsubmitted
  approvals — expected to be a no-op today (kill switches locked, nothing
  mid-cycle), but stated explicitly rather than assumed silent.
- Tier-1 file — held for explicit merge approval rather than self-merged,
  per routing policy, even though found and fixed same-day as a live
  blocker.

---

## 2026-08-18 — Phase 19M: `ibkr-operator hermes-proposal` never actually
produced a Gate-H-passing proposal (Tier 2)

Chris, direct operator question: "How to get the proper proposal from
Hermes via OC since it should work this way or am i wrong?" — after
OpenClaw reported preflight running fully clean and asked whether to
generate a real proposal file. Traced against source rather than assumed
working because the field names *looked* deliberately matched.

**What was actually there:** two independent, never-reconciled
implementations of "ask Hermes for a proposal, in JSON":

- `hermes_advisory.py` (Phase 5B.1/P3) — a standalone script. Its prompt
  template already includes a `position_sizing` object (`method`,
  `stop_price`, `final_shares`, plus supporting detail),
  and it already calls `guard.save_proposal_file()` to persist the parsed
  response, bare and unwrapped, to `~/.openclaw/proposals/`. Correct, but
  not wired to any `ibkr-operator` subcommand — nothing runs it day to day.
- `ibkr_operator.py`'s `_run_hermes_proposal()` (Phase 5B.1 "(original)")
  — the function actually behind the `ibkr-operator hermes-proposal`
  command Chris and OpenClaw use. Its own private copy of the prompt
  template never asked for `position_sizing` at all, and the function
  never persisted anything to disk. Its documented `--output <path>` flag
  writes the *whole wrapped result* (`{"command":..., "proposal":
  {...}, "raw_response":..., "evidence":...}`), not the bare object Gate H
  (`guard.gate_proposal_discipline`) reads at the top level. Net effect: a
  BUY proposal generated this way could never pass Gate H — missing
  `position_sizing` unconditionally fails it (`guard.py`'s
  `_MANDATORY_POSITION_SIZING_FIELDS`, no exception for BUY) — regardless
  of how good Hermes's answer was, and there was no file on disk for Gate H
  to read in the first place.

**Fix:** `_run_hermes_proposal()` now imports and calls
`hermes_advisory.build_prompt()` for the prompt instead of maintaining its
own copy, and — when Hermes's response parses as a JSON object — persists
it via `guard.save_proposal_file()`, the same call `hermes_advisory.py`
already used. One shared template, one shared persistence path, called
from the command operators actually run. A malformed/unparsable response
is never persisted (no phantom proposal files); a persistence failure
(disk full, etc.) is reported in the result (`proposal_persist_error`) but
does not fail the command — Hermes's advisory answer is still worth
showing even if the write fails. The result dict gains `proposal_path`;
`_print_hermes_result()` now prints it, or the persist error if the write
failed.

### Why not fix this by adding `position_sizing` + persistence directly
inside `_run_hermes_proposal()` instead of importing from
`hermes_advisory.py`

Considered and rejected: that would leave two hand-maintained copies of
the same template able to drift again exactly as they already had —
`hermes_advisory.py`'s copy grew a field the other one never got. Importing
the one canonical template and the one canonical persistence function
removes the duplication instead of patching one side of it.

### Verification

- `python3.12 -m py_compile ibkr_operator.py guard.py hermes_advisory.py
  strategy_v1_1_core.py strategy_v1_1_advisory.py` — clean.
- `python3.12 ibkr_operator.py hermes-proposal --help` — module still
  imports cleanly (confirms `save_proposal_file` isn't caught by
  `ibkr_operator.py`'s own `_enforce_safety()` AST check — it isn't in
  `_FORBIDDEN_NAMES`, and it performs no order/guard-state mutation).
- New: `tests/test_phase19m_hermes_proposal_persistence.py` (7) — source
  regression guards that the private ad hoc template is gone and the
  shared `build_prompt()` is actually imported and invoked; a valid parsed
  response gets persisted and the file on disk round-trips with
  `position_sizing` intact; the persisted file is fed straight into
  `guard.gate_proposal_discipline()` and asserted to **pass** — the
  concrete end-to-end proof this was previously impossible and now isn't;
  an unparsable Hermes response leaves no file behind; a
  `save_proposal_file()` failure is reported, not raised, and doesn't
  block the advisory answer from being returned. Registered in
  `scripts/run-ci-portable`.
- Not a Tier-1 change — touches `ibkr_operator.py` only (calls into
  `guard.save_proposal_file()`, an existing, unmodified function; `guard.py`
  itself is untouched).

### Still open

- `hermes_advisory.py` itself still has the Gate-I/regime-logic
  duplication concern flagged in the Phase 19B entry above (unrelated to
  this fix — that concern is about its sector-concentration signal
  generation, not the prompt-template/persistence path touched here).
- This makes `ibkr-operator hermes-proposal` capable of producing a
  Gate-H-passing file; it does not itself validate that Hermes's actual
  live numbers (price, ATR, sizing math) are correct — that's Hermes's
  advisory judgment and Chris's review, same as before.

## 2026-08-27 — Phase 19N: `/order/preflight` could hang indefinitely on a
stalled Gateway (Tier 1)

Live incident, run day: Chris ran the exact documented `/order/preflight`
curl against a real, previously-persisted (Phase 19M) proposal file. It
never returned — killed manually past 75s, then confirmed with
`--max-time 60` → `HTTP 000`, 0 bytes. The bridge itself was healthy the
whole time (`/`, `/health`, `/account`, `/positions` all responded
instantly) — only this one endpoint was affected.

**Diagnosed by OpenClaw, independently verified against this exact
checkout before any fix was written** — every claim checked out, exact
line numbers included:

- `bridge.py`'s `order_preflight()` wired `guard.run_preflight()`'s
  `quote_provider`/`bars_provider` to the *unbounded*
  `_internal_fetch_quote`/`_internal_fetch_bars`.
- Both call `ib.qualifyContracts()` — a synchronous IBKR round-trip with no
  deadline. Against a stalled/slow Gateway this blocks forever.
- `guard.run_preflight()`'s except clause around the account/quote/bars
  fetch catches only `(RuntimeError, ValueError, FileNotFoundError)`. A
  blocked `ib` call raises nothing — there was never an exception available
  to catch. Preflight hung before any gate ever ran, which is also why
  uvicorn's access log showed no `POST /order/preflight` line at all (it
  only logs after the handler returns).
- `_internal_fetch_quote_safe` already existed (Step 15L-B/15N) as exactly
  the right bounded pattern — thread executor, `future.result(timeout=...)`,
  raises `RuntimeError("market_data_timeout: ...")` on timeout — but was
  never wired into `order_preflight()`. No bars equivalent existed.

While tracing the fix, found the same unbounded pair wired into two more
places, same bug, not yet hit live:

- `/order/submit`'s revalidation step (`guard.revalidate_before_submit`,
  invariant #5 — "submit-time revalidation") — would hang the same way
  mid-submit against a stalled Gateway.
- `/order/dry-run`'s internal `run_preflight()` call.

**Fix:** added `_internal_fetch_bars_safe()`, mirroring
`_internal_fetch_quote_safe()` exactly (thread executor, bounded
`future.result(timeout=_MARKET_SNAPSHOT_TIMEOUT)`, `RuntimeError` on
timeout, `executor.shutdown(wait=False)` so a leaked background thread
never blocks the caller, shares the existing leaked-thread counter/warning
so repeated bars timeouts are tracked the same way repeated quote timeouts
already are — including the symmetric `_decrement_leaked_md_thread()` call
at the end of `_internal_fetch_bars()` itself, matching
`_internal_fetch_quote()`'s own pattern, so the counter doesn't drift
upward forever). Re-wired all three call sites
(`order_preflight()`, `submit_order()`'s revalidation wiring,
`/order/dry-run`'s internal preflight call) to the `_safe` variants.

No `guard.py` change was needed: `run_preflight()`'s except clause already
catches `RuntimeError`, and `revalidate_before_submit()`'s quote/bars except
clauses already catch `RuntimeError` specifically — the `_safe` wrappers'
timeout `RuntimeError` slots into handling that already existed and was
already correct. This was purely a wiring bug in `bridge.py`.

Built and PR'd through the normal repo workflow rather than a live hotfix
directly on the host — `bridge.py` is Tier 1 and the order-safety path;
git history, tests, and Chris's explicit review apply the same as any
other Tier-1 change, same as Phase 19L.

### Verification

- `python3.12 -m py_compile bridge.py guard.py ibkr_operator.py
  hermes_advisory.py strategy_v1_1_core.py strategy_v1_1_advisory.py` —
  clean.
- New: `tests/test_phase19n_preflight_bounded_market_data.py` (10 in the
  curated suite + 3 `@pytest.mark.integration`, mirroring
  `test_step15n_backpressure_leak.py`'s existing pattern for the quote
  wrapper). Curated-suite tests: source regression proving all three call
  sites actually use the `_safe` variants (not just that the variants
  exist), that no unbounded wiring survived anywhere in `bridge.py`, that
  the new wrapper actually bounds the call (thread executor +
  `future.result(timeout=...)`) rather than being a same-named passthrough,
  and that the leaked-thread counter is symmetric. Plus a guard.py-only
  behavioral pair (no `bridge.py`/`fastapi` import needed) proving the
  exact original failure mode is fixed: a `quote_provider`/`bars_provider`
  that raises `RuntimeError` (exactly what the `_safe` wrappers do on
  timeout) now produces a clean `{"passed": False, "error": "..."}`
  response from `run_preflight()`, never an uncaught exception. Integration
  tests (skipped in this sandbox — no `fastapi` installed here, same as the
  existing Step 15N ones) mirror `TestFetchQuoteSafeTimeout` for the new
  bars wrapper, plus an end-to-end test simulating both fetches hung and
  asserting `/order/preflight`'s own code path returns in well under the
  live ~75s+ hang. Registered in `scripts/run-ci-portable`. Full curated
  suite: 2540 passed (was 2530), 0 failures, 3150 subtests passed.

### Still open

- Confirm live, once merged and the bridge is restarted: re-run the exact
  curl Chris used against the same persisted AAPL proposal file and
  confirm a full gate-by-gate JSON response (not a hang) — OC already
  confirmed Gate H passes independently via a direct
  `guard.gate_proposal_discipline()` call against the file; this closes the
  loop through the actual endpoint.
- Requires a bridge restart to take effect (unlike Phase 19M, which only
  touched `ibkr_operator.py`/`hermes_advisory.py` and needed none) — the
  bridge is a long-running process, not invoked fresh per call.
- Tier-1 file — held for explicit merge approval rather than self-merged.

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
