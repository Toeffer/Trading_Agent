"""Decision 11.6 — no autonomous learning channel in the advisory path.

`hermes_advisory.py` is stateless with respect to outcomes: no fill, P&L, or
past proposal re-enters a prompt. That property currently holds by
construction rather than by guarantee, so these tests pin it.

If it ever breaks, the effective strategy could adapt to outcomes without a
version bump, defeating strategy_v1.md section 16 versioning discipline.
"""

import ast
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
ADAPTER = REPO / "hermes_advisory.py"
sys.path.insert(0, str(REPO))

SOURCE = ADAPTER.read_text()
TREE = ast.parse(SOURCE)


def _func(name: str):
    for node in ast.walk(TREE):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"function {name} not found in hermes_advisory.py")


def _segment(node) -> str:
    return "\n".join(SOURCE.splitlines()[node.lineno - 1:node.end_lineno])


# ── The prompt must not carry outcome data ──────────────────────────────────


class TestPromptIsOutcomeFree:

    def test_build_prompt_exists(self):
        assert _func("build_prompt")

    def test_build_prompt_takes_only_baseline_and_request(self):
        """A third input channel is where outcome data would enter."""
        args = [a.arg for a in _func("build_prompt").args.args]
        assert args == ["baseline", "user_request"], \
            f"build_prompt signature changed to {args}; verify no outcome channel was added"

    def test_build_prompt_reads_no_files(self):
        body = _segment(_func("build_prompt"))
        for forbidden in ["open(", "read_text", "glob", "iterdir", "listdir", "json.load("]:
            assert forbidden not in body, \
                f"build_prompt performs I/O via {forbidden!r} — it must be a pure function of its arguments"

    @pytest.mark.parametrize("term", [
        "pnl", "p_and_l", "realized", "unrealized", "fill_price",
        "past_trade", "previous_outcome", "trade_history", "win_rate",
    ])
    def test_build_prompt_references_no_outcome_terms(self, term):
        assert term not in _segment(_func("build_prompt")).lower()


# ── Persisted proposals are write-only ──────────────────────────────────────


class TestProposalsAreWriteOnly:

    def test_proposals_dir_is_never_enumerated(self):
        """Proposals are persisted for audit, never read back into a decision."""
        for pattern in [r"proposals.*\.glob\(", r"glob\([^)]*proposals",
                        r"listdir\([^)]*proposals", r"iterdir\(\)"]:
            assert not re.search(pattern, SOURCE), \
                f"hermes_advisory.py enumerates the proposals directory ({pattern!r}) — " \
                "that would create an outcome feedback loop"

    def test_only_proposal_symbol_imported_is_a_writer(self):
        """Persistence goes through save_proposal_file; no reader is imported."""
        imported = set()
        for node in ast.walk(TREE):
            if isinstance(node, ast.ImportFrom):
                imported.update(a.name for a in node.names)
        proposal_syms = {n for n in imported if "proposal" in n.lower()}
        assert proposal_syms == {"save_proposal_file"}, \
            f"unexpected proposal symbols imported: {proposal_syms}"

    @pytest.mark.parametrize("reader", [
        "load_proposal", "read_proposal", "list_proposals",
        "get_proposals", "load_proposals",
    ])
    def test_no_proposal_reader_is_imported_or_defined(self, reader):
        assert reader not in SOURCE, \
            f"{reader!r} present — reading past proposals would create a feedback loop"


# ── No training or adaptation ───────────────────────────────────────────────


class TestNoAdaptation:

    @pytest.mark.parametrize("term", [
        "fine_tune", "finetune", "train(", "backprop", "gradient",
        "update_weights", "reinforce", "reward",
    ])
    def test_no_training_primitives(self, term):
        assert term not in SOURCE.lower(), \
            f"hermes_advisory.py references {term!r} — nothing in this path may train"

    def test_config_paths_appear_only_as_blocklist_entries(self):
        """`paper-trading-rules.yaml` etc. appear in FORBIDDEN_COMMANDS, a control
        the adapter scans Hermes responses against — the opposite of a mutation."""
        blocklist = set()
        for node in ast.walk(TREE):
            if isinstance(node, ast.Assign):
                target = getattr(node.targets[0], "id", None)
                if target == "FORBIDDEN_COMMANDS" and isinstance(node.value, ast.List):
                    blocklist = {e.value for e in node.value.elts
                                 if isinstance(e, ast.Constant)}
        assert blocklist, "FORBIDDEN_COMMANDS list not found"
        for term in ["paper-trading-rules.yaml", ".env", "guard-state"]:
            assert term in blocklist, f"{term!r} must be a forbidden-pattern entry"
        # And must appear nowhere else in the module.
        for term in ["paper-trading-rules.yaml", "guard-state.json"]:
            assert SOURCE.count(term) <= 1, \
                f"{term!r} appears outside the blocklist; the advisory path must not touch configuration"

    def test_adapter_opens_no_file_for_writing_except_its_output(self):
        writes = re.findall(r'open\(([^)]*)"w"', SOURCE)
        for w in writes:
            assert "args.output" in w, \
                f"unexpected write target: {w!r}"


# ── The documented decision matches the code ────────────────────────────────


class TestManifestRecordMatchesCode:

    def test_manifest_records_no_learning_channel(self):
        import json
        m = json.loads((REPO / "docs" / "strategy-proposals"
                        / "strategy_v1_1_proposal_v0_1.manifest.json").read_text())
        learning = m["learning_policy"]
        assert learning["autonomous_parameter_adaptation"] is False
        assert learning["pnl_is_decision_input"] is False
        assert learning["preregistration_required"] is True
        assert learning["adapter_stateless_wrt_outcomes"] is True

    def test_revision_budget_is_recorded(self):
        import json
        m = json.loads((REPO / "docs" / "strategy-proposals"
                        / "strategy_v1_1_proposal_v0_1.manifest.json").read_text())
        assert m["learning_policy"]["max_revisions_per_window"] == 1
