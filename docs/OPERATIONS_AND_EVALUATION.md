# Operational and evaluation follow-up

The implementation remains paper-only, H1-approved, MKT-only and disabled by
default. No host or broker acceptance is implied by CI or a candidate tag.

## Monitoring

Read `/execution/readiness` or `/status`. These return the existing blockers plus
`operations`, `broker_queue` and `operator_actions`. No monitoring call transmits
an order or clears a blocker. Queue saturation is distinguished from account
disconnection and an unavailable status observation.

`operations` contains account-scoped unresolved execution count, the oldest
current unresolved intent's age measured from creation, and separate last
successful account/individual execution reconciliation timestamps. Historical
execution events without normalized verification metadata yield no successful
timestamp. An account reconciliation timestamp never asserts that all execution
intents are resolved. Inspect the unresolved count as well.

Export depth and oldest age cover the whole execution service's durable outbox.
An export error or backlog older than 30 seconds supplies `EXPORT_BACKLOG` guidance.
The database remains authoritative. Inspect disk space and permissions, repair
export access, and let the idempotent exporter drain the backlog. Export alerts
do not grant submission or recovery authority.

Queue usage includes tasks still cancelling after their callers time out. Slots
are released only when the actual owner-loop task completes. An order operation
that outlives its caller retains its durable intent and must not be resubmitted.

## Disposable migration rehearsal

Use the release's pinned Python environment:

```text
python -m trading_agent state rehearse-upgrade --source DATABASE --workspace NEW_DIRECTORY
```

This opens the source read-only through SQLite's backup API, retains a backup,
upgrades a second copy, invalidates unused approvals, verifies database integrity,
foreign keys, execution identities and fill preservation, and exercises outbox
export. It imports no broker client. The new directory is retained for review.
It refuses an existing destination. A failed rehearsal requires investigation;
never substitute its copy for current authoritative execution state.

Actual migration still requires stopped intake, host permissions and reconciliation.
Never restore an older database over authoritative state after broker transmission.

## Replay and commission evidence

Newly recorded decision snapshots use version 3, recording the risk decision.
Export reads decisions and current execution evidence within one SQLite read
transaction. It adds identified parent fills, their observation cutoff, execution
and protection state, and uncertainty indicators. Protective-stop fills remain
separate execution evidence and are not counted as parent entry slippage.
Historical version 1/2 snapshots are preserved and remain readable.

```text
python -m trading_agent state export-snapshots --database DATABASE --output NEW_FILE
python -m trading_agent evaluation replay NEW_FILE
```

Version 3 replay returns `decision_matches_recorded`, separately from fill evidence
issues, execution state, protection state, costs and slippage. It rejects missing,
non-finite, excessive, mismatched, conflicting or improperly timestamped fill
evidence from the slippage calculation. Identical duplicate fills count once.
No missing commission is assumed to be zero.

To evaluate costs, create a new derived copy of the exported record. Add
`commissions` entries with `broker_execution_id`, ISO currency and decimal-string
`amount`, plus `commission_provenance` identifying the operator-verified statement
and its hash. Preserve the unmodified export and statement. Identical commission
rows count once; conflicts and unknown fill identities are reported. Amounts remain
grouped by currency, with no assumed exchange rate. Negative commissions may
represent rebates. `cost_coverage_complete` describes evidence coverage only;
statement authenticity still requires operator verification.

After actual paper acceptance, generate a release/configuration-pinned draft:

```text
python -m trading_agent evaluation preregister --release COMMIT_SHA --configuration-hash CONFIG_SHA256
```

The operator supplies expectations, acceptance evidence and study criteria before
the later 60-trading-day observation period. No strategy parameters are optimized
by these tools.

## CLI maintenance and release checks

Workflow, governance and research handlers now import concrete helper owners.
The public alias facade remains compatible. Shared registry, argument definitions
and output formatting are checked under strict mypy; legacy dictionary contents
remain gradually typed. Other helper exemptions remain explicitly listed.
CI additionally checks unused imports/variables on the migrated shared modules
and new operational/evaluation modules. No global lint suppression was added.

Required release evidence remains Linux/Windows portable CI, diff review, a
migration rehearsal, actual Linux identity/permission/gateway checks, and the human
paper BUY/confirmed-stop/explicit stop cancellation/separately approved close-only
SELL exercise. Reconcile all state and relock afterward.
