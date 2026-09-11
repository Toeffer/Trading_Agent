# Remediation implementation ledger

Baseline: `9d863ba88077e3bf4e92d6ea7d0365128a98856c`.
Branch: `remediation/durable-paper-execution`.
The original checkout and audit results are preserved outside this checkout.

## Accepted scope

Seven stages: portable test baseline; immutable approvals; durable single-use
execution; complete risk and broker outcomes; runtime/OS boundaries; modular
application; deployment acceptance and evaluation preparation. Linux/systemd
runtime, Windows development. Human approval and 300-second expiry remain.
No live trading, automatic recovery orders, strategy optimization, or new
subscriptions. The later 60-trading-day study is not part of implementation.

## Progress as of 2026-09-11

The implementation is a release candidate on the remediation branch.
No release has been tagged and no deployment or broker order has been performed.
Implementation below does not imply that the corresponding release gate passed.

Draft PR: https://github.com/Toeffer/Trading_Agent/pull/24 (base `master`).
The first candidate commit is `ad69f28381c4d897384c7f6de157389db1b0c757`.

| Stage | Implemented locally | Remaining gate or work |
| --- | --- | --- |
| 1. Test baseline | Isolated branch; Python 3.12.10 toolchain; discovered portable tests; Linux/Windows CI configuration; UTF-8 and LF handling; behavioral regressions | Passing Linux/Windows runs recorded below; require green checks on the current PR commit |
| 2. Approval binding | Immutable order snapshot; proposal binding and price constraints; durable pending creation; H1 authorization; complete approval UI | PR review; current-commit contract validation is part of CI |
| 3. Durable execution | SQLite schema 3, unique intents, reservations, account evidence revisions, identity-based fill accounting, holdings anchors, outbox and legacy quarantine | Real stopped-service migration and broker reconciliation; final concurrency/crash review |
| 4. Risk and broker outcomes | Shared account risk evaluator; explicit valuations and FX; close-only SELL; staged BUY parent with protective child; separate broker evidence | Schema 3 accounting repairs and regressions implemented; complete CI and validate with the real paper gateway |
| 5. Runtime boundaries | One bounded broker loop; explicit startup/settings; token helper; separate systemd identities and firewall templates; host-check tooling | Install and verify actual Linux ownership, permissions, gateway restrictions and release/configuration identity |
| 6. Refactor | Package boundaries; thin original entry points; shared CLI registry and command groups; extracted checkpoint harnesses; strict types on new boundaries | Legacy preflight delegates to the application; 601 CLI helpers extracted; one-time transformation scripts removed; complete regression verification |
| 7. Release and evaluation | Migration/rollback instructions; deterministic snapshot export/replay; preregistration preparation; acceptance-evidence validator | PR review and release tag, current-commit CI, host verification, human paper BUY/stop/SELL exercise, reconciliation and relock |

## Validation history (per-commit results)

- Earlier complete discovered portable run: **3,756 passed, 8 failed, 2 skipped,
  390 deselected**, with **3,150 subtests passed**. The eight failures were
  assertions tied to the earlier implementation; their fixes require a new
  complete run before the suite can be described as passing.
- Subsequent verification of all new behavioral contracts and the files with
  the eight prior failures: **205 passed, 1 skipped, 1 deselected**.
- Latest execution, persistence, HTTP, runtime, migration, replay and historical
  preflight contract verification: **103 passed, 3 deselected**.
- Strict mypy: **42 source files checked successfully**, with explicit exclusions
  for retained legacy modules. Repository Ruff check passed.
- Compared **25 historical artifact files** with baseline Git bytes: unchanged.
- Complete Linux/Windows results are recorded below. The draft PR checks show
  the result for its current commit. Intermediate CLI extraction failures remain
  in local logs as history; they have not been relabeled as passing evidence.
- Additional review repairs: read-only tools refuse schema migration; SQLite
  upgrades back up the old schema first. Cold CI type checks now explicitly
  exclude historical root imports outside the typed execution boundaries.
- CLI compatibility rerun: **99 passed, 48 deselected**. Historical source-check
  repairs and executable mutation-detection negative controls: **16 passed**.
- Local fake-broker round-trip tests exercise BUY, protective-stop evidence,
  explicit cancellation evidence and separately approved close-only SELL.
  They are not evidence of actual paper acceptance.

Logs are retained locally under `.test-results/`. The original failing audit
and historical artifact bytes remain preserved; historical seals were not
rewritten to turn the audit into passing evidence.

The Linux host/SSH alias and explicitly approved paper-account identity have
been requested and are still pending. Do not provide secrets in the status
ledger. Deployment instructions are in `docs/REMEDIATION_RELEASE.md`.

## Validation and operational boundary

All local broker tests use fakes or blocked network connections. Deployment,
credentials, host state and human paper acceptance must be verified separately;
local passing tests will never be reported as evidence of deployed readiness.
Orders remain disabled until all execution repairs pass together.

Latest follow-up regressions: **22 passed** (read-only tools, pre-upgrade backup,
accounting and executable mutation checks). Cold type checking passes locally;
the initial CI type failure is addressed in the follow-up candidate.


## Clean-run follow-up

The diagnostic local run completed with **3,783 passed, 12 failed, 2 skipped,
390 deselected and 3,150 subtests passed**. All twelve failures were historical
source checks already repaired and separately verified; the run started before
those fixes and is not final-candidate evidence.

CI for `917fb8a020f3cfc488205d6f2b1048b83831164d` passed compilation, lint and
cold strict typing on both operating systems. Its complete suites found two
Linux fixture failures and fifteen Windows fixture failures: missing temporary
paths, a missing backup source fixture, and an assumption about wall-clock
resolution. Explicit temporary paths, source setup and a controlled clock now
pass **28 focused checks** without excluding any tests.

The account snapshot now checks application open-order contract identity and
remaining quantity against the immutable plan and verified fills before risk
reservation. A failing behavioral reproduction preceded the repair; **23 focused
accounting, capacity, broker-snapshot and round-trip tests pass** afterward.
The next commit requires fresh complete Linux and Windows CI before tagging.

CI run [34588494267](https://github.com/Toeffer/Trading_Agent/actions/runs/34588494267)
passed on Linux and Windows for commit
`4d6a438348ed9120dea41538ce7fa2808d7610eb`: **3,805 passed, 2 skipped,
390 deselected and 3,150 subtests passed** on each platform. Compilation,
repository lint and cold strict type checking also passed. Both jobs retained
their test artifacts. This supersedes the earlier failing validation results;
those results remain historical evidence.

Final review found that empty or reused labels on external open orders could
collapse daily-capacity reservations. Three failing adapter regressions preceded
the repair: external orders now use broker permanent identities, and unavailable
or duplicate identities block the snapshot. **26 focused tests pass** after this
repair. Fresh CI against the follow-up commit remains required. No PR review,
host verification or human paper acceptance has been recorded yet.

Skip audit: the historical heartbeat freeze assertion incorrectly depended on
an installed checkout before reading repository source; it now always runs.
The installed user-service comparison is explicitly marked `host`, so discovering
an installed production unit cannot activate it during portable testing. This
accounts for the prior two skips; host checks require `--run-host`.


## Candidate handoff

Implementation and focused validation are complete; all review-discovered
accounting defects have behavioral regressions. Complete portable suites run on
both operating systems for every candidate commit. The PR remains a draft for
review; no review approval or release tag is implied by passing CI.

The two prior portable skips were resolved explicitly: the repository heartbeat
assertion now executes, and the installed-service comparison requires host opt-in.
Their focused rerun passed **44 tests, with 43 operational tests deselected and
no skips**. The full runner now excludes **391 explicitly classified operational
tests**. Original audit logs and all 25 historical artifact bytes remain intact.

Remaining operational work requires the designated Linux host/SSH alias and
approved paper-account identity: stopped-service backup/migration, broker
reconciliation, actual ownership and gateway checks, then the human paper
BUY/confirmed stop/explicit stop cancellation/separately approved close-only SELL
exercise. Capture real evidence and relock before recording deployed acceptance.
The replay example and release/configuration-pinned preregistration generator are
ready; operator expectations and acceptance evidence remain intentionally empty.
