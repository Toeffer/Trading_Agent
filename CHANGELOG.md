# CHANGELOG — OpenClaw / Werner / IBKR Bridge

History, order records, and superseded decisions. **`CLAUDE.md` holds no history** — when
a fact there changes, its old form lands here with a date. Append-only.

> Reconstructed 2026-06-09 from the prior monolithic CLAUDE.md. Phase boundaries are
> preserved; exact per-phase dates were not all recorded in the source and are marked
> where uncertain. Items needing live confirmation are collected in **§ Verification Queue**.

---

## Order history (paper account DUQ542875)

| Date | Symbol | Action | Qty | Type | Order ID | Fill | Notes |
|---|---|---|---:|---|---|---|---|
| 2026-06-02 | — | first paper order | — | — | — | First order executed; both kill switches rolled back after |
| 2026-06-03 | AAPL | SELL | 1 | MKT | 36 (permId 551562267) | $314.50 | Close-only |
| 2026-06-09 | AAPL | SELL | 1 | MKT | 24 | ~$300.30 | Close-only — Phase 5C cycle 1 |
| 2026-06-09 | META | BUY | 72 | MKT | 25 | $596.28 avg | Open — Phase 5C cycle 2 (current position) |
| 2026-06-09 | QQQ | BUY | 59 | MKT | 52, 60, 71 | — | **Blocked** by KID/PRIIPs |

> ⚠️ **Verify:** the source file presented two different AAPL closes as "the" close event
> — order 36 @ $314.50 (06-03) and order 24 @ ~$300.30 (06-09). Both are tabled above;
> confirm against `/monitor/events` which fills are real vs. test artifacts.

Known test artifacts (classified `historical`, `requires_action=false`): order_ids 12345,
99999; approvals `aprv_noexec`, `aprv_7`.

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

### Phase 5C — Dual decision cycles — COMPLETE (2026-06-09)
- Two live paper cycles: AAPL SELL filled (close-only) + META BUY 72 @ $596.28 filled;
  QQQ BUY blocked by KID/PRIIPs. Both kill switches rolled back after each cycle.
- Mandatory position-sizing-rationale section added to every proposal.
- Data-provenance policy: Hermes source-labeling, IBKR = truth.
- Allowlist updated to AAPL/META/NVDA/AMD (SPY/QQQ removed).

---

## Verification Queue (resolve against the live system)

0. **Risk-rails divergence (highest priority — safety-relevant).** `CLAUDE.md §5`
   (v1.3-draft, YAML-sourced) states 2% risk/trade, 30% exposure, no weekly trade cap. The
   RUNBOOK's Phase 5 Hermes pilot rails state 0.25% risk/trade, 25% exposure, 5 trades/week.
   Loss halts match (−1% day / −3% week), and max position matches (5%). Two readings:
   **(A)** advisory overlay — `guard.py` enforces the wider v1.3-draft caps as the hard
   ceiling, Hermes proposes inside a tighter envelope (most likely; the matching loss halts
   and the fact that 0.25% = 5% notional × 5% stop floor both support this); **(B)**
   supersession — the YAML/guard were tightened to the pilot numbers and §5 is stale.
   Resolve by reading `paper-trading-rules.yaml` + the limit constants in `guard.py`. If (B),
   update `CLAUDE.md §5`. If (A), §5 is correct as the enforced ceiling and the pilot envelope
   stays documented under Hermes.
1. **AAPL close discrepancy** — order 36 @ $314.50 (06-03) vs order 24 @ ~$300.30 (06-09).
   Which is the real close? Cross-check `/monitor/events`.
2. **QQQ remnant count** — source said "2 cancelled" but listed three IDs (52, 60, 71).
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
