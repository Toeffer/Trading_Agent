# Main consolidation — 2026-10-07

The owner requested committing and pushing the consolidated current IBKR work
to `main`, including remediation, the persistent agent controller, and newer
research. This is source integration, not deployment or paper-trading acceptance.

## Included history

| Source | Included tip | Role |
|---|---|---|
| Previous `main` | `9a2a128780e0443ccd1778acc8d43a495b56cd20` | Retired crypto scaffold |
| `master` | `9d863ba88077e3bf4e92d6ea7d0365128a98856c` | IBKR baseline |
| `remediation/durable-paper-execution` | `14c4f109ae2f28cfc2789cdc38a12e35ff43d553` | Durable execution and package refactor |
| `feature/persistent-agent-controller` | `b084772dc6997b723df77d012b2d4a3a71a6ffa4` | Persistent simulation agent; includes remediation |
| `claude/repo-check-ghkkwt` | `9789a66ef76fe4468564834da49b091cfaed6ba1` | FX/market-data corrections, simulator, Hermes sizing, research and reviews |

The research tip includes `claude/repo-review-xsn87x` at
`f2c8aa2cf4a7b5b9fd0f4a8681fbf4d2cb9e20de`. The histories are merged without
rewriting the earlier `main` commits.

Four previously uncommitted legacy files were preserved before archiving:
`CLAUDE.md`, `config/sae-config.yaml`, `tests/test_position_sizing.py`, and
`tests/test_sae_config.py`. Their content is under `archive/crypto-scaffold/`.
The original checkouts and their working files were left intact.

## Integration decisions

- Keep the durable execution service, typed plans, SQLite reservations, and the
  bounded `BrokerLoop` as the active execution architecture. Root `bridge.py`,
  `guard.py`, and `ibkr_operator.py` remain compatibility entry points.
- Port research FX conversion and finite-price handling into the package's
  compatibility modules. Port Hermes sizing and research/review commands into
  the existing operator command groups and lazy registry.
- Adapt the wire simulator to the durable adapter's account, portfolio, quote,
  contract, and order requests. Its rehearsal uses a disposable risk baseline,
  H1 token, state/proposal directories, and ephemeral bridge/gateway ports.
- Assert filled/partial/unknown states and protective-stop evidence
  through the authoritative execution API. Historical `/monitor/*` reports
  describe compatibility JSON views; they are not SQLite execution authority.
  Rejected brackets with cancelled protection remain unresolved for human review;
  the rehearsal verifies the retained cancellation evidence and blocked retries.
- Preserve portable test isolation, permitting connections only to ephemeral
  loopback listeners registered by the test tree. Production and external
  destinations remain blocked. Research regressions target the package rather
  than inspecting retired root-module implementations.

Use `python scripts/run_ci.py`, the Ruff gates in `.github/workflows/ci.yml`,
and `python -m mypy --no-incremental trading_agent` to validate this tree.
Local and CI verification does not replace the migration and paper acceptance
procedure in [REMEDIATION_RELEASE.md](REMEDIATION_RELEASE.md).

## Local verification

Windows, Python 3.12.10, pinned development dependencies:

- Portable discovery: 4,022 passed, 3,150 subtests passed, 391 operational tests
  deselected. One symlink test skipped because the local Windows account lacks
  symlink creation privileges.
- All CI Ruff gates pass; strict mypy reports no issues in 53 package modules.
- Compilation passes for the package, compatibility entry points, research
  modules, and simulator. All five simulator scenarios pass.
- Research/CLI regressions rerun after explicit UTF-8 text handling: 100 passed,
  with the same single Windows symlink skip.
- All four original uncommitted files match their archived working copies by
  SHA-256. Git whitespace checks pass and no merge conflicts remain.
