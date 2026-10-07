#!/usr/bin/env python3
"""Seal a paper-run pre-registration document.

Records the SHA-256 of the document before the run starts, so that any later
amendment is detectable. Proposal section 10.4 requires the hash be fixed
before the first cycle; amending a sealed document voids the run as evidence.

Usage:
    python3 scripts/seal-preregistration.py docs/paper-runs/<run-id>-preregistration.md
    python3 scripts/seal-preregistration.py --verify docs/paper-runs/<run-id>-preregistration.md

Read-only with respect to the trading system. Touches no broker endpoint, no
guard state, no rules file, and no H1 token.
"""

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

SEAL_LINE = "| SHA-256 of this document |"
PLACEHOLDER = re.compile(r"<<[^>]*>>")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def seal_path(doc: Path) -> Path:
    return doc.with_name(doc.name.replace("-preregistration.md", "-seal.json"))


def unfilled_placeholders(text: str) -> list[str]:
    """Placeholders outside section 7's running counter and section 8's seal fields."""
    out = []
    for line in text.splitlines():
        if not PLACEHOLDER.search(line):
            continue
        if "update during the run" in line or "written by the seal script" in line:
            continue
        out.append(line.strip())
    return out


def do_seal(doc: Path, force: bool) -> int:
    if not doc.exists():
        print(f"error: {doc} does not exist", file=sys.stderr)
        return 2

    text = doc.read_text()
    outstanding = unfilled_placeholders(text)
    if outstanding and not force:
        print(f"REFUSING TO SEAL — {len(outstanding)} field(s) still unfilled:\n",
              file=sys.stderr)
        for line in outstanding:
            print(f"  {line}", file=sys.stderr)
        print("\nA pre-registration with blanks registers nothing. Fill them in, or "
              "pass --force if a blank is genuinely intentional.", file=sys.stderr)
        return 1

    target = seal_path(doc)
    if target.exists():
        existing = json.loads(target.read_text())
        print(f"error: already sealed at {existing.get('sealed_utc')}", file=sys.stderr)
        print("Amending a sealed pre-registration voids the run. Start a new run "
              "instead of resealing.", file=sys.stderr)
        return 3

    digest = sha256_file(doc)
    record = {
        "document": str(doc.as_posix()),
        "sha256": digest,
        "sealed_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "algorithm": "sha256",
        "governing_sections": ["10.4", "10.1", "11.6"],
        "immutable": True,
        "note": ("Amending the sealed document voids the run as evidence. "
                 "Observations belong in the corresponding results document."),
    }
    target.write_text(json.dumps(record, indent=2) + "\n")

    print(f"sealed:     {doc}")
    print(f"sha256:     {digest}")
    print(f"seal file:  {target}")
    print("\nCommit both files, then start the run.")
    return 0


def do_verify(doc: Path) -> int:
    target = seal_path(doc)
    if not target.exists():
        print(f"error: no seal file at {target}", file=sys.stderr)
        return 2

    record = json.loads(target.read_text())
    actual = sha256_file(doc)
    if actual == record["sha256"]:
        print(f"INTACT — matches seal from {record['sealed_utc']}")
        print(f"sha256: {actual}")
        return 0

    print("SEAL BROKEN — the pre-registration changed after sealing.", file=sys.stderr)
    print(f"  sealed: {record['sha256']}", file=sys.stderr)
    print(f"  actual: {actual}", file=sys.stderr)
    print("\nThis run is void as evidence (section 10.4). Start a new run.", file=sys.stderr)
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Seal or verify a pre-registration document")
    ap.add_argument("document", type=Path)
    ap.add_argument("--verify", action="store_true",
                    help="Check an existing seal instead of creating one")
    ap.add_argument("--force", action="store_true",
                    help="Seal despite unfilled placeholders")
    args = ap.parse_args()
    return do_verify(args.document) if args.verify else do_seal(args.document, args.force)


if __name__ == "__main__":
    sys.exit(main())
