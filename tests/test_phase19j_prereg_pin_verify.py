"""Tests for Phase 19J — Pre-registration pin verification (2026-08-13).

Implements, as an actual executable check, the pin-computation procedure
pr-2026-08-v4-preregistration.md's §2 describes (and TEMPLATE-preregistration.md's
queued wording fix): a pathspec-filtered git commit pin, and a YAML pin
normalized against exactly one `enforced:` field. Until this, both were
verified by hand on the live host.

Read-only throughout: no protected files, no order path, no H1 token.
"""

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

BRIDGE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BRIDGE_DIR))

from ibkr_operator import (  # noqa: E402
    _prereg_runtime_safety_git_pin,
    _prereg_normalized_yaml_pin,
    _parse_prereg_recorded_pins,
    _run_prereg_pin_verify,
    _PREREG_RUNTIME_SAFETY_PATHS,
)


class TestGitRuntimeSafetyPin:
    def test_matches_raw_git_log_against_the_same_pathspec(self):
        """Cross-check against the exact command from the v4 document and
        tonight's live-host verification, run independently here."""
        sha, err = _prereg_runtime_safety_git_pin(BRIDGE_DIR)
        assert err is None
        raw = subprocess.run(
            ["git", "log", "-1", "--format=%H", "--"] + _PREREG_RUNTIME_SAFETY_PATHS,
            cwd=str(BRIDGE_DIR), capture_output=True, text=True,
        ).stdout.strip()
        assert sha == raw
        assert len(sha) == 40

    def test_nonexistent_repo_dir_errors_not_crashes(self, tmp_path):
        sha, err = _prereg_runtime_safety_git_pin(tmp_path / "does-not-exist")
        assert sha is None
        assert err is not None

    def test_docs_only_commit_does_not_change_the_pin(self, tmp_path):
        """The whole point of the pathspec filter: a commit touching only
        docs must not move this pin. Build a tiny throwaway repo to prove
        it deterministically rather than relying on this repo's real
        history happening to have one at hand."""
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=tmp_path, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
        (tmp_path / "guard.py").write_text("# runtime safety file\n")
        (tmp_path / "docs.md").write_text("# docs\n")
        subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)

        # Point the pathspec check at just this repo's one runtime file.
        with patch("ibkr_operator._PREREG_RUNTIME_SAFETY_PATHS", ["guard.py"]):
            sha_before, _ = _prereg_runtime_safety_git_pin(tmp_path)

        (tmp_path / "docs.md").write_text("# docs, updated\n")
        subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "docs only"], cwd=tmp_path, check=True)

        with patch("ibkr_operator._PREREG_RUNTIME_SAFETY_PATHS", ["guard.py"]):
            sha_after, _ = _prereg_runtime_safety_git_pin(tmp_path)

        assert sha_before == sha_after


class TestNormalizedYamlPin:
    def test_missing_file_fails_closed(self, tmp_path):
        pin, err = _prereg_normalized_yaml_pin(tmp_path / "does-not-exist.yaml")
        assert pin is None
        assert "not found" in err

    def test_zero_enforced_fields_fails_closed(self, tmp_path):
        p = tmp_path / "rules.yaml"
        p.write_text("allowlist:\n  - AAPL\n")
        pin, err = _prereg_normalized_yaml_pin(p)
        assert pin is None
        assert "found 0" in err

    def test_two_enforced_fields_fails_closed(self, tmp_path):
        p = tmp_path / "rules.yaml"
        p.write_text("enforced: true\nnested:\n  enforced: false\n")
        pin, err = _prereg_normalized_yaml_pin(p)
        assert pin is None
        assert "found 2" in err

    def test_true_and_false_normalize_to_the_same_pin(self, tmp_path):
        """The documented false -> true -> false trade-window cycle must
        not change the pin."""
        p = tmp_path / "rules.yaml"
        p.write_text("allowlist:\n  - AAPL\nenforced: false\nmax_trades: 2\n")
        pin_false, err1 = _prereg_normalized_yaml_pin(p)

        p.write_text("allowlist:\n  - AAPL\nenforced: true\nmax_trades: 2\n")
        pin_true, err2 = _prereg_normalized_yaml_pin(p)

        assert err1 is None and err2 is None
        assert pin_false == pin_true

    def test_any_other_field_change_does_change_the_pin(self, tmp_path):
        """Only the enforced flip is excluded -- everything else still
        moves the pin, exactly as the run-voiding rule requires."""
        p = tmp_path / "rules.yaml"
        p.write_text("allowlist:\n  - AAPL\nenforced: false\nmax_trades: 2\n")
        pin_before, _ = _prereg_normalized_yaml_pin(p)

        p.write_text("allowlist:\n  - AAPL\n  - MSFT\nenforced: false\nmax_trades: 2\n")
        pin_after, _ = _prereg_normalized_yaml_pin(p)

        assert pin_before != pin_after

    def test_matches_manual_sha256_of_the_normalized_text(self, tmp_path):
        p = tmp_path / "rules.yaml"
        p.write_text("a: 1\nenforced: true\nb: 2\n")
        pin, err = _prereg_normalized_yaml_pin(p)
        assert err is None
        expected = hashlib.sha256(b"a: 1\nenforced: false\nb: 2\n").hexdigest()
        assert pin == expected


class TestParseRecordedPins:
    def test_parses_v4_style_document(self):
        doc = """
| Field | Value |
|---|---|
| Git runtime-safety pin | `ff7973328184df73b31c4d8d27adeee5d83620c9` |
| paper-trading-rules.yaml normalized configuration SHA-256 | `fadb4402f0a7c286945fab5f1d429113063200532e3936f47f0f8ed555a0442b` |
"""
        pins = _parse_prereg_recorded_pins(doc)
        assert pins["git_runtime_safety_pin"] == "ff7973328184df73b31c4d8d27adeee5d83620c9"
        assert pins["yaml_normalized_sha256"] == "fadb4402f0a7c286945fab5f1d429113063200532e3936f47f0f8ed555a0442b"

    def test_falls_back_to_plain_git_commit_label_for_older_documents(self):
        """pr-2026-08-v2 used the old "Git commit" label, not "Git
        runtime-safety pin" -- still parseable, even though its value is
        known-stale (that's the whole incident this feature exists to
        prevent from recurring silently)."""
        doc = "| Git commit | `5a4654b23b43887714e30790220056864dc9e0cd` |"
        pins = _parse_prereg_recorded_pins(doc)
        assert pins["git_runtime_safety_pin"] == "5a4654b23b43887714e30790220056864dc9e0cd"

    def test_missing_fields_return_empty_dict_not_a_crash(self):
        assert _parse_prereg_recorded_pins("no pins here at all") == {}


class TestRunPreregPinVerify:
    def test_no_doc_just_reports_live_pins(self, tmp_path):
        yaml_path = tmp_path / "rules.yaml"
        yaml_path.write_text("enforced: false\n")
        with patch("ibkr_operator.BRIDGE_DIR", BRIDGE_DIR), \
             patch("ibkr_operator._prereg_rules_path", return_value=yaml_path):
            result = _run_prereg_pin_verify(doc_path=None)

        assert result["pass"] is True
        assert result["live"]["git_runtime_safety_pin"] is not None
        assert result["live"]["yaml_normalized_sha256"] is not None
        assert result["recorded"] is None
        assert result["comparisons"] is None

    def test_computation_error_fails_closed_regardless_of_doc(self, tmp_path):
        with patch("ibkr_operator.BRIDGE_DIR", tmp_path / "no-such-repo"), \
             patch("ibkr_operator._prereg_rules_path", return_value=tmp_path / "no-such.yaml"):
            result = _run_prereg_pin_verify(doc_path=None)

        assert result["pass"] is False
        assert result["fail_reason"] == "fail_closed_on_pin_computation_error"

    def test_doc_with_matching_pins_passes(self, tmp_path):
        yaml_path = tmp_path / "rules.yaml"
        yaml_path.write_text("enforced: false\n")

        with patch("ibkr_operator.BRIDGE_DIR", BRIDGE_DIR), \
             patch("ibkr_operator._prereg_rules_path", return_value=yaml_path):
            live = _run_prereg_pin_verify(doc_path=None)

        doc_path = tmp_path / "pr-test-preregistration.md"
        doc_path.write_text(
            f"| Git runtime-safety pin | `{live['live']['git_runtime_safety_pin']}` |\n"
            f"| paper-trading-rules.yaml normalized configuration SHA-256 | "
            f"`{live['live']['yaml_normalized_sha256']}` |\n"
        )

        with patch("ibkr_operator.BRIDGE_DIR", BRIDGE_DIR), \
             patch("ibkr_operator._prereg_rules_path", return_value=yaml_path):
            result = _run_prereg_pin_verify(doc_path=str(doc_path))

        assert result["pass"] is True
        assert result["comparisons"]["git_runtime_safety_pin"]["status"] == "MATCH"
        assert result["comparisons"]["yaml_normalized_sha256"]["status"] == "MATCH"

    def test_doc_with_stale_pin_fails_and_says_exactly_why(self, tmp_path):
        """Regression for the actual pr-2026-08-v2 incident: a pin that
        goes stale must be caught, not silently waved through."""
        yaml_path = tmp_path / "rules.yaml"
        yaml_path.write_text("enforced: false\n")

        doc_path = tmp_path / "pr-test-preregistration.md"
        doc_path.write_text(
            "| Git runtime-safety pin | `0000000000000000000000000000000000000000` |\n"
            "| paper-trading-rules.yaml normalized configuration SHA-256 | "
            "`0000000000000000000000000000000000000000000000000000000000000000` |\n"
        )

        with patch("ibkr_operator.BRIDGE_DIR", BRIDGE_DIR), \
             patch("ibkr_operator._prereg_rules_path", return_value=yaml_path):
            result = _run_prereg_pin_verify(doc_path=str(doc_path))

        assert result["pass"] is False
        assert result["comparisons"]["git_runtime_safety_pin"]["status"] == "MISMATCH"
        assert result["comparisons"]["yaml_normalized_sha256"]["status"] == "MISMATCH"

    def test_missing_document_fails_with_a_clear_reason(self, tmp_path):
        yaml_path = tmp_path / "rules.yaml"
        yaml_path.write_text("enforced: false\n")
        with patch("ibkr_operator.BRIDGE_DIR", BRIDGE_DIR), \
             patch("ibkr_operator._prereg_rules_path", return_value=yaml_path):
            result = _run_prereg_pin_verify(doc_path=str(tmp_path / "nope.md"))
        assert result["pass"] is False
        assert "not found" in result["fail_reason"]


class TestCliRegistration:
    def test_aliases_registered(self):
        for alias in ("preregistration-pin-verify", "prereg-pin-verify"):
            r = subprocess.run(
                [sys.executable, str(BRIDGE_DIR / "ibkr_operator.py"), alias, "--help"],
                capture_output=True, text=True, timeout=15,
            )
            assert r.returncode == 0, f"{alias} --help failed: {r.stderr}"

    def test_json_output_is_valid_json(self, tmp_path):
        yaml_path = tmp_path / "does-not-exist.yaml"
        env = {"IBKR_RULES_PATH": str(yaml_path)}
        import os
        full_env = {**os.environ, **env}
        r = subprocess.run(
            [sys.executable, str(BRIDGE_DIR / "ibkr_operator.py"), "preregistration-pin-verify", "--json"],
            capture_output=True, text=True, timeout=15, env=full_env,
        )
        data = json.loads(r.stdout)
        assert "live" in data
        assert data["pass"] is False  # the redirected YAML path doesn't exist
