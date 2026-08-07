#!/usr/bin/env bash
# Nightly backup of the bot database.
#
# Uses sqlite3's .backup rather than cp: with WAL enabled a plain file copy can
# catch the database mid-write and produce an unusable file.
#
#   crontab -e
#   15 3 * * *  /opt/salary-tracking/deploy/backup.sh
set -euo pipefail

DB="${DB:-/opt/salary-tracking/data/salary.db}"
DEST="${DEST:-/opt/salary-tracking/backups}"
KEEP_DAYS="${KEEP_DAYS:-30}"

mkdir -p "$DEST"
stamp="$(date +%Y-%m-%d)"
out="$DEST/salary-$stamp.db"

sqlite3 "$DB" ".backup '$out'"
gzip -f "$out"

find "$DEST" -name 'salary-*.db.gz' -mtime "+$KEEP_DAYS" -delete

echo "Backed up to $out.gz"
