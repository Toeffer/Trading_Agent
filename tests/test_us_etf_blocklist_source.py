"""H4.1 — US-domiciled ETF blocklist source of truth.

The blocklist moved from a hardcoded set to `regulatory baseline | YAML`.
These tests pin the property that makes that safe: the YAML may EXTEND the
blocklist but can never shrink it below the regulatory floor.

PRIIPs/KID is law, not policy. No configuration error, omission, or
malformation may weaken the H4.1 block.
"""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import guard  # noqa: E402


BASELINE_SAMPLE = ["SPY", "QQQ", "IVV", "VOO", "GLD", "TLT", "ARKK", "SOXX"]


# ── The regulatory floor ────────────────────────────────────────────────────


class TestRegulatoryBaseline:

    def test_baseline_exists_and_is_immutable(self):
        assert isinstance(guard._US_ETF_REGULATORY_BASELINE, frozenset)

    def test_baseline_is_not_empty(self):
        assert len(guard._US_ETF_REGULATORY_BASELINE) >= 39

    @pytest.mark.parametrize("symbol", BASELINE_SAMPLE)
    def test_core_symbols_in_baseline(self, symbol):
        assert symbol in guard._US_ETF_REGULATORY_BASELINE

    def test_legacy_alias_preserved(self):
        """Existing callers and tests reference _US_ETF_BLOCKLIST."""
        assert guard._US_ETF_BLOCKLIST == guard._US_ETF_REGULATORY_BASELINE

    def test_leveraged_etfs_covered(self):
        """Belt-and-braces: leveraged ETFs are separately banned, but listed here too."""
        for sym in ["TQQQ", "SQQQ", "UPRO", "SPXU", "SOXL"]:
            assert sym in guard._US_ETF_REGULATORY_BASELINE


# ── YAML may extend ─────────────────────────────────────────────────────────


class TestYamlExtension:

    def test_yaml_symbols_are_added(self):
        rules = {"us_etf_blocklist": {"symbols": ["ZZZZ"]}}
        assert "ZZZZ" in guard._load_us_etf_blocklist(rules)

    def test_extension_is_case_insensitive(self):
        rules = {"us_etf_blocklist": {"symbols": ["zzzz"]}}
        assert "ZZZZ" in guard._load_us_etf_blocklist(rules)

    def test_extension_strips_whitespace(self):
        rules = {"us_etf_blocklist": {"symbols": ["  ZZZZ  "]}}
        assert "ZZZZ" in guard._load_us_etf_blocklist(rules)

    def test_extended_symbol_is_actually_rejected(self):
        rules = {"us_etf_blocklist": {"symbols": ["ZZZZ"]}}
        with pytest.raises(ValueError):
            guard._reject_us_domiciled_etf("ZZZZ", rules=rules)

    def test_baseline_survives_extension(self):
        rules = {"us_etf_blocklist": {"symbols": ["ZZZZ"]}}
        effective = guard._load_us_etf_blocklist(rules)
        assert guard._US_ETF_REGULATORY_BASELINE <= effective


# ── YAML may never shrink — the safety property ─────────────────────────────


class TestYamlCannotWeaken:
    """The single most important property in this module."""

    @pytest.mark.parametrize("rules", [
        {},                                            # section absent
        {"us_etf_blocklist": None},                    # section null
        {"us_etf_blocklist": {}},                      # section empty
        {"us_etf_blocklist": {"symbols": []}},         # list empty
        {"us_etf_blocklist": {"symbols": None}},       # list null
        {"us_etf_blocklist": "nonsense"},              # section wrong type
        {"us_etf_blocklist": {"symbols": "SPY"}},      # list wrong type
        {"us_etf_blocklist": {"symbols": [None, 42]}},  # entries wrong type
    ], ids=["absent", "null", "empty-section", "empty-list",
            "null-list", "bad-section-type", "bad-list-type", "bad-entries"])
    def test_baseline_always_survives(self, rules):
        effective = guard._load_us_etf_blocklist(rules)
        assert guard._US_ETF_REGULATORY_BASELINE <= effective, \
            f"YAML shape {rules!r} weakened the regulatory floor"

    @pytest.mark.parametrize("rules", [
        {}, {"us_etf_blocklist": {"symbols": []}}, {"us_etf_blocklist": "nonsense"},
    ], ids=["absent", "empty", "malformed"])
    def test_spy_rejected_regardless_of_yaml(self, rules):
        with pytest.raises(ValueError, match="US-domiciled ETF"):
            guard._reject_us_domiciled_etf("SPY", rules=rules)

    def test_yaml_cannot_remove_a_baseline_symbol(self):
        """Even an explicit attempt to override leaves the floor intact."""
        rules = {"us_etf_blocklist": {"symbols": [], "remove": ["SPY"]}}
        assert "SPY" in guard._load_us_etf_blocklist(rules)
        with pytest.raises(ValueError):
            guard._reject_us_domiciled_etf("SPY", rules=rules)

    def test_effective_list_never_empty(self):
        for rules in [{}, None, {"us_etf_blocklist": {}}]:
            assert len(guard._load_us_etf_blocklist(rules)) >= 39


# ── Rejection behavior unchanged ────────────────────────────────────────────


class TestRejectionBehavior:

    @pytest.mark.parametrize("symbol", BASELINE_SAMPLE)
    def test_baseline_symbols_rejected(self, symbol):
        with pytest.raises(ValueError, match="US-domiciled ETF"):
            guard._reject_us_domiciled_etf(symbol, rules={})

    @pytest.mark.parametrize("symbol", ["AAPL", "META", "NVDA", "AMD", "MSFT", "JNJ"])
    def test_single_names_accepted(self, symbol):
        guard._reject_us_domiciled_etf(symbol, rules={})

    def test_error_message_cites_priips(self):
        with pytest.raises(ValueError, match="PRIIPs"):
            guard._reject_us_domiciled_etf("SPY", rules={})

    def test_symbol_normalization(self):
        for variant in ["spy", " SPY ", "SpY"]:
            with pytest.raises(ValueError):
                guard._reject_us_domiciled_etf(variant, rules={})

    def test_legacy_two_arg_signature(self):
        """Pre-existing callers pass only the symbol."""
        with pytest.raises(ValueError):
            guard._reject_us_domiciled_etf("SPY")

    def test_contract_level_check_still_active(self):
        """An ETF not on any list is still caught via contract lookup."""
        def provider(sym):
            return {"secType": "ETF", "exchange": "ARCA"}
        with pytest.raises(ValueError, match="US exchange"):
            guard._reject_us_domiciled_etf("NEWETF", contract_provider=provider, rules={})

    def test_contract_provider_failure_is_non_fatal(self):
        def provider(sym):
            raise RuntimeError("lookup down")
        guard._reject_us_domiciled_etf("AAPL", contract_provider=provider, rules={})

    def test_non_us_etf_not_caught_by_contract_check(self):
        """UCITS ETFs on EU venues are not blocked by H4.1 (they are legal).

        They remain blocked by the separate non-US-equities rule and by
        Gate A, but H4.1 itself must not be the thing rejecting them.
        """
        def provider(sym):
            return {"secType": "ETF", "exchange": "IBIS"}   # Xetra
        guard._reject_us_domiciled_etf("EQQQ", contract_provider=provider, rules={})


# ── H2 single-source-of-truth accounting ────────────────────────────────────


class TestH2Accounting:

    def test_yaml_section_is_optional(self):
        """Absence must not raise — it resolves to the baseline."""
        assert guard._load_us_etf_blocklist({}) == guard._US_ETF_REGULATORY_BASELINE

    def test_loader_documents_the_floor_rationale(self):
        source = (REPO / "guard.py").read_text()
        idx = source.find("_US_ETF_REGULATORY_BASELINE")
        assert idx != -1
        header = source[max(0, idx - 1400):idx]
        assert "PRIIPs" in header
        assert "fail-open" in header or "never shrink" in header or "can never" in header

    def test_blocklist_not_in_required_keys(self):
        """Optional by design: a missing key must not stop the bridge starting."""
        source = (REPO / "guard.py").read_text()
        start = source.find("required_keys = [")
        block = source[start:start + 600]
        assert "us_etf_blocklist" not in block
