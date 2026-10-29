#!/usr/bin/env sh
set -eu

PROJECT_DIR=${PROJECT_DIR:-/opt/club-platform}
BACKUP_DIR=${BACKUP_DIR:-$PROJECT_DIR/backups}
STAMP=$(date +%Y%m%d-%H%M%S)
mkdir -p "$BACKUP_DIR"
cd "$PROJECT_DIR"

WEB_CONTAINER=$(docker compose ps -q web)
[ -n "$WEB_CONTAINER" ] || { echo 'Web container not found; backup aborted.' >&2; exit 1; }
MEDIA_VOLUME=$(docker inspect --format '{{range .Mounts}}{{if and (eq .Destination "/app/media") (eq .Type "volume")}}{{.Name}}{{end}}{{end}}' "$WEB_CONTAINER")
[ -n "$MEDIA_VOLUME" ] || { echo 'Media volume not found; backup aborted.' >&2; exit 1; }

docker compose exec -T db sh -c 'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB"' > "$BACKUP_DIR/db-$STAMP.sql"
docker run --rm --mount "type=volume,src=$MEDIA_VOLUME,dst=/source,readonly" -v "$BACKUP_DIR:/backup" alpine tar czf "/backup/media-$STAMP.tar.gz" -C /source .
find "$BACKUP_DIR" -type f \( -name 'db-*.sql' -o -name 'media-*.tar.gz' \) -mtime +30 -delete
