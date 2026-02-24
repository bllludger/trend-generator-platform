#!/bin/bash
# Создаёт/обновляет роль postgres с паролем postgres, чтобы внешние клиенты (IDE, pgAdmin)
# не засоряли логи FATAL при подключении к localhost:5432 как user postgres.
# Запуск: ./scripts/fix_postgres_role.sh  (из корня проекта, при поднятом docker compose)

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

if command -v docker compose &>/dev/null; then
  COMPOSE_CMD="docker compose"
else
  COMPOSE_CMD="docker-compose"
fi

$COMPOSE_CMD exec -T db psql -U trends -d trends -c "
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'postgres') THEN
    CREATE ROLE postgres WITH LOGIN PASSWORD 'postgres' SUPERUSER;
    RAISE NOTICE 'Role postgres created with password postgres';
  ELSE
    ALTER ROLE postgres WITH PASSWORD 'postgres';
    RAISE NOTICE 'Role postgres password updated to postgres';
  END IF;
END \$\$;
"
# Явные права на БД trends (на случай если роль не SUPERUSER или БД создана от пользователя trends)
$COMPOSE_CMD exec -T db psql -U trends -d trends -c "
GRANT CONNECT ON DATABASE trends TO postgres;
GRANT USAGE ON SCHEMA public TO postgres;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO postgres;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO postgres;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO postgres;
" 2>/dev/null || true

# Проверка: подключение postgres/postgres изнутри контейнера
if $COMPOSE_CMD exec -T -e PGPASSWORD=postgres db psql -U postgres -d trends -t -c "SELECT 1" &>/dev/null; then
  echo "OK: подключение postgres/postgres работает."
else
  echo "Проверка из контейнера не удалась (роль postgres может не иметь доступа к БД trends)."
fi

echo ""
echo "Подключение к БД: user=postgres, password=postgres (или user=trends, password=trends)."
echo ""
echo "Если FATAL в логах не прекратились — какой-то клиент подключается с ДРУГИМ паролем"
echo "(часто пустой). Проверьте:"
echo "  • Cursor/VSCode: панель Database/SQL — в настройках подключения укажите пароль postgres;"
echo "  • pgAdmin/DBeaver: в сохранённом подключении укажите пароль postgres;"
echo "  • Или переключите клиент на user=trends, password=trends."
