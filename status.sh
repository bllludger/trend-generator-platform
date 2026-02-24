#!/bin/bash
#
# TREND GENERATOR - STATUS SCRIPT
# Показать статус всех сервисов
#

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

# Determine compose command
if docker compose version &> /dev/null 2>&1; then
    COMPOSE_CMD="docker compose"
else
    COMPOSE_CMD="docker-compose"
fi

echo ""
echo -e "${CYAN}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║${NC}  ${BOLD}TREND GENERATOR - СТАТУС СЕРВИСОВ${NC}                      ${CYAN}║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""

# ============================================
# CONTAINER STATUS
# ============================================

echo -e "${BOLD}Контейнеры:${NC}"
echo ""
$COMPOSE_CMD ps 2>/dev/null || echo "Docker Compose не найден или не запущен"
echo ""

# ============================================
# HEALTH CHECKS
# ============================================

echo -e "${BOLD}Проверка доступности:${NC}"
echo ""

check_service() {
    local name=$1
    local url=$2
    local response=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 2 "$url" 2>/dev/null)
    if [ "$response" = "200" ]; then
        echo -e "  ${GREEN}✓${NC} $name - ${GREEN}OK${NC} ($url)"
    else
        echo -e "  ${RED}✗${NC} $name - ${RED}НЕДОСТУПЕН${NC} ($url)"
    fi
}

check_service "Admin UI" "http://${SERVER_IP}:3000"
check_service "Backend API (через админку)" "http://${SERVER_IP}:3000/api/health"
check_service "Cleanup API (localhost)" "http://127.0.0.1:8001/health"

echo ""

# ============================================
# RESOURCE USAGE
# ============================================

echo -e "${BOLD}Использование ресурсов:${NC}"
echo ""
docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}" 2>/dev/null | head -10 || echo "Не удалось получить статистику"
echo ""

# ============================================
# LOGS PREVIEW
# ============================================

echo -e "${BOLD}Последние логи (ошибки):${NC}"
echo ""
$COMPOSE_CMD logs --tail=5 2>&1 | grep -i "error\|exception\|failed" | tail -5 || echo "  Ошибок не найдено"
echo ""

# ============================================
# QUICK LINKS
# ============================================

echo -e "${BOLD}Ссылки (извне доступна только админка):${NC}"
echo -e "  ${CYAN}Админка:${NC}      http://${SERVER_IP}:3000"
echo -e "  ${CYAN}API (внутр.):${NC}  http://127.0.0.1:8000  (через админку: ${SERVER_IP}:3000/api)"
echo ""

echo -e "${BOLD}Команды:${NC}"
echo -e "  ${YELLOW}./start.sh${NC}    - Запустить все"
echo -e "  ${YELLOW}./stop.sh${NC}     - Остановить все"
echo -e "  ${YELLOW}./restart.sh${NC}  - Перезапустить"
echo -e "  ${YELLOW}./logs.sh${NC}     - Смотреть логи"
echo ""
