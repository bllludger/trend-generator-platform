#!/bin/bash
#
# TREND GENERATOR - LOGS SCRIPT
# Просмотр логов сервисов
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

# Determine compose command
if docker compose version &> /dev/null 2>&1; then
    COMPOSE_CMD="docker compose"
else
    COMPOSE_CMD="docker-compose"
fi

show_help() {
    echo ""
    echo -e "${BOLD}Использование:${NC} ./logs.sh [СЕРВИС] [ОПЦИИ]"
    echo ""
    echo -e "${BOLD}Сервисы:${NC}"
    echo "  api        - Backend API (FastAPI)"
    echo "  admin-ui   - Админка (React)"
    echo "  bot        - Telegram бот"
    echo "  worker     - Celery worker"
    echo "  cleanup    - Cleanup сервис"
    echo "  db         - PostgreSQL"
    echo "  redis      - Redis"
    echo "  all        - Все сервисы (по умолчанию)"
    echo ""
    echo -e "${BOLD}Опции:${NC}"
    echo "  -f, --follow    Следить за логами в реальном времени"
    echo "  -n, --tail N    Показать последние N строк (по умолчанию 100)"
    echo "  --errors        Показать только ошибки"
    echo "  -h, --help      Показать эту справку"
    echo ""
    echo -e "${BOLD}Примеры:${NC}"
    echo "  ./logs.sh                   # Все логи, последние 100 строк"
    echo "  ./logs.sh api -f            # Следить за логами API"
    echo "  ./logs.sh bot --errors      # Ошибки бота"
    echo "  ./logs.sh worker -n 50      # Последние 50 строк worker"
    echo ""
    exit 0
}

# Defaults
SERVICE="all"
FOLLOW=""
TAIL="100"
ERRORS_ONLY=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        api|admin-ui|bot|worker|cleanup|db|redis|all)
            SERVICE=$1
            shift
            ;;
        -f|--follow)
            FOLLOW="-f"
            shift
            ;;
        -n|--tail)
            TAIL=$2
            shift 2
            ;;
        --errors)
            ERRORS_ONLY=true
            shift
            ;;
        -h|--help)
            show_help
            ;;
        *)
            echo -e "${YELLOW}Неизвестная опция: $1${NC}"
            show_help
            ;;
    esac
done

echo ""
echo -e "${CYAN}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║${NC}  ${BOLD}TREND GENERATOR - ЛОГИ${NC}                                 ${CYAN}║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""

if [ "$SERVICE" = "all" ]; then
    SERVICE_ARG=""
else
    SERVICE_ARG="$SERVICE"
fi

if [ "$ERRORS_ONLY" = true ]; then
    echo -e "${YELLOW}Показываю только ошибки...${NC}"
    echo ""
    $COMPOSE_CMD logs --tail=$TAIL $SERVICE_ARG 2>&1 | grep -i "error\|exception\|failed\|critical"
else
    $COMPOSE_CMD logs --tail=$TAIL $FOLLOW $SERVICE_ARG
fi
