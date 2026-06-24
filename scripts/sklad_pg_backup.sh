#!/usr/bin/env bash
# PostgreSQL daily backup for sklad/tetis databases
# Retention: 30 days

set -euo pipefail

BACKUP_DIR="/opt/backups/postgres"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
RETAIN_DAYS=30
POSTGRES_CONTAINER="36e33509aaac_qtrix_postgres_1"
LOG_FILE="/var/log/sklad_backup.log"
PGUSER="finalboss"
PGPASSWORD="finalboss_pass"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"; }

mkdir -p "$BACKUP_DIR"

log "=== PostgreSQL backup started ==="

# Get list of databases (exclude system DBs)
DATABASES=$(docker exec -e PGPASSWORD="$PGPASSWORD" "$POSTGRES_CONTAINER" \
    psql -U "$PGUSER" -d postgres -t -c \
    "SELECT datname FROM pg_database WHERE datistemplate = false AND datname NOT IN ('postgres') ORDER BY datname;" \
    2>/dev/null | tr -d ' ' | grep -v '^$')

if [ -z "$DATABASES" ]; then
    log "WARNING: could not enumerate databases, falling back to pg_dumpall"
    OUTFILE="$BACKUP_DIR/all_databases_${TIMESTAMP}.sql.gz"
    docker exec -e PGPASSWORD="$PGPASSWORD" "$POSTGRES_CONTAINER" \
        pg_dumpall -U "$PGUSER" 2>/dev/null | gzip > "$OUTFILE"
    SIZE=$(du -sh "$OUTFILE" | cut -f1)
    log "Backed up all databases -> $OUTFILE ($SIZE)"
else
    for DB in $DATABASES; do
        OUTFILE="$BACKUP_DIR/${DB}_${TIMESTAMP}.sql.gz"
        log "Backing up database: $DB"
        docker exec -e PGPASSWORD="$PGPASSWORD" "$POSTGRES_CONTAINER" \
            pg_dump -U "$PGUSER" --format=plain --no-owner --no-acl "$DB" 2>/dev/null \
            | gzip > "$OUTFILE"
        SIZE=$(du -sh "$OUTFILE" | cut -f1)
        log "  -> $OUTFILE ($SIZE)"
    done
fi

# Remove backups older than RETAIN_DAYS
DELETED=$(find "$BACKUP_DIR" -name "*.sql.gz" -mtime "+${RETAIN_DAYS}" -print -delete | wc -l)
if [ "$DELETED" -gt 0 ]; then
    log "Removed $DELETED backup(s) older than ${RETAIN_DAYS} days"
fi

TOTAL=$(du -sh "$BACKUP_DIR" 2>/dev/null | cut -f1)
FILES=$(find "$BACKUP_DIR" -name "*.sql.gz" | wc -l)
log "Backup complete. Total: $FILES files, $TOTAL on disk."
log "=== Done ==="
