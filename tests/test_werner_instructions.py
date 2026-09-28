"""Werner's deployed instructions must be this repo's CLAUDE.md (2026-09-28).

The live Werner reads ~/.openclaw/CLAUDE.md, a separate file from the checkout.
The pre-refactor copy (now docs/openclaw/archive/) still told Werner to size
with the raw ExchangeRate tag and an assumed EUR/USD of 1.00, while the guard
uses 1 / ExchangeRate[USD]. `ibkr-operator doctor` check K17 flags any drift.
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import ibkr_operator  # noqa: E402

REPO_MD = REPO / "CLAUDE.md"
ARCHIVED = REPO / "docs" / "openclaw" / "archive" / "CLAUDE.pre-refactor.md"


class TestWernerInstructionsCheck:
    def test_identical_copy_passes(self, tmp_path):
        deployed = tmp_path / "CLAUDE.md"
        deployed.write_text(REPO_MD.read_text())
        ok, detail = ibkr_operator._check_werner_instructions(deployed, REPO_MD)
        assert ok, detail

    def test_symlink_passes(self, tmp_path):
        deployed = tmp_path / "CLAUDE.md"
        deployed.symlink_to(REPO_MD)
        ok, detail = ibkr_operator._check_werner_instructions(deployed, REPO_MD)
        assert ok, detail

    def test_stale_pre_refactor_copy_fails_and_names_the_fx_rule(self, tmp_path):
        deployed = tmp_path / "CLAUDE.md"
        deployed.write_text(ARCHIVED.read_text())
        ok, detail = ibkr_operator._check_werner_instructions(deployed, REPO_MD)
        assert not ok
        assert "fx_rate = ibkr_account.ExchangeRate" in detail

    def test_any_drift_fails(self, tmp_path):
        deployed = tmp_path / "CLAUDE.md"
        deployed.write_text(REPO_MD.read_text() + "\nlocal edit\n")
        ok, detail = ibkr_operator._check_werner_instructions(deployed, REPO_MD)
        assert not ok and "differs" in detail

    def test_not_deployed_is_skipped(self, tmp_path):
        ok, detail = ibkr_operator._check_werner_instructions(tmp_path / "missing.md", REPO_MD)
        assert ok and "skipped" in detail

    def test_doctor_runs_the_check(self):
        assert '"werner_instructions_current"' in (REPO / "ibkr_operator.py").read_text()


class TestInstructionContent:
    def test_repo_claude_md_has_the_correct_fx_rule(self):
        text = REPO_MD.read_text()
        assert "1 / ExchangeRate[USD]" in text
        for rule in ibkr_operator._STALE_WERNER_RULES:
            assert rule not in text, rule

    def test_repo_claude_md_has_the_simulation_rule(self):
        text = REPO_MD.read_text()
        assert "DUSIM0001" in text and "SIMULATION" in text

    def test_archived_copy_is_marked_superseded(self):
        assert ARCHIVED.read_text().startswith("> **SUPERSEDED")
        assert not (REPO / "docs" / "openclaw" / "CLAUDE.md").exists()
