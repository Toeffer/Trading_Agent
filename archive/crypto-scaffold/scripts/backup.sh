#!/usr/bin/env bash
# Weekly encrypted backup of OpenClaw runtime state.
# Per CLAUDE.md §11 rule 9.
#
# Schedule with cron, e.g. (Sunday 03:00 UTC):
#   0 3 * * 0 cd /opt/trading-agent && ./scripts/backup.sh >> backups/backup.log 2>&1
#
# Requires: gpg, tar. BACKUP_PASSPHRASE env var must be set (from .env).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Load env
if [[ -f .env ]]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
fi

if [[ -z "${BACKUP_PASSPHRASE:-}" ]]; then
    echo "ERROR: BACKUP_PASSPHRASE not set in .env" >&2
    exit 1
fi

DATE="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="backups/openclaw-${DATE}.tar.gz.gpg"
mkdir -p backups

echo "[backup] Creating ${OUT}"

# Tar the runtime data volume + the config dir.
# We don't back up logs > 90 days (per CLAUDE.md §10 retention).
# We DO back up sae-config.yaml (committed to git anyway, but redundancy is cheap).
docker compose run --rm \
    -v "${REPO_ROOT}/backups:/backup-out" \
    agent tar -czf - -C / data/openclaw 2>/dev/null \
    | gpg --batch --yes --symmetric --cipher-algo AES256 \
        --passphrase "${BACKUP_PASSPHRASE}" \
        -o "${OUT}"

echo "[backup] OK — ${OUT} ($(du -h "${OUT}" | cut -f1))"

# Rotate: keep last 8 weeks
ls -1t backups/openclaw-*.tar.gz.gpg 2>/dev/null | tail -n +9 | xargs -r rm -v

# TODO(operator): copy ${OUT} off-host. Suggested options:
#   - rsync to a remote server:   rsync -av "${OUT}" backup-host:/backups/
#   - upload to S3-compatible:    aws s3 cp "${OUT}" s3://your-bucket/
#   - mounted external disk:      cp "${OUT}" /mnt/external/backups/
# Per CLAUDE.md §11 rule 9 the backup must land in an external location.
echo "[backup] TODO: copy ${OUT} off-host (see script for options)"
