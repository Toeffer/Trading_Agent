# Persistent autonomous agent

The first autonomy milestone is runnable: a controller consumes observations,
uses existing strategy tools, persists its reasoning and performs a complete
position lifecycle in a local simulator. No individual order approval is needed
inside that simulator. Production broker execution retains its existing manual
approval path.

## Run the demonstration

Use Python 3.12 and the repository's pinned development dependencies:

```text
python -m pip install -r requirements-dev.txt
python -m trading_agent agent demo --workspace agent-demo
```

The workspace must not already exist. The command writes `mandate.json`,
`observations.jsonl`, `agent.sqlite3` and `report.json`. It demonstrates:

1. A recorded opinion causes the agent to abstain.
2. The agent discovers a trend/relative-strength candidate and saves its decision.
3. A new controller instance recovers the pending decision and executes it once.
4. The agent holds the position while its thesis remains valid.
5. A recorded exit opinion causes a full close, with costs and FX accounted for.
6. Replaying the entry observation creates no additional fill.

All prices, histories and opinions in this demo are synthetic fixtures. The
result demonstrates behavior and accounting, not strategy performance. The
demo's `model` value identifies a fixture; no model service is invoked.

## Use your own recorded observations

Create a new mandate and database for each configuration. Start from the demo's
generated files or `trading_agent/agent/demo.py`, which defines the complete
version 1 example. Then run:

```text
python -m trading_agent agent init --database my-agent.sqlite3 --mandate mandate.json
python -m trading_agent agent run --database my-agent.sqlite3 --events observations.jsonl --max-events 1000
python -m trading_agent agent status --database my-agent.sqlite3
python -m trading_agent agent pause --database my-agent.sqlite3 --reason "Review input quality"
python -m trading_agent agent resume --database my-agent.sqlite3
python -m trading_agent agent recover --database my-agent.sqlite3
```

`run` reads a finite JSONL stream. It first completes any previously prepared
simulation cycle, then processes at most `max-events` new cycles. Identical
completed observations are replayed without counting against that budget.
Re-running the same file therefore progresses beyond a previously processed
prefix. Successfully committed earlier lines survive an invalid later line;
fix the input or supply a new stream and rerun. Reusing an event ID with different
content is an error, not a correction mechanism.

`recover` uses the exact recorded decision and does not call the reasoner again.
Pause state survives restart and blocks pending execution. Resume clears only
the simulation pause. Status opens the agent database read-only and includes
the portfolio, pending work, decision histories and fills. It independently
reconstructs cash and quantities from the fill ledger and compares state with
the last completed cycle. A mismatch blocks new decisions and recovery.

The input stream is currently the event source. A scheduled market feed,
continuous service, external model invocation, broker submission and live
mandate activation are later adapters, not features implied by this command.

## Mandate and data contract

The simulation mandate pins its full configuration hash for the database's
lifetime. It specifies account, currency pair, initial cash, active time window,
instrument identities and sectors, strategy version, risk limits and cost model.
Risk values ending in `_fraction` are decimal fractions (`0.05` means 5%).
Slippage uses basis points. Commission is a fixed amount per simulated order in
quote currency. `base_to_quote` is quote currency units per base currency unit.

Only `mode: simulation` is implemented. Supplying `paper`, `live` or another mode
fails before creating a database. The simulator has its own SQLite application
ID and schema and refuses the existing execution database. New initialization
is exclusive and will never overwrite an existing file.

Each observation supplies:

- A unique `event_id`, matching account and timezone-aware `at` timestamp.
- Positive `base_to_quote`; the rate must be one when both currencies match.
- Bid/ask, observation time and daily history for every mandated instrument.
- Reference-market daily history used by the regime and volatility tools.
- Optional recorded opinions keyed by symbol.

New observations must be strictly chronological. Quotes must be available at
the observation time and no more than 30 seconds old. Every daily bar has
`ended_at` and `available_at`, plus OHLCV. Availability cannot precede bar end or
follow the decision time. Bars are strictly ordered with one row per UTC date;
all series end at the same time and satisfy the configured maximum bar age.
Missing quotes, crossed markets, non-finite values, future data and unknown
fields are rejected before recording a cycle. Input lines are limited to
5 MiB of decoded text, histories to 4,096 bars and the universe to 32 symbols.

This is a validated recorded-input contract, not provider authenticity or a
complete point-in-time market database. Exchange calendars, splits, dividends,
delistings and the accuracy of external timestamps remain the data provider's
responsibility. Do not mix adjusted history and unadjusted execution prices
without an explicit data convention.

Recorded opinions contain only `action` (ENTER/HOLD/EXIT), `thesis`,
`invalidation`, `sources`, `model` and `observed_at`. They cannot supply quantity,
leverage, an approval secret or an executable order. Opinions are limited to the
last 24 hours and must include source identifiers. Their exact input is retained
for later evaluation. Supplying old documents to a current model does not by
itself establish unbiased historical reasoning.

## Reasoning and risk

`agent-trend-v1` is a new, deliberately small baseline built from the existing
v1.1 pure tools. It does not claim to implement every discretionary v1 rule or
activate the existing advisory proposal.

- Reference-market 200-day SMA and 12-month momentum determine regime.
- Existing 60-bar relative-strength ranking selects the strongest half of the
  mandated universe. Entry also requires price above its 20-bar SMA.
- Reference volatility and regime reduce the available exposure budget.
- A recorded HOLD or EXIT opinion prevents a flat-position entry. ENTER still
  requires the numerical setup and policy checks to pass.
- An existing position exits on a triggered stop, recorded EXIT, holding-period
  expiry (calendar days), valid risk-off regime or trend invalidation.
- Missing strategy history yields HOLD; missing regime evidence does not by
  itself manufacture a valid risk-off exit. Protection remains independent.

The `Reasoner` protocol provides a future integration point for Hermes. Version,
decision timestamp, universe coverage, action schema and budget are validated.
Numerical sizing, cash constraints, account checks, exposure, sector capacity,
loss halts and daily trade limits remain outside the reasoning provider.

Each ENTER/EXIT is checked by the shared `trading_agent.risk.evaluate` using
immutable plan and portfolio types. The simulation's standalone mandate supplies
its policy; production YAML and H1 state are neither read nor changed by this
controller. Existing type vocabulary (`paper` and `realtime`) is used only
inside that pure evaluator. All public agent results and fills identify
themselves as simulation.

## Simulation and restart guarantees

One database permits one pending cycle. Preparing a cycle records the input,
pre-decision portfolio hash, exact reasoning output and its hash under a SQLite
write transaction. Completion checks these identities and commits fills, cash,
holdings and cycle status in a second atomic transaction. Concurrent controllers
serialize through SQLite. A crash before preparation commits leaves no cycle;
a crash after preparation reuses that decision; a crash during completion rolls
back all simulation effects. Completed replay returns the saved result.

The simulator buys at ask plus slippage and sells at bid minus slippage. It sizes
whole shares at the adverse price, includes commission in available cash and
marks holdings at bid in base currency. Each entry retains its thesis, entry
cost, stop and opening time. Realized P&L includes entry and exit commissions
and the FX conversion at each fill. Cash does not accrue interest in this
milestone.

A triggered protective stop closes at the observed adverse bid, including
slippage; a gap is not filled optimistically at the stop price. Stop execution
is enforced independently of a provider HOLD. It is an already-existing local
protection action, so it does not consume another application trade or require
the discretionary daily-capacity gate. Discretionary exits retain the existing
shared evaluator's daily trade limit. Daily and weekly anchors carry forward
the previous observed equity so a new period does not erase an overnight gap.

Fills are immediate and complete; there is no order-book depth, queue model,
partial-fill simulation, intrabar path reconstruction or market-impact model.
Stops are checked only at supplied observations. An atomic local close removes
the simulated stop and position together. These guarantees must not be applied
to broker cancellation/replacement, where acknowledgements, external state and
uncertain transmission require the existing durable execution machinery.

## Validation and next adapter

`tests/test_agent_controller.py` covers a full costed round trip, persisted
reasoning, recovery without reinvocation, duplicate/concurrent delivery,
rollback on fill-storage failure, pauses, event ordering and integrity, risk
capacity, gap stops, malformed or future data, small accounts and bounded CLI
restart. The normal discovered CI suite includes it.

The next milestone is a recorded/current-data adapter and persistent shadow
service using this same decision contract. Automatic paper execution then
requires a reviewed mandate-authorization path, broker-aware position management
and reconciliation of actual fills. It must not obtain automation by handing
the controller the human H1 credential. The product objective remains an agent
that eventually executes and manages eligible real trades automatically.
