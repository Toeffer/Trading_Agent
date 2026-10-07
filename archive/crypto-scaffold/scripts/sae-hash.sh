#!/usr/bin/env bash
# Record / verify the SHA-256 hash of config/sae-config.yaml.
# Per CLAUDE.md §11 rule 10: detect unauthorized changes to safety rules.
#
# Usage:
#   ./scripts/sae-hash.sh record   # after an intentional edit, run this then commit both files
#   ./scripts/sae-hash.sh verify   # at session start (also run by preflight.py)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SAE_CONFIG="${REPO_ROOT}/config/sae-config.yaml"
HASH_FILE="${REPO_ROOT}/.sae-config.hash"

if [[ ! -f "${SAE_CONFIG}" ]]; then
    echo "ERROR: ${SAE_CONFIG} not found" >&2
    exit 2
fi

current="$(sha256sum "${SAE_CONFIG}" | awk '{print $1}')"

case "${1:-verify}" in
    record)
        echo "${current}" > "${HASH_FILE}"
        echo "Recorded SAE config hash: ${current}"
        echo "Commit ${HASH_FILE} alongside config/sae-config.yaml."
        ;;
    verify)
        if [[ ! -f "${HASH_FILE}" ]]; then
            echo "WARN: no recorded hash. Run: ./scripts/sae-hash.sh record" >&2
            exit 1
        fi
        recorded="$(cat "${HASH_FILE}")"
        if [[ "${recorded}" == "${current}" ]]; then
            echo "OK: SAE config hash matches (${current:0:12}...)"
            exit 0
        fi
        echo "FAIL: SAE config hash MISMATCH" >&2
        echo "  recorded: ${recorded}" >&2
        echo "  current:  ${current}" >&2
        echo "Per CLAUDE.md §11 rule 10: halt and review before any trading." >&2
        exit 1
        ;;
    *)
        echo "Usage: $0 {record|verify}" >&2
        exit 2
        ;;
esac
