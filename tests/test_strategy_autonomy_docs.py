#!/usr/bin/env python3
"""
CI Validation Tests for Strategy and Autonomy Documents

Ensures required sections exist in docs/STRATEGY.md and docs/AUTONOMY_CRITERIA.md.
These are structural validation tests — they verify the documents are complete
and include the mandatory sections, not that the content is correct.

  T1  STRATEGY.md exists and is non-empty
  T2  STRATEGY.md has all required sections
  T3  AUTONOMY_CRITERIA.md exists and is non-empty
  T4  AUTONOMY_CRITERIA.md has all required sections
  T5  Hard invariants present in both documents
"""

from pathlib import Path


DOCS_DIR = Path(__file__).resolve().parent.parent / "docs"
STRATEGY_PATH = DOCS_DIR / "STRATEGY.md"
AUTONOMY_PATH = DOCS_DIR / "AUTONOMY_CRITERIA.md"

# Required sections in STRATEGY.md (checked as headings)
STRATEGY_REQUIRED_SECTIONS = [
    "Allowed Market Universe",
    "Allowed Instruments",
    "Long-Only",
    "Setup Criteria",
    "Entry Criteria",
    "Invalidation",
    "Stop Criteria",
    "Profit-Taking",
    "Exit Criteria",
    "Position Sizing",
    "Maximum Daily",
    "Trade Frequency",
    "No-Trade Conditions",
    "Hermes Advisory",
    "Werner / OpenClaw Boundaries",
    "Default State",
]

# Required sections in AUTONOMY_CRITERIA.md (checked as headings)
AUTONOMY_REQUIRED_SECTIONS = [
    "Autonomous Cycle",
    "Pre-Cycle Checks",
    "Required Proposal Fields",
    "Required Approval Evidence",
    "Post-Cycle Monitoring",
    "Hard Stop Conditions",
    "Clean Cycle",
    "Autonomy Levels",
    "Rollback",
    "Relock",
    "Cycle Logging",
    "Hard Invariants",
]

# Hard invariants that must appear in AUTONOMY_CRITERIA.md
HARD_INVARIANTS = [
    "Hermes remains advisory-only",
    "Bridge remains the only broker-action path",
    "/order remains 403",
    "BUY entries require P5 broker-side protective stops",
    "close-only SELL exits remain allowed only for reducing",
    "All orders require /order/preflight",
    "Default state remains locked",
    "H1 token never stored in app code",
]


def _get_headings(doc_path: Path) -> list[str]:
    """Extract all markdown headings from a document."""
    headings = []
    try:
        for line in doc_path.read_text().splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                headings.append(stripped.lstrip("#").strip())
    except Exception:
        pass
    return headings


def _section_present(headings: list[str], required: str) -> bool:
    """Check if a required section is present in headings (fuzzy match)."""
    required_lower = required.lower()
    for h in headings:
        if required_lower in h.lower():
            return True
    return False


class TestStrategyDocument:
    """T1–T2: STRATEGY.md completeness."""

    def test_strategy_doc_exists(self):
        """STRATEGY.md exists and is non-empty."""
        assert STRATEGY_PATH.exists(), f"{STRATEGY_PATH} must exist"
        content = STRATEGY_PATH.read_text()
        assert len(content) > 500, \
            f"STRATEGY.md is too short ({len(content)} chars); expected substantial document"

    def test_strategy_has_required_sections(self):
        """All required sections are present in STRATEGY.md."""
        headings = _get_headings(STRATEGY_PATH)
        missing = []
        for section in STRATEGY_REQUIRED_SECTIONS:
            if not _section_present(headings, section):
                missing.append(section)
        assert len(missing) == 0, \
            f"STRATEGY.md missing required sections:\n" + \
            "\n".join(f"  - {s}" for s in missing)

    def test_strategy_defines_default_state(self):
        """STRATEGY.md explicitly states default locked state."""
        content = STRATEGY_PATH.read_text()
        assert "IBKR_ALLOW_ORDERS=false" in content or "IBKR_ALLOW_ORDERS=false" in content, \
            "STRATEGY.md must reference IBKR_ALLOW_ORDERS=false"
        assert "rules.enforced=false" in content or "rules.enforced=false" in content, \
            "STRATEGY.md must reference rules.enforced=false"

    def test_strategy_defines_no_broker_mutation(self):
        """STRATEGY.md is strategy-only, no broker mutation."""
        # Not a code file — this is meta. Verify it's not executable.
        content = STRATEGY_PATH.read_text()
        assert "#!/usr/bin" not in content, "STRATEGY.md must not be executable"
        assert "ib.placeOrder" not in content, "STRATEGY.md must not contain broker code"


class TestAutonomyDocument:
    """T3–T4: AUTONOMY_CRITERIA.md completeness."""

    def test_autonomy_doc_exists(self):
        """AUTONOMY_CRITERIA.md exists and is non-empty."""
        assert AUTONOMY_PATH.exists(), f"{AUTONOMY_PATH} must exist"
        content = AUTONOMY_PATH.read_text()
        assert len(content) > 500, \
            f"AUTONOMY_CRITERIA.md is too short ({len(content)} chars)"

    def test_autonomy_has_required_sections(self):
        """All required sections are present in AUTONOMY_CRITERIA.md."""
        headings = _get_headings(AUTONOMY_PATH)
        missing = []
        for section in AUTONOMY_REQUIRED_SECTIONS:
            if not _section_present(headings, section):
                missing.append(section)
        assert len(missing) == 0, \
            f"AUTONOMY_CRITERIA.md missing required sections:\n" + \
            "\n".join(f"  - {s}" for s in missing)

    def test_autonomy_defines_current_level_zero(self):
        """AUTONOMY_CRITERIA.md defines current autonomy as Level 0."""
        content = AUTONOMY_PATH.read_text()
        assert "**0 (current)**" in content or "Level 0" in content or "level 0" in content.lower(), \
            "AUTONOMY_CRITERIA.md must define current autonomy as Level 0"
        assert "Zero autonomy" in content or "zero autonomy" in content.lower(), \
            "AUTONOMY_CRITERIA.md must state zero autonomy at current level"


class TestHardInvariants:
    """T5: Hard invariants present in both documents."""

    def test_hard_invariants_in_autonomy(self):
        """All hard invariants appear in AUTONOMY_CRITERIA.md."""
        content = AUTONOMY_PATH.read_text()
        # Use case-insensitive normalized content for matching
        normalized = content.replace("`", "").lower()
        missing = []
        for inv in HARD_INVARIANTS:
            inv_lower = inv.lower()
            # Try exact match first, then normalized
            if inv not in content and inv_lower not in normalized:
                # Try key phrase match (first 4 words, case-insensitive)
                key_words = inv_lower.split()[:4]
                key_phrase = " ".join(key_words)
                if key_phrase not in normalized:
                    missing.append(inv)
        assert len(missing) == 0, \
            f"AUTONOMY_CRITERIA.md missing hard invariants:\n" + \
            "\n".join(f"  - {s}" for s in missing)

    def test_hard_invariants_in_strategy(self):
        """Key hard invariants appear in STRATEGY.md."""
        content = STRATEGY_PATH.read_text()
        # Strip markdown formatting and backticks for fuzzy matching
        import re
        clean = content.replace("`", "").replace("**", "").replace("*", "").lower()
        # Check key phrases that must be present (fuzzy match on document wording)
        must_contain = [
            ("Hermes advisory", ["hermes is advisory", "hermes remains advisory"]),
            ("bridge path", ["bridge", "broker-action path", "only execution path"]),
            ("/order 403", ["/order remains 403", "/order endpoint", "/order is permanently blocked"]),
            ("P5 stops", ["p5 broker-side protective stop", "p5 bracket", "broker-side protective stop"]),
            ("approval path", ["/order/preflight", "/order/approve", "/order/submit"]),
            ("default locked", ["default state", "ibkr_allow_orders=false", "rules.enforced=false"]),
        ]
        missing = []
        for label, phrases in must_contain:
            found = any(p in clean for p in phrases)
            if not found:
                missing.append(label)
        assert len(missing) == 0, \
            f"STRATEGY.md missing hard invariants:\n" + \
            "\n".join(f"  - {s}" for s in missing)

    def test_no_order_enabling_in_either_doc(self):
        """Neither document contains order-enabling instructions."""
        for doc_path in [STRATEGY_PATH, AUTONOMY_PATH]:
            content = doc_path.read_text()
            # "IBKR_ALLOW_ORDERS=true" should never appear as a literal instruction
            # (it may appear in context of "must not" or "Chris sets")
            lines_with_true = [
                l for l in content.splitlines()
                if "IBKR_ALLOW_ORDERS=true" in l
            ]
            for line in lines_with_true:
                stripped = line.strip()
                ok = (
                    "Chris" in stripped
                    or "must not" in stripped.lower()
                    or "must never" in stripped.lower()
                    or stripped.startswith("#")
                    or stripped.startswith(">")
                )
                assert ok, \
                    f"{doc_path.name}: IBKR_ALLOW_ORDERS=true in non-safety context: {stripped[:120]}"
