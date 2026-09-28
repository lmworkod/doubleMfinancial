#!/usr/bin/env bash
set -Eeuo pipefail
BACKUP_DIR="${BACKUP_DIR:-/var/backups/doublemfinancial}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
install -d -o root -g root -m 0700 "$BACKUP_DIR"
sudo -u postgres pg_dump --format=custom --no-owner doublem > "$BACKUP_DIR/doublem-$STAMP.dump"
chmod 0600 "$BACKUP_DIR/doublem-$STAMP.dump"
echo "$BACKUP_DIR/doublem-$STAMP.dump"
