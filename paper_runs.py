"""Paper-run pre-registrations: discovery, seal check, window, review state.

Read-only helpers shared by `hermes_research` and `hermes_review`. They read
docs/paper-runs/<run-id>-preregistration.md and its -seal.json (the same
SHA-256 scripts/seal-preregistration.py records), and the presence of an
end-of-window review under ~/.openclaw/reviews/<run-id>/. They never read
run outcomes (guard events, approvals, fills, results documents).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent
PAPER_RUNS = REPO / "docs" / "paper-runs"
REVIEWS_DIR = Path(os.environ.get("OPENCLAW_REVIEWS_DIR",
                                  str(Path.home() / ".openclaw" / "reviews")))

_ROW = r"^\|\s*{label}\s*\|\s*`?(\d{{4}}-\d{{2}}-\d{{2}})`?\s*\|"


def prereg_path(run_id: str, paper_runs: Path = PAPER_RUNS) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,80}", run_id or ""):
        raise ValueError(f"invalid run id {run_id!r}")
    return Path(paper_runs) / f"{run_id}-preregistration.md"


def seal_path(doc: Path) -> Path:
    return doc.with_name(doc.name.replace("-preregistration.md", "-seal.json"))


def window(text: str) -> tuple[str | None, str | None]:
    """(start, planned_end) from the section 1 Run identity table."""
    found = []
    for label in ("Start date", "Planned end date"):
        m = re.search(_ROW.format(label=re.escape(label)), text, re.M)
        found.append(m.group(1) if m else None)
    return found[0], found[1]


def seal_status(doc: Path) -> dict:
    """{'sealed': bool, 'intact': bool|None, 'sha256', 'sealed_utc'}."""
    seal = seal_path(doc)
    if not seal.exists():
        return {"sealed": False, "intact": None, "sha256": None, "sealed_utc": None}
    record = json.loads(seal.read_text(encoding="utf-8"))
    actual = hashlib.sha256(doc.read_bytes()).hexdigest()
    return {"sealed": True, "intact": actual == record.get("sha256"),
            "sha256": record.get("sha256"), "sealed_utc": record.get("sealed_utc")}


def review_dir(run_id: str, reviews_dir: Path | None = None) -> Path:
    return Path(reviews_dir or REVIEWS_DIR) / run_id


def is_reviewed(run_id: str, reviews_dir: Path | None = None) -> bool:
    return (review_dir(run_id, reviews_dir) / "review.json").exists()


def sealed_runs(paper_runs: Path = PAPER_RUNS, reviews_dir: Path | None = None) -> list[dict]:
    """Every sealed pre-registration, oldest start first."""
    runs = []
    for doc in sorted(Path(paper_runs).glob("*-preregistration.md")):
        if doc.name.startswith("TEMPLATE"):
            continue
        status = seal_status(doc)
        if not status["sealed"]:
            continue
        run_id = doc.name[: -len("-preregistration.md")]
        start, end = window(doc.read_text(encoding="utf-8"))
        runs.append({"run_id": run_id, "start": start, "planned_end": end,
                     "intact": status["intact"], "reviewed": is_reviewed(run_id, reviews_dir)})
    return sorted(runs, key=lambda r: (r["start"] or "", r["run_id"]))


def outcome_cutoff(paper_runs: Path = PAPER_RUNS, reviews_dir: Path | None = None,
                   today: date | None = None) -> dict:
    """First date research data may not reach.

    The earliest start of any sealed run that has not had its end-of-window
    review. Market data from inside such a window would tell Hermes how its
    pre-registered strategy is doing. A sealed run without a readable start
    date fails closed at today.
    """
    today = today or date.today()
    unreviewed = [r for r in sealed_runs(paper_runs, reviews_dir) if not r["reviewed"]]
    if not unreviewed:
        return {"cutoff": None, "runs": []}
    starts = [r["start"] or today.isoformat() for r in unreviewed]
    return {"cutoff": min(starts), "runs": [r["run_id"] for r in unreviewed]}
