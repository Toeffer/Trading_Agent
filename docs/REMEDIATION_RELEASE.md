# Durable paper release procedure

This branch is an implementation candidate, not a verified deployed release.
The audited baseline is 9d863ba88077e3bf4e92d6ea7d0365128a98856c.
Historical audit results and checkpoint seals remain historical evidence.

## Protected-state policy

The execution service may create a **pending** approval from a validated,
immutable plan. This narrow operation cannot approve, deny or transmit it.
Those actions require H1 authentication. Expiry remains exactly 300 seconds.
SQLite is authoritative. JSON exports are compatibility evidence only; old
JSON files must never be supplied to the submission path as authority.

Schema version 3 adds account evidence revisions, durable external-fill
identities and holdings anchors. A reservation uses unfilled quantities only
after a broker snapshot accounts for the verified fills. An intervening event
or unexplained holdings change blocks intake. Each parent entry or separately
approved exit counts once on its first fill's UTC date. Its linked protective
stop does not create another application trade.

External orders require broker identities and complete fill history; a port,
account prefix or aggregate count cannot establish that history. An upgrade
from schema 1 or 2 retains historical fills and quarantines existing executions
for H1 broker reconciliation. Missing evidence remains unresolved.

`POST /order/account/reconcile` accepts only `{"symbol":"AAPL"}` and requires
H1. It fetches broker evidence through the account's bounded owner loop and
cannot accept caller-supplied fills, counts or recovery orders. The privileged
helper exposes it as `reconcile-account AAPL`. An imported daily count is
reconciled only when verified order identities account for that count exactly.
The original aggregate is retained in the outbox; no order switch is enabled.

New decision snapshots use version 2 and include evidence revision, verified
fills and coverage. Version 1 records remain readable; missing evidence is
reported explicitly instead of being fabricated during replay.

## Installation and ownership

Create separate system users `ibkr-exec`, `ibkr-ui`, `ibkr-gateway` and an
advisory identity. None may share a UID, have sudo privileges, or write code or
configuration. Create `ibkr-proposals` for advisory write / execution read
access to proposals. Use root-owned release directories under
`/opt/trading-agent/releases/<commit>` and a root-owned `current` symlink.
Build the pinned Python 3.12.10 environment before making the tree read-only
to all service users. Deploy the templates in `deploy/`; substitute paths,
ports and UIDs explicitly and validate with `systemd-analyze verify` and
`nft --check --file`. Review the existing host firewall before incorporating
the gateway table. Do not replace unrelated firewall rules.

Only `ibkr-exec` may write `/var/lib/ibkr-bridge` (0700). Configuration is
root-owned and execution-readable, never advisory-writable. The Gateway's
own state belongs only to `ibkr-gateway`. Configure Gateway for the explicit
paper account and localhost API access. The configured account must match
the connected account; ports and account prefixes do not grant permission.

Generate the H1 secret outside shell history and argv. Store its hash in the
bridge configuration and the secret in `/etc/ibkr-bridge/h1_token`, root:root
0600. Permit only designated **human** operators to run the fixed root-owned
`scripts/h1_client.py` with the release's fixed Python interpreter and `-I`.
Do not grant that sudo rule to any advisory or service identity. The helper
validates the action/ID, refuses redirects/proxies, and keeps the secret in
process memory. Existing token-bearing curl command examples are obsolete.
Access the loopback approval UI through a human-controlled SSH tunnel.

## Migration and locked rollback

1. Stop intake and the old execution service. Disable both order switches.
   Record all broker orders, fills and holdings. Verify no old worker remains.
2. Back up legacy state byte-for-byte to a new directory; record SHA-256 hashes.
   Back up SQLite with its backup API while the execution service is stopped.
3. Import legacy records with provenance into a new database. Unused approvals
   expire; ambiguous submissions stay quarantined. Verify the imported daily
   and weekly baselines and counts against broker evidence.
4. Reconcile before enabling. Missing or ambiguous broker history is a blocker,
   not permission to assume no transmission. Do not clear quarantine with
   hand-edited JSON or SQL.
5. Start the candidate locked; verify deployed commit, configuration hash,
   account identity, H1, filesystem ownership and negative gateway-access tests.
6. Once any broker transmission has occurred, **never restore an older database
   snapshot**. Rollback means stop intake, relock, preserve the latest database
   and broker evidence, and run only a schema-compatible reviewed release.
   An incompatible old binary remains stopped until a forward repair is ready.

## Required release evidence

Portable CI must pass on Linux and Windows; retain JUnit results and the full
behavioral suite. Review the diff and migration rehearsal, then create a tag
identifying the reviewed commit. A tag alone is not deployment verification.
Capture actual host permissions, effective unit configuration, firewall rules,
negative connectivity from advisory/UI identities, and positive execution
connectivity. Compare `/execution/readiness` identities with the deployed files.
Service readiness does not guarantee usable market data for a particular order.

## Human paper acceptance

The designated operator supplies a proposal and expectations, enables only the
reviewed paper window, and initiates the smallest permitted BUY with a fresh
H1 approval. Record parent acknowledgement, actual fills and separately
confirmed stop identity/quantity/price. `PendingSubmit` and `PendingCancel`
are not protection. Stop immediately on uncertainty and request reconciliation;
never retry an uncertain execution or automatically cancel/flatten it.

The operator explicitly cancels the stop in Gateway/TWS and confirms terminal
cancellation, then requests H1 reconciliation. Create and approve a separate
close-only SELL after confirming holdings and no competing open SELL. Reconcile
all fills, holdings, orders and reservations. Relock both switches and preserve
the acceptance evidence. Do not call this exercise passed until these real
human/broker observations exist. No live orders or subscriptions are authorized.

## Later evaluation

Replay uses versioned timestamped snapshots and the same risk evaluator. Report
policy decisions separately from missing input, operational failures, costs and
slippage. Create a new preregistration tied to the verified release; the operator
must supply expectations before the later 60-trading-day strategy study.
