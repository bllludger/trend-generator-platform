#!/usr/bin/env bash
# Применяет миграции 040, 041, 042 (Session/Take/Favorites + HD) к уже запущенной БД.
# Использование: ./scripts/apply_session_migrations.sh
# Требует: docker compose (или docker-compose) и запущенный контейнер db.

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT_DIR"

COMPOSE_CMD="docker compose"
command -v docker compose &>/dev/null || COMPOSE_CMD="docker-compose"

if ! $COMPOSE_CMD exec -T db psql -U trends -d trends -t -A -c "SELECT 1;" &>/dev/null; then
    echo "Ошибка: контейнер db не запущен или БД trends недоступна. Запустите: $COMPOSE_CMD up -d db"
    exit 1
fi

echo "Применение миграций 040, 041, 042..."
for f in migrations/040_sessions_takes_favorites.sql migrations/041_migrate_tokens_to_hd.sql migrations/042_favorites_updated_at.sql; do
    if [ -f "$f" ]; then
        echo "  -> $f"
        $COMPOSE_CMD exec -T db psql -U trends -d trends -f /dev/stdin < "$f" || { echo "  Ошибка при применении $f"; exit 1; }
    else
        echo "  Пропуск (файл не найден): $f"
    fi
done
echo "Готово. Перезапустите бота при необходимости: $COMPOSE_CMD restart bot"
