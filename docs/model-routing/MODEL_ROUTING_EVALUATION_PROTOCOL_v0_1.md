# Model Routing Evaluation Protocol v0.1

**Governance ID:** `model_routing_governance_v0_1`
**Phase:** 18R1
**Status:** DRY_RUN_ONLY — advisory, no model invocation

---

## 1. Purpose

This protocol defines a future offline comparison framework for evaluating
model routing decisions across the four approved logical models:

- **gpt-5.5** (HERMES_DEFAULT)
- **gpt-5.6-sol** (HERMES_ESCALATION)
- **deepseek-v4-pro** (OC_DEFAULT)
- **kimi-k3** (OC_ESCALATION)

Phase 18R1 runs no benchmark. No model is called. No pricing is frozen.
No benchmark winner is frozen.

---

## 2. Evaluation Dimensions

Each routing scenario shall be scored along these dimensions:

### 2.1 Correctness
- First-pass targeted-test success (bool)
- First-pass portable-CI success (bool)

### 2.2 Safety
- Forbidden-file changes (count, enumerated)
- Specification violations (count, enumerated)
- Safety-boundary violations (count, enumerated)

### 2.3 Efficiency
- Human correction turns (integer)
- Total input tokens (supplied externally by the caller)
- Total output tokens (supplied externally by the caller)
- Estimated cost (supplied externally, not frozen)
- Elapsed time (seconds, wall-clock)

### 2.4 Deterministic Classification
Each run produces one of:
- `PASS_ALL` — all dimensions within thresholds
- `PASS_WITH_NOTES` — minor warnings only
- `FAIL_SAFETY` — safety boundary violated
- `FAIL_CORRECTNESS` — correctness dimension failed
- `FAIL_EFFICIENCY` — excessive cost or time
- `INCONCLUSIVE` — insufficient data or contradictory results

---

## 3. Phase 18R1 Explicit Limitations

- **No benchmark execution** — Phase 18R1 is schema, governance, and decision
  logic only.
- **No model is called** — The decision engine selects a logical model ID;
  invocation is deferred to Phase 18R2+.
- **No pricing is frozen** — `pricing_frozen: false` in the catalog.
- **No benchmark winner is frozen** — `benchmark_rank_frozen: false` in the
  catalog.
- **Evaluation results cannot change trading authority** — All routing is
  advisory only (`advisory_only: true`).
- **Human review remains required** — `human_final_authority: true` in all
  decision outputs.

---

## 4. Future Execution Protocol (Phase 18R2+)

When model invocation is authorized in a future phase:

1. The routing decision selects the logical model.
2. The OpenClaw runtime supplies credentials and API configuration.
3. Each model receives identical prompts for each test scenario.
4. Results are scored against the criteria above.
5. A structured evaluation report is produced.
6. Human review confirms or overrides the routing recommendation.

---

## 5. Governance

| Aspect | Value |
|--------|-------|
| Version | 0.1 |
| Phase | 18R1 |
| Model invocation | Not authorized |
| Pricing frozen | false |
| Benchmark rank frozen | false |
| Trading authority change | Not permitted |
| Human review | Required |
| Next phase | PHASE18R2_OPENCLAW_ROUTING_ADAPTER |
