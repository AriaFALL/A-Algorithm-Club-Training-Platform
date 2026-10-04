#!/usr/bin/env sh
set -eu

PROJECT_DIR=${PROJECT_DIR:-/opt/club-platform}
BACKUP_DIR=${BACKUP_DIR:-$PROJECT_DIR/backups}
STAMP=$(date +%Y%m%d-%H%M%S)
mkdir -p "$BACKUP_DIR"
cd "$PROJECT_DIR"
docker compose exec -T db pg_dump -U "${POSTGRES_USER:-club}" -d "${POSTGRES_DB:-club_platform}" > "$BACKUP_DIR/db-$STAMP.sql"
docker run --rm -v club-platform_media_data:/source -v "$BACKUP_DIR:/backup" alpine tar czf "/backup/media-$STAMP.tar.gz" -C /source .
find "$BACKUP_DIR" -type f -mtime +30 -delete
