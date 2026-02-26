#!/bin/bash
#
# TREND GENERATOR - START SCRIPT
# Запуск всех сервисов
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

# Get server IP
SERVER_IP=$(hostname -I | awk '{print $1}' 2>/dev/null || echo "localhost")

# Determine compose command early for status check
if docker compose version &> /dev/null 2>&1; then
    COMPOSE_CMD="docker compose"
else
    COMPOSE_CMD="docker-compose"
fi

# Flags
FORCE_RESTART=false
FORCE_KILL=false
SHOW_CREDENTIALS=false
for arg in "$@"; do
    case "$arg" in
        --force|-f)
            FORCE_RESTART=true
            ;;
        --force-kill)
            FORCE_KILL=true
            ;;
        --show-credentials)
            SHOW_CREDENTIALS=true
            ;;
    esac
done

# ============================================
# CHECK IF ALREADY RUNNING
# ============================================

check_already_running() {
    # Count running containers
    local running=$($COMPOSE_CMD ps -q 2>/dev/null | wc -l)
    local total=7  # Total expected services
    
    if [ "$running" -ge "$total" ]; then
        # Check if all are healthy/running
        local healthy=$($COMPOSE_CMD ps 2>/dev/null | grep -E "Up|running|healthy" | wc -l)
        if [ "$healthy" -ge "$total" ]; then
            return 0  # All running
        fi
    fi
    return 1  # Not all running
}

show_status() {
    echo ""
    echo -e "${GREEN}╔══════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║${NC}  ${BOLD}ВСЕ СЕРВИСЫ УЖЕ ЗАПУЩЕНЫ!${NC}                              ${GREEN}║${NC}"
    echo -e "${GREEN}╚══════════════════════════════════════════════════════════╝${NC}"
    echo ""
    
    echo -e "${BOLD}Статус контейнеров:${NC}"
    $COMPOSE_CMD ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null || $COMPOSE_CMD ps
    
    echo ""
    echo -e "${BOLD}Доступные сервисы (извне только админка):${NC}"
    echo -e "  ${CYAN}Админка:${NC}  http://${SERVER_IP}:3000"
    echo ""
    
    echo -e "${BOLD}Вход в админку:${NC}"
    echo -e "  ${CYAN}URL:${NC}      http://${SERVER_IP}:3000"
    if [ "$SHOW_CREDENTIALS" = true ]; then
        # Get credentials from .env
        ADMIN_USER=$(grep ADMIN_UI_USERNAME .env 2>/dev/null | cut -d'=' -f2 || echo "admin")
        ADMIN_PASS=$(grep ADMIN_UI_PASSWORD .env 2>/dev/null | cut -d'=' -f2 | head -1 || echo "см. .env")
        echo -e "  ${CYAN}Логин:${NC}    ${ADMIN_USER}"
        echo -e "  ${CYAN}Пароль:${NC}   ${ADMIN_PASS}"
    else
        echo -e "  ${YELLOW}Логин/пароль скрыты. Используйте --show-credentials${NC}"
    fi
    echo ""
    
    echo -e "${BOLD}Команды:${NC}"
    echo -e "  ${YELLOW}./status.sh${NC}   - Подробный статус"
    echo -e "  ${YELLOW}./logs.sh${NC}     - Логи"
    echo -e "  ${YELLOW}./restart.sh${NC}  - Перезапустить"
    echo -e "  ${YELLOW}./stop.sh${NC}     - Остановить"
    echo ""
}

# Check if already running (skip with --force flag)
if [ "$FORCE_RESTART" != true ]; then
    if check_already_running; then
        show_status
        echo -e "${YELLOW}Используйте ${BOLD}./start.sh --force${NC}${YELLOW} для принудительного перезапуска${NC}"
        echo ""
        exit 0
    fi
fi

echo ""
echo -e "${CYAN}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║${NC}  ${BOLD}TREND GENERATOR - ЗАПУСК ВСЕХ СЕРВИСОВ${NC}                 ${CYAN}║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""

# ============================================
# CHECK REQUIREMENTS
# ============================================

echo -e "${BLUE}[1/5]${NC} Проверка требований..."

# Check .env
if [ ! -f .env ]; then
    echo -e "${YELLOW}  ⚠  .env не найден. Копирую из env.example...${NC}"
    if [ -f env.example ]; then
        cp env.example .env
        echo -e "${GREEN}  ✓  Создан .env из env.example${NC}"
        echo -e "${YELLOW}  ⚠  Отредактируйте .env с вашими данными!${NC}"
    else
        echo -e "${RED}  ✗  env.example не найден!${NC}"
        exit 1
    fi
else
    echo -e "${GREEN}  ✓  .env найден${NC}"
fi

# Check Docker
if ! command -v docker &> /dev/null; then
    echo -e "${RED}  ✗  Docker не установлен!${NC}"
    echo -e "${YELLOW}     Установите: curl -fsSL https://get.docker.com | sh${NC}"
    exit 1
fi
echo -e "${GREEN}  ✓  Docker установлен${NC}"

# Check Docker running
if ! docker info &> /dev/null; then
    echo -e "${YELLOW}  ⚠  Docker не запущен. Запускаю...${NC}"
    sudo systemctl start docker 2>/dev/null || service docker start 2>/dev/null || true
    sleep 2
fi

# Determine compose command
if docker compose version &> /dev/null 2>&1; then
    COMPOSE_CMD="docker compose"
else
    COMPOSE_CMD="docker-compose"
fi
echo -e "${GREEN}  ✓  Docker Compose готов${NC}"

# ============================================
# FREE PORTS IF NEEDED
# ============================================

echo -e "${BLUE}[2/5]${NC} Проверка портов..."

free_port() {
    local port=$1
    local pid=$(lsof -ti:$port 2>/dev/null || fuser $port/tcp 2>/dev/null | awk '{print $1}' || true)
    if [ -n "$pid" ]; then
        if [ "$FORCE_KILL" = true ]; then
            echo -e "${YELLOW}  ⚠  Порт $port занят (PID: $pid). Освобождаю...${NC}"
            kill -9 $pid 2>/dev/null || true
            sleep 1
        else
            echo -e "${YELLOW}  ⚠  Порт $port занят (PID: $pid). Пропускаю (используйте --force-kill)${NC}"
        fi
    fi
}

# Free ports that might be in use
for port in 3000 8000 8001 5432 6379; do
    free_port $port
done
echo -e "${GREEN}  ✓  Проверка портов завершена${NC}"

# ============================================
# BUILD CONTAINERS
# ============================================

echo -e "${BLUE}[3/5]${NC} Сборка контейнеров..."
$COMPOSE_CMD build --quiet 2>/dev/null || $COMPOSE_CMD build
echo -e "${GREEN}  ✓  Контейнеры собраны${NC}"

# ============================================
# START DATABASE & REDIS FIRST
# ============================================

echo -e "${BLUE}[4/5]${NC} Запуск базы данных..."
$COMPOSE_CMD up -d db redis
echo -e "${YELLOW}     Ожидание PostgreSQL...${NC}"

# Wait for PostgreSQL (accept connection to any existing DB)
for i in {1..30}; do
    if $COMPOSE_CMD exec -T db pg_isready -U trends -d postgres &>/dev/null || $COMPOSE_CMD exec -T db pg_isready -U trends -d trends &>/dev/null; then
        echo -e "${GREEN}  ✓  PostgreSQL готов${NC}"
        break
    fi
    sleep 1
    if [ $i -eq 30 ]; then
        echo -e "${RED}  ✗  PostgreSQL не запустился за 30 секунд${NC}"
        exit 1
    fi
done

# Ensure database "trends" exists (volume may have been created with POSTGRES_DB=postgres)
echo -e "${YELLOW}     Проверка базы trends...${NC}"
if ! $COMPOSE_CMD exec -T db psql -U trends -d trends -t -A -c "SELECT 1;" &>/dev/null; then
    if $COMPOSE_CMD exec -T db psql -U trends -d postgres -t -A -c "SELECT 1;" &>/dev/null; then
        $COMPOSE_CMD exec -T db psql -U trends -d postgres -c "CREATE DATABASE trends;" 2>/dev/null && echo -e "${GREEN}  ✓  База trends создана${NC}" || true
    else
        $COMPOSE_CMD exec -T db psql -U postgres -d postgres -c "CREATE DATABASE trends; CREATE USER trends WITH PASSWORD 'trends' SUPERUSER; GRANT ALL PRIVILEGES ON DATABASE trends TO trends;" 2>/dev/null && echo -e "${GREEN}  ✓  База trends и пользователь созданы${NC}" || true
    fi
fi

# Run migrations
echo -e "${YELLOW}     Применение миграций...${NC}"
if [ -f migrations/schema.sql ]; then
    $COMPOSE_CMD exec -T db psql -U trends -d trends -f /dev/stdin < migrations/schema.sql 2>/dev/null || true
fi
# Seed trends ONLY when table is empty — do not overwrite admin edits on restart
# If SELECT fails (e.g. table missing), treat as 0 so seed runs and fills DB
if [ -f migrations/seed/001_trends.sql ]; then
    TREND_COUNT=$($COMPOSE_CMD exec -T db psql -U trends -d trends -t -A -c "SELECT COUNT(*) FROM trends;" 2>/dev/null | tr -d '\r\n' || echo "0")
    if [ "$TREND_COUNT" = "0" ]; then
        $COMPOSE_CMD exec -T db psql -U trends -d trends -f /dev/stdin < migrations/seed/001_trends.sql 2>/dev/null || true
        echo -e "${GREEN}  ✓ Сид трендов применён (таблица была пуста)${NC}"
    else
        echo -e "${GREEN}  ✓ Тренды уже есть в БД, сид пропущен (сохраняем правки из админки)${NC}"
    fi
fi
if [ -f migrations/002_telemetry_snapshots.sql ]; then
    $COMPOSE_CMD exec -T db psql -U trends -d trends -f /dev/stdin < migrations/002_telemetry_snapshots.sql 2>/dev/null || true
fi
if [ -f migrations/003_security_fields.sql ]; then
    $COMPOSE_CMD exec -T db psql -U trends -d trends -f /dev/stdin < migrations/003_security_fields.sql 2>/dev/null || true
fi
if [ -f migrations/004_security_settings.sql ]; then
    $COMPOSE_CMD exec -T db psql -U trends -d trends -f /dev/stdin < migrations/004_security_settings.sql 2>/dev/null || true
fi
if [ -f migrations/005_user_telegram_profile.sql ]; then
    $COMPOSE_CMD exec -T db psql -U trends -d trends -f /dev/stdin < migrations/005_user_telegram_profile.sql 2>/dev/null || true
fi
if [ -f migrations/006_performance_indexes.sql ]; then
    $COMPOSE_CMD exec -T db psql -U trends -d trends -f /dev/stdin < migrations/006_performance_indexes.sql 2>/dev/null || true
fi
if [ -f migrations/007_job_custom_prompt_format.sql ]; then
    $COMPOSE_CMD exec -T db psql -U trends -d trends -f /dev/stdin < migrations/007_job_custom_prompt_format.sql 2>/dev/null || true
fi
if [ -f migrations/008_free_generations_balance.sql ]; then
    $COMPOSE_CMD exec -T db psql -U trends -d trends -f /dev/stdin < migrations/008_free_generations_balance.sql 2>/dev/null || true
fi
if [ -f migrations/009_copy_quota.sql ]; then
    $COMPOSE_CMD exec -T db psql -U trends -d trends -f /dev/stdin < migrations/009_copy_quota.sql 2>/dev/null || true
fi
if [ -f migrations/010_is_moderator.sql ]; then
    $COMPOSE_CMD exec -T db psql -U trends -d trends -f /dev/stdin < migrations/010_is_moderator.sql 2>/dev/null || true
fi
if [ -f migrations/011_copy_style_settings.sql ]; then
    $COMPOSE_CMD exec -T db psql -U trends -d trends -f /dev/stdin < migrations/011_copy_style_settings.sql 2>/dev/null || true
fi
if [ -f migrations/012_copy_style_prompt_suffix.sql ]; then
    $COMPOSE_CMD exec -T db psql -U trends -d trends -f /dev/stdin < migrations/012_copy_style_prompt_suffix.sql 2>/dev/null || true
fi
if [ -f migrations/013_trend_example_image.sql ]; then
    $COMPOSE_CMD exec -T db psql -U trends -d trends -f /dev/stdin < migrations/013_trend_example_image.sql 2>/dev/null || true
fi
if [ -f migrations/014_generation_prompt_settings.sql ]; then
    $COMPOSE_CMD exec -T db psql -U trends -d trends -f /dev/stdin < migrations/014_generation_prompt_settings.sql 2>/dev/null || true
fi
if [ -f migrations/015_copy_style_instruction_prompts.sql ]; then
    $COMPOSE_CMD exec -T db psql -U trends -d trends -f /dev/stdin < migrations/015_copy_style_instruction_prompts.sql 2>/dev/null || true
fi
if [ -f migrations/016_copy_style_generation_prompt.sql ]; then
    $COMPOSE_CMD exec -T db psql -U trends -d trends -f /dev/stdin < migrations/016_copy_style_generation_prompt.sql 2>/dev/null || true
fi
if [ -f migrations/017_trend_scene_subject.sql ]; then
    $COMPOSE_CMD exec -T db psql -U trends -d trends -f /dev/stdin < migrations/017_trend_scene_subject.sql 2>/dev/null || true
fi
if [ -f migrations/018_generation_prompt_sections.sql ]; then
    $COMPOSE_CMD exec -T db psql -U trends -d trends -f /dev/stdin < migrations/018_generation_prompt_sections.sql 2>/dev/null || true
fi
if [ -f migrations/019_backfill_scene_prompt.sql ]; then
    $COMPOSE_CMD exec -T db psql -U trends -d trends -f /dev/stdin < migrations/019_backfill_scene_prompt.sql 2>/dev/null || true
fi
if [ -f migrations/020_trend_scene_only_and_transfer_policy.sql ]; then
    $COMPOSE_CMD exec -T db psql -U trends -d trends -f /dev/stdin < migrations/020_trend_scene_only_and_transfer_policy.sql 2>/dev/null || true
fi
if [ -f migrations/021_transfer_policy_avoid_default.sql ]; then
    $COMPOSE_CMD exec -T db psql -U trends -d trends -f /dev/stdin < migrations/021_transfer_policy_avoid_default.sql 2>/dev/null || true
fi
if [ -f migrations/022_trend_style_reference_image.sql ]; then
    $COMPOSE_CMD exec -T db psql -U trends -d trends -f /dev/stdin < migrations/022_trend_style_reference_image.sql 2>/dev/null || true
fi
if [ -f migrations/023_trend_prompt_sections.sql ]; then
    $COMPOSE_CMD exec -T db psql -U trends -d trends -f /dev/stdin < migrations/023_trend_prompt_sections.sql 2>/dev/null || true
fi
if [ -f migrations/024_payments_packs.sql ]; then
    $COMPOSE_CMD exec -T db psql -U trends -d trends -f /dev/stdin < migrations/024_payments_packs.sql 2>/dev/null || true
fi
if [ -f migrations/025_app_settings.sql ]; then
    $COMPOSE_CMD exec -T db psql -U trends -d trends -f /dev/stdin < migrations/025_app_settings.sql 2>/dev/null || true
fi
if [ -f migrations/026_image_size_tier.sql ]; then
    $COMPOSE_CMD exec -T db psql -U trends -d trends -f /dev/stdin < migrations/026_image_size_tier.sql 2>/dev/null || true
fi
if [ -f migrations/027_trend_playground_profile.sql ]; then
    $COMPOSE_CMD exec -T db psql -U trends -d trends -f /dev/stdin < migrations/027_trend_playground_profile.sql 2>/dev/null || true
fi
if [ -f migrations/028_telegram_message_templates.sql ]; then
    $COMPOSE_CMD exec -T db psql -U trends -d trends -f /dev/stdin < migrations/028_telegram_message_templates.sql 2>/dev/null || true
fi
if [ -f migrations/030_bank_transfer_settings.sql ]; then
    $COMPOSE_CMD exec -T db psql -U trends -d trends -f /dev/stdin < migrations/030_bank_transfer_settings.sql 2>/dev/null || true
fi
if [ -f migrations/031_bank_transfer_receipt_log.sql ]; then
    $COMPOSE_CMD exec -T db psql -U trends -d trends -f /dev/stdin < migrations/031_bank_transfer_receipt_log.sql 2>/dev/null || true
fi
if [ -f migrations/032_receipt_log_card_match.sql ]; then
    $COMPOSE_CMD exec -T db psql -U trends -d trends -f /dev/stdin < migrations/032_receipt_log_card_match.sql 2>/dev/null || true
fi
if [ -f migrations/033_receipt_prompts_json_default.sql ]; then
    $COMPOSE_CMD exec -T db psql -U trends -d trends -f /dev/stdin < migrations/033_receipt_prompts_json_default.sql 2>/dev/null || true
fi
if [ -f migrations/034_generation_prompt_four_blocks.sql ]; then
    $COMPOSE_CMD exec -T db psql -U trends -d trends -f /dev/stdin < migrations/034_generation_prompt_four_blocks.sql 2>/dev/null || true
fi
if [ -f migrations/035_themes_and_trend_theme_id.sql ]; then
    $COMPOSE_CMD exec -T db psql -U trends -d trends -f /dev/stdin < migrations/035_themes_and_trend_theme_id.sql 2>/dev/null || true
fi
if [ -f migrations/036_transfer_policy_scope.sql ]; then
    $COMPOSE_CMD exec -T db psql -U trends -d trends -f /dev/stdin < migrations/036_transfer_policy_scope.sql 2>/dev/null || true
fi
if [ -f migrations/037_job_unlocked_at_unlock_method.sql ]; then
    $COMPOSE_CMD exec -T db psql -U trends -d trends -f /dev/stdin < migrations/037_job_unlocked_at_unlock_method.sql 2>/dev/null || true
fi
if [ -f migrations/038_referral_program.sql ]; then
    $COMPOSE_CMD exec -T db psql -U trends -d trends -f /dev/stdin < migrations/038_referral_program.sql 2>/dev/null || true
fi
if [ -f migrations/039_premium_packs.sql ]; then
    $COMPOSE_CMD exec -T db psql -U trends -d trends -f /dev/stdin < migrations/039_premium_packs.sql 2>/dev/null || true
fi
if [ -f migrations/040_sessions_takes_favorites.sql ]; then
    $COMPOSE_CMD exec -T db psql -U trends -d trends -f /dev/stdin < migrations/040_sessions_takes_favorites.sql 2>/dev/null || true
fi
if [ -f migrations/041_migrate_tokens_to_hd.sql ]; then
    $COMPOSE_CMD exec -T db psql -U trends -d trends -f /dev/stdin < migrations/041_migrate_tokens_to_hd.sql 2>/dev/null || true
fi
if [ -f migrations/042_favorites_updated_at.sql ]; then
    $COMPOSE_CMD exec -T db psql -U trends -d trends -f /dev/stdin < migrations/042_favorites_updated_at.sql 2>/dev/null || true
fi
if [ -f migrations/043_outcome_collections.sql ]; then
    $COMPOSE_CMD exec -T db psql -U trends -d trends -f /dev/stdin < migrations/043_outcome_collections.sql 2>/dev/null || true
fi
if [ -f migrations/044_sku_ladder_disable_legacy.sql ]; then
    $COMPOSE_CMD exec -T db psql -U trends -d trends -f /dev/stdin < migrations/044_sku_ladder_disable_legacy.sql 2>/dev/null || true
fi
if [ -f migrations/045_trend_composition_prompt.sql ]; then
    $COMPOSE_CMD exec -T db psql -U trends -d trends -f /dev/stdin < migrations/045_trend_composition_prompt.sql 2>/dev/null || true
fi
# Роль postgres: создать или обновить пароль (внешние клиенты/IDE часто подключаются как postgres → убираем FATAL в логах)
if ! $COMPOSE_CMD exec -T db psql -U trends -d trends -c "
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'postgres') THEN
    CREATE ROLE postgres WITH LOGIN PASSWORD 'postgres' SUPERUSER;
  ELSE
    ALTER ROLE postgres WITH PASSWORD 'postgres';
  END IF;
END \$\$;
"; then
  echo -e "${YELLOW}  ⚠  Не удалось задать пароль для postgres (FATAL в логах будут, если IDE подключается как postgres). Запустите: ./scripts/fix_postgres_role.sh${NC}"
else
  # Явные права на БД trends для роли postgres (подключение IDE/pgAdmin)
  $COMPOSE_CMD exec -T db psql -U trends -d trends -c "
  GRANT CONNECT ON DATABASE trends TO postgres;
  GRANT USAGE ON SCHEMA public TO postgres;
  GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO postgres;
  GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO postgres;
  " 2>/dev/null || true
fi
echo -e "${GREEN}  ✓  База данных инициализирована${NC}"

# ============================================
# START ALL SERVICES
# ============================================

echo -e "${BLUE}[5/5]${NC} Запуск всех сервисов..."
$COMPOSE_CMD up -d

# Wait for services to be healthy (API has start_period 60s + retries)
echo -e "${YELLOW}     Ожидание запуска сервисов...${NC}"
sleep 5

# Wait for API to become healthy (up to 90s)
for i in {1..18}; do
    if $COMPOSE_CMD ps api 2>/dev/null | grep -q "healthy"; then
        break
    fi
    sleep 5
    if [ $i -eq 18 ]; then
        echo -e "${RED}  ✗ API не прошёл healthcheck за 90 секунд${NC}"
        echo -e "${YELLOW}     Последние логи API:${NC}"
        $COMPOSE_CMD logs api --tail 80 2>/dev/null || true
        echo ""
        echo -e "${YELLOW}     Проверьте .env (ADMIN_UI_USERNAME, ADMIN_UI_PASSWORD, ADMIN_UI_SESSION_SECRET ≥16 символов). Логи: $COMPOSE_CMD logs -f api${NC}"
        exit 1
    fi
done

# ============================================
# SHOW STATUS
# ============================================

echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║${NC}  ${BOLD}ВСЕ СЕРВИСЫ УСПЕШНО ЗАПУЩЕНЫ!${NC}                          ${GREEN}║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""

# Show container status
echo -e "${BOLD}Статус контейнеров:${NC}"
$COMPOSE_CMD ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null || $COMPOSE_CMD ps

echo ""
echo -e "${BOLD}Доступные сервисы (извне только админка):${NC}"
echo -e "  ${CYAN}Админка:${NC}          http://${SERVER_IP}:3000"
echo -e "  ${CYAN}API (localhost):${NC}  http://127.0.0.1:8000  (извне — через админку /api)"
echo -e "  ${CYAN}Cleanup (localhost):${NC} http://127.0.0.1:8001"
echo ""

echo -e "${BOLD}Внутренние (только localhost):${NC}"
echo -e "  ${CYAN}PostgreSQL:${NC} 127.0.0.1:5432  ${CYAN}Redis:${NC} 127.0.0.1:6379"
echo ""

echo -e "${BOLD}Вход в админку:${NC}"
echo -e "  ${CYAN}URL:${NC}      http://${SERVER_IP}:3000"
if [ "$SHOW_CREDENTIALS" = true ]; then
    # Get credentials from .env
    ADMIN_USER=$(grep ADMIN_UI_USERNAME .env 2>/dev/null | cut -d'=' -f2 || echo "admin")
    ADMIN_PASS=$(grep ADMIN_UI_PASSWORD .env 2>/dev/null | cut -d'=' -f2 | head -1 || echo "см. .env")
    echo -e "  ${CYAN}Логин:${NC}    ${ADMIN_USER}"
    echo -e "  ${CYAN}Пароль:${NC}   ${ADMIN_PASS}"
else
    echo -e "  ${YELLOW}Логин/пароль скрыты. Используйте --show-credentials${NC}"
fi
echo ""

echo -e "${BOLD}Команды:${NC}"
echo -e "  ${YELLOW}Логи:${NC}     $COMPOSE_CMD logs -f"
echo -e "  ${YELLOW}Статус:${NC}   $COMPOSE_CMD ps"
echo -e "  ${YELLOW}Стоп:${NC}     ./stop.sh"
echo ""
