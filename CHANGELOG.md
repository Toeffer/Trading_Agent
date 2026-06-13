# CHANGELOG — OpenClaw / Werner / IBKR Bridge

History, order records, and superseded decisions. **`CLAUDE.md` holds no history** — when
a fact there changes, its old form lands here with a date. Append-only.

> Reconstructed 2026-06-09 from the prior monolithic CLAUDE.md. Phase boundaries are
> preserved; exact per-phase dates were not all recorded in the source and are marked
> where uncertain. Items needing live confirmation are collected in **§ Verification Queue**.

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
