# P1–P6 Rulings

Status: Chris-approved ruling set.  
Scope: rulings only; no implementation in this document.  
Safety: no broker calls, no order enablement, no Tier-1 invariant change outside its own branch/tag.  
Baseline: `IBKR_ALLOW_ORDERS=false`, `rules.enforced=false`.  
Current baseline: ContextVar + fast approve canary + R1 tailnet approval UI complete.

## Ruling Table

| Item | Decision | Reason | Safety impact | Files expected | Test / done-when | Tier-1 impact | When |
|---|---|---|---|---|---|---|---|
| P1 | ACCEPT | Process hygiene: revert unapproved §3 invariant text, then re-add with Chris-approved wording and Tier-1 tag. This cleans process before other P items touch invariants. | Neutral on behavior; positive for process integrity. | `MEMORY.md` or invariant document. | Reverted text absent; re-added text matches Chris-approved wording and has a proper tag/note. | Yes — invariant text is Tier-1, but this is a process-fix only. | Now, first. |
| P2 | ACCEPT | Advisory-rail wording only. Clarify that close-only SELLs are exempt from the relevant advisory rails. Do not touch `gate_loss_halts()` because Gate E is a separate enforcement rail. | None — wording only, no code-path change. | Advisory rail document. | Wording matches Chris’s intent; grep confirms `gate_loss_halts()` untouched. | No. | Now, separate branch. |
| P2b | DECIDE EXPLICITLY | Separate from P2: decide whether Gate E loss halts should exempt close-only SELLs so a halt can never block an exit that reduces loss. | If accepted: positive because it prevents halts from trapping positions. If rejected: halts remain absolute and could block an exit. | `guard.py` / Gate E only if accepted. | Gate E logic reviewed; close-only SELL exemption added only if explicitly accepted. | Potentially yes — Gate E is a Tier-1 enforcement rail. | Separate analysis before P5. |
| P3 | ACCEPT | Add Gate H proposal discipline: proposals must live under `~/.openclaw/proposals/`, be validated, and fail closed when missing or incomplete. | Positive — prevents silent defaults and phantom proposals. | Proposal handler, validators, Gate H hooks, likely `guard.py` and tests. | Missing or incomplete proposal fails closed; valid proposal passes Gate H. | Yes — Gate H is a Tier-1 enforcement rail. | Now, separate branch. |
| P4 | ACCEPT | Documentation accuracy: the −10% threshold was decision input because it anchored “risk if held”; it must not be described as irrelevant or non-input. | Positive — correct risk documentation prevents wrong assumptions. | Risk note / decision document. | Note no longer describes −10% as irrelevant or non-input. | No. | Now, separate branch. |
| P5 | ACCEPT IN PRINCIPLE, DEFER | Broker-side bracket stops are approved in principle but blocked until Step 8. Implementation is complex: guarded EXIT must cancel/OCA-link child STP first; reconciliation must detect orphan stops; child stop must be GTC; STP→MKT gap risk must be documented; invariants must be amended; dry-run bracket/restart/orphan-stop scenarios must pass. | High when implemented — bracket stops can orphan, mis-link, or fire unexpectedly. Must not proceed without full test matrix. | Bracket logic, reconciliation, invariants, tests, docs. | Deferred until Step 8. Later done-when requires dry-run, restart, orphan-stop detection, OCA unlinking/cancel behavior, and documentation to pass. | Yes — multiple Tier-1 invariants will change. | Step 8 only. |
| P6 | ACCEPT | Every Hermes artifact must record the resolved model string. Tests must assert that the recorded Hermes model is not Werner’s model family. | Positive — prevents Werner from masquerading as Hermes in the audit trail. | Hermes adapter, Hermes artifact schema, tests. | All Hermes invocations record `resolved_model`; tests assert model is not Werner’s model family. | No — Hermes audit trail only. | Now, separate branch. |

## Implementation Order

No bundled changes. One item = one branch, one implementation, one test, one tag.

1. **P1**  
   Branch: `phase0-2-step5-p1-invariant-process-fix`  
   Reason: clean invariant process before other invariant-touching work.  
   Estimated scope: documentation/process fix only.

2. **P2**  
   Branch: `phase0-2-step5-p2-close-only-wording`  
   Reason: advisory wording only; must not touch Gate E.  
   Estimated scope: documentation only.

3. **P4**  
   Branch: `phase0-2-step5-p4-risk-note-fix`  
   Reason: documentation accuracy.  
   Estimated scope: documentation only.

4. **P3**  
   Branch: `phase0-2-step5-p3-proposal-discipline`  
   Reason: Gate H proposal discipline; fail-closed behavior.  
   Estimated scope: proposal storage, validation, tests.

5. **P6**  
   Branch: `phase0-2-step5-p6-hermes-model-audit`  
   Reason: Hermes audit integrity.  
   Estimated scope: adapter/artifact/test update.

6. **P2b**  
   Branch: TBD after explicit Chris ruling.  
   Reason: Gate E close-only exemption must be decided separately before P5.  
   Estimated scope: enforcement logic only if accepted.

7. **P5**  
   Branch: `phase0-2-step8-p5-bracket-stops`  
   Reason: broker-side bracket stops are deferred to Step 8.  
   Estimated scope: significant; blocked by P3, P2b, and Step 8 prerequisites.

## Gate-Level Summary

| Item | Touches | Tier-1 effect |
|---|---|---|
| P1 | Invariant text / §3 | Process-fix on Tier-1 text. |
| P2 | Advisory wording | No Tier-1 effect. |
| P2b | Gate E / `gate_loss_halts()` | Potential Tier-1 effect. |
| P3 | Gate H / proposals | Tier-1 enforcement rail. |
| P4 | Risk documentation | No Tier-1 effect. |
| P5 | Broker-side bracket stops / multi-gate behavior | Tier-1, deferred. |
| P6 | Hermes metadata / audit trail | No Tier-1 effect. |

## Hard Constraints

- All P items remain read-only rulings until Chris approves each implementation branch individually.
- No orders.
- No broker calls.
- No order window enablement.
- `IBKR_ALLOW_ORDERS=false`.
- `rules.enforced=false`.
- H1 canary and R1 tailnet approval UI must not regress.
- No Tier-1 invariant changes without explicit Chris-approved wording and a dedicated tag.
- P5 must not be implemented before Step 8.
