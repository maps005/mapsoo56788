#!/bin/bash
# Backs up the database and survey photos to ./backups (keeps 14 days).
# Schedule daily with:  crontab -e   then add:
#   30 2 * * * cd /opt/faibaplaning && ./deploy/backup.sh >> backups/backup.log 2>&1
set -euo pipefail
umask 077
cd "$(dirname "$0")/.."
. ./.env
mkdir -p backups
STAMP=$(date +%Y%m%d-%H%M)
docker compose exec -T db pg_dump -U "${POSTGRES_USER:-ftth}" "${POSTGRES_DB:-ftth}" | gzip > "backups/db-$STAMP.sql.gz.part"
mv "backups/db-$STAMP.sql.gz.part" "backups/db-$STAMP.sql.gz"   # only complete dumps get the final name
docker compose run --rm --no-deps --user root -v "$(pwd)/backups:/backup" --entrypoint tar web \
  czf "/backup/media-$STAMP.tgz" -C /data .
# keep 14 days, but never delete the newest 3 good backups
ls -1t backups/db-*.sql.gz | tail -n +4 | while read -r f; do [ -n "$(find "$f" -mtime +14)" ] && rm -f "$f"; done
ls -1t backups/media-*.tgz | tail -n +4 | while read -r f; do [ -n "$(find "$f" -mtime +14)" ] && rm -f "$f"; done
echo "$(date) backup $STAMP done"
