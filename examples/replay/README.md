# Offline replay example

Run `python -m trading_agent evaluation replay examples/replay/synthetic-v2.jsonl`.
The expected result is in `expected-v2.json`. All account, contract, release and
fill data in this example are synthetic. The zero release identity is an
explicit fixture marker, not a reviewed release. The example sends no orders.

For actual evaluation, export recorded snapshots with
`python -m trading_agent state export-snapshots --database DATABASE --output NEW_FILE`
and replay that file. Keep operational failures, transaction costs and slippage
separate from the strategy decision.

After verified deployment and paper acceptance, generate the preregistration
draft with `python -m trading_agent evaluation preregister --release COMMIT_SHA
--configuration-hash CONFIG_SHA256`. Both identities must come from the verified
release. The operator supplies expectations, study dates and acceptance evidence;
the generator deliberately leaves those fields empty.


The version 3 example adds identified fills, a recorded decision and separately
identified commission evidence:
`python -m trading_agent evaluation replay examples/replay/synthetic-v3.jsonl`.
Compare with `expected-v3.json`. Its costs and broker identities are synthetic,
and its zero release hash is a fixture marker. Historical version 2 files remain
unchanged. See `docs/OPERATIONS_AND_EVALUATION.md` for actual evidence requirements.
