#!/usr/bin/env bash
# Резервное копирование: PostgreSQL + каталоги prompts, data/trend_examples, data/generated_images.
# Запуск из корня проекта: ./scripts/backup.sh
# Или с указанием каталога: BACKUP_DIR=/path ./scripts/backup.sh
# Опционально выгрузка в S3: BACKUP_S3_URI=s3://bucket/prefix ./scripts/backup.sh (нужен aws cli)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# Подхватить переменные из .env (BACKUP_S3_URI, POSTGRES_*, BACKUP_RETENTION_DAYS)
if [ -f .env ]; then set -a; source .env; set +a; fi

BACKUP_DIR="${BACKUP_DIR:-./backups}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
ARCHIVE_NAME="trend_generator_backup_${TIMESTAMP}"
WORK_DIR="${BACKUP_DIR}/${ARCHIVE_NAME}"
COMPOSE_CMD="docker compose"
[ -n "$COMPOSE_PROJECT_NAME" ] && COMPOSE_CMD="$COMPOSE_CMD -p $COMPOSE_PROJECT_NAME"

mkdir -p "$WORK_DIR"
echo "[backup] Starting at $(date -Iseconds)"

# 1. PostgreSQL
echo "[backup] Dumping PostgreSQL..."
$COMPOSE_CMD exec -T db pg_dump -U "${POSTGRES_USER:-trends}" "${POSTGRES_DB:-trends}" | gzip -9 > "${WORK_DIR}/db.sql.gz"
echo "[backup] PostgreSQL dump done ($(du -h "${WORK_DIR}/db.sql.gz" | cut -f1))"

# 2. Файлы: prompts, trend_examples, generated_images
echo "[backup] Archiving prompts and data..."
tar -czf "${WORK_DIR}/data.tar.gz" \
  -C "$PROJECT_ROOT" \
  prompts \
  data/trend_examples \
  data/generated_images \
  2>/dev/null || true
echo "[backup] Data archive done ($(du -h "${WORK_DIR}/data.tar.gz" 2>/dev/null | cut -f1 || echo "0"))"

# 3. Один итоговый архив
FINAL="${BACKUP_DIR}/${ARCHIVE_NAME}.tar.gz"
tar -czf "$FINAL" -C "$BACKUP_DIR" "$ARCHIVE_NAME"
rm -rf "$WORK_DIR"
echo "[backup] Final archive: $FINAL ($(du -h "$FINAL" | cut -f1))"

# 4. Удаление старых локальных бэкапов
if [ -n "$RETENTION_DAYS" ] && [ "$RETENTION_DAYS" -gt 0 ]; then
  echo "[backup] Removing backups older than $RETENTION_DAYS days..."
  find "$BACKUP_DIR" -maxdepth 1 -name "trend_generator_backup_*.tar.gz" -mtime +"$RETENTION_DAYS" -delete
fi

# 5. Опциональная выгрузка в S3-совместимое хранилище
if [ -n "${BACKUP_S3_URI:-}" ]; then
  if command -v aws &>/dev/null; then
    echo "[backup] Uploading to $BACKUP_S3_URI..."
    aws s3 cp "$FINAL" "${BACKUP_S3_URI%/}/${ARCHIVE_NAME}.tar.gz" --only-show-errors
    echo "[backup] Upload done."
  else
    echo "[backup] WARNING: BACKUP_S3_URI set but 'aws' CLI not found. Install awscli for S3 upload."
  fi
fi

echo "[backup] Finished at $(date -Iseconds)"
