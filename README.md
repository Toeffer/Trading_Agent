# IBKR OpenClaw Bridge

A FastAPI bridge, deterministic risk guard, and read-only operator CLI for **manual-approval,
paper-trading-only** stock/ETF order cycles against Interactive Brokers, built for the
OpenClaw/Werner runtime. Not a general-purpose trading framework — the safety architecture
(kill switches, gated order lifecycle, H1 approval boundary) is the point of this codebase.

**This README is a map, not a source of truth.** For anything that actually matters —
current safety-invariant status, kill-switch state, what's live vs. archived, operator
procedures — see the files below, not this one:

| File | What it's for |
|---|---|
| `CLAUDE.md` | Identity, safety invariants, architecture, active rules. The load-bearing doc. |
| `RUNBOOK.md` | Operator commands and procedures (`ibkr-operator` CLI, break-glass). |
| `CHANGELOG.md` | Phase ledger, order history, bug fixes, verification queue. |
| `GET /status`, `GET /readiness`, `guard-state.json`, `paper-trading-rules.yaml` | Live, mutable state — always wins over any doc, including this one and `CLAUDE.md` itself (see `CLAUDE.md §0`). |

## Safety posture (summary — `CLAUDE.md §3` is authoritative)

- Paper account only. Stocks/ETFs only. No shorting, no options, no leverage, no crypto.
- `/order` is permanently HTTP 403.
- Order submission requires three independent kill switches all true/present at once
  (`IBKR_ALLOW_ORDERS`, `paper-trading-rules.yaml`'s `enforced`, and an H1 approval token
  only the human operator holds) — while any one is off, submission is structurally
  blocked before it reaches IBKR.
- The only order path is `/order/preflight` → `/order/approve` → `/order/submit`, with
  manual human approval required at the approve step. Preflight is validation-only and
  never returns an executable payload.
- No automation: every order cycle starts because a human explicitly starts it.

## Layout

| Path | Role |
|---|---|
| `bridge.py` | FastAPI service — the hard safety boundary; the only thing that talks to IBKR |
| `guard.py` | Deterministic risk engine — gates, sizing, state, approvals (Tier 1) |
| `monitor.py` | Read-only reconciliation and alerting |
| `bundle_audit.py` | Audit bundles, verification, release tags |
| `ibkr_operator.py` | Read-only operator CLI (`ibkr-operator`) — checklist, daily-report, doctor, and a large family of read-only checkpoints |
| `hermes_advisory.py` | Advisory-only Hermes (trade research) adapter — never touches order endpoints |
| `strategy_v1_1_core.py` | Pure, deterministic strategy evaluation library (no I/O, no side effects) |
| `dry_run_scenarios.py`, `approval_ui.py`, `ibkr_status.py`, `model_routing.py`, `openclaw_routing_adapter.py` | Supporting tooling |
| `systemd/` | Unit files for the live bridge, approval UI, and heartbeat timer |
| `docs/`, `scripts/` | Strategy proposals/governance docs; CI and pin-verification scripts |
| `tests/` | Test suite — see below |

`bridge.py`, `guard.py`, `monitor.py`, and `bundle_audit.py` are Tier 1: safety-critical
edits to these require the routing policy's Tier-1 model and an explicit, reviewed,
git-tagged merge — see `CLAUDE.md §6` and `RUNBOOK.md`.

## Running the tests

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt pytest
bash scripts/run-ci-portable
```

This runs the curated suite registered in `scripts/run-ci-portable` (excludes tests marked
`integration`, `live`, or `acceptance`, which need a real host — a live bridge, a
`hermes` CLI, systemd, or a `~/.openclaw`-style filesystem layout — and aren't portable to
a bare checkout). Requires Python 3.12+ (this codebase uses PEP 701 f-string syntax that
doesn't parse on 3.11).

Lint (the correctness-relevant subset — see `pyproject.toml`):

```bash
ruff check .
```

## Contributing / editing

Read `CLAUDE.md` first. It is the actual operating contract for this codebase — precedence
rules, what "Tier 1" means, what Werner/Hermes may and may not do, and why. Anything in
this README that conflicts with it is this README being wrong.
