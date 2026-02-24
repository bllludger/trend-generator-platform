#!/bin/bash
#
# TREND GENERATOR - STOP SCRIPT
# Остановка всех сервисов
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

echo ""
echo -e "${CYAN}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║${NC}  ${BOLD}TREND GENERATOR - ОСТАНОВКА СЕРВИСОВ${NC}                   ${CYAN}║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""

# Determine compose command
if docker compose version &> /dev/null 2>&1; then
    COMPOSE_CMD="docker compose"
else
    COMPOSE_CMD="docker-compose"
fi

# Parse arguments
REMOVE_VOLUMES=false
REMOVE_IMAGES=false
FULL_CLEANUP=false
FORCE_KILL=false

show_help() {
    echo -e "${BOLD}Использование:${NC} ./stop.sh [ОПЦИИ]"
    echo ""
    echo -e "${BOLD}Опции:${NC}"
    echo "  -v, --volumes   Удалить volumes (данные БД будут потеряны!)"
    echo "  -i, --images    Удалить собранные образы"
    echo "  --full          Полная очистка (volumes + images + networks)"
    echo "  -k, --force-kill Убить процессы на портах 3000/8000/8001"
    echo "  -h, --help      Показать эту справку"
    echo ""
    echo -e "${BOLD}Защита БД:${NC} При -v/--full скрипт запросит ввод слова DELETE."
    echo "  Без подтверждения volume не удаляется. Из скрипта: CONFIRM_DESTROY_DB=yes ./stop.sh -v"
    echo ""
    echo -e "${BOLD}Примеры:${NC}"
    echo "  ./stop.sh              # Просто остановить контейнеры (данные сохраняются)"
    echo "  ./stop.sh -v            # Остановить и удалить данные (попросит ввести DELETE)"
    echo "  ./stop.sh --full       # Полная очистка всего (попросит ввести DELETE)"
    echo ""
    exit 0
}

while [[ $# -gt 0 ]]; do
    case $1 in
        -v|--volumes)
            REMOVE_VOLUMES=true
            shift
            ;;
        -i|--images)
            REMOVE_IMAGES=true
            shift
            ;;
        --full)
            FULL_CLEANUP=true
            REMOVE_VOLUMES=true
            REMOVE_IMAGES=true
            shift
            ;;
        -k|--force-kill)
            FORCE_KILL=true
            shift
            ;;
        -h|--help)
            show_help
            ;;
        *)
            echo -e "${RED}Неизвестная опция: $1${NC}"
            echo "Используйте --help для справки"
            exit 1
            ;;
    esac
done

# ============================================
# STOP CONTAINERS
# ============================================

echo -e "${BLUE}[1/3]${NC} Остановка контейнеров..."

if $COMPOSE_CMD ps -q 2>/dev/null | grep -q .; then
    # Таймаут 30с на stop, чтобы не зависнуть при «упрямом» контейнере
    (timeout 30 $COMPOSE_CMD stop 2>/dev/null) || $COMPOSE_CMD stop 2>/dev/null || true
    echo -e "${GREEN}  ✓  Контейнеры остановлены${NC}"
else
    echo -e "${YELLOW}  ⚠  Контейнеры уже остановлены${NC}"
fi

# ============================================
# REMOVE CONTAINERS
# ============================================

echo -e "${BLUE}[2/3]${NC} Удаление контейнеров..."
# Таймаут 45с — чтобы не зависнуть, если down долго ждёт сети/контейнеры
(timeout 45 $COMPOSE_CMD down 2>/dev/null) || true
echo -e "${GREEN}  ✓  Контейнеры удалены${NC}"

# ============================================
# CLEANUP (if requested)
# ============================================

echo -e "${BLUE}[3/3]${NC} Очистка..."

if [ "$REMOVE_VOLUMES" = true ]; then
    # Защита от случайного удаления БД: нужна явная подтверждение
    ALLOW_DESTROY=false
    if [ "${CONFIRM_DESTROY_DB}" = "yes" ]; then
        ALLOW_DESTROY=true
    elif [ -t 0 ]; then
        echo ""
        echo -e "${RED}╔══════════════════════════════════════════════════════════╗${NC}"
        echo -e "${RED}║  ВНИМАНИЕ: Будет удалена ВСЯ база данных (users, jobs).  ║${NC}"
        echo -e "${RED}║  Восстановление без бэкапа НЕВОЗМОЖНО.                    ║${NC}"
        echo -e "${RED}╚══════════════════════════════════════════════════════════╝${NC}"
        echo ""
        echo -e -n "${BOLD}Введите слово DELETE (заглавными) для подтверждения: ${NC}"
        read -r user_confirm
        if [ "$user_confirm" = "DELETE" ]; then
            ALLOW_DESTROY=true
        else
            echo -e "${GREEN}  ✓  Удаление volume отменено. Данные БД сохранены.${NC}"
        fi
    else
        echo -e "${RED}  ✗  Удаление volume отключено (нет TTY).${NC}"
        echo -e "${YELLOW}     Чтобы удалить БД из скрипта, задайте: CONFIRM_DESTROY_DB=yes ./stop.sh -v${NC}"
    fi

    if [ "$ALLOW_DESTROY" = true ]; then
        echo -e "${YELLOW}  ⚠  Удаление volumes (данные БД)...${NC}"
        $COMPOSE_CMD down -v 2>/dev/null || true
        docker volume rm ai_slop_2_postgres_data 2>/dev/null || true
        echo -e "${RED}  ✓  Volumes удалены (данные потеряны)${NC}"
    else
        REMOVE_VOLUMES=false
    fi
fi

if [ "$REMOVE_IMAGES" = true ]; then
    echo -e "${YELLOW}  ⚠  Удаление Docker образов...${NC}"
    $COMPOSE_CMD down --rmi local 2>/dev/null || true
    echo -e "${GREEN}  ✓  Образы удалены${NC}"
fi

if [ "$FULL_CLEANUP" = true ]; then
    echo -e "${YELLOW}  ⚠  Удаление сетей...${NC}"
    docker network rm ai_slop_2_default 2>/dev/null || true
    echo -e "${GREEN}  ✓  Сети удалены${NC}"
    
    echo -e "${YELLOW}  ⚠  Очистка Docker кэша...${NC}"
    docker system prune -f 2>/dev/null || true
    echo -e "${GREEN}  ✓  Кэш очищен${NC}"
fi

if [ "$REMOVE_VOLUMES" = false ] && [ "$REMOVE_IMAGES" = false ]; then
    echo -e "${GREEN}  ✓  Данные сохранены${NC}"
fi

# ============================================
# KILL ANY REMAINING PROCESSES
# ============================================

# Kill any remaining processes on our ports (optional)
if [ "$FORCE_KILL" = true ]; then
    for port in 3000 8000 8001; do
        pid=$(lsof -ti:$port 2>/dev/null || fuser $port/tcp 2>/dev/null | awk '{print $1}' || true)
        if [ -n "$pid" ]; then
            kill -9 $pid 2>/dev/null || true
        fi
    done
else
    echo -e "${YELLOW}  ⚠  Пропуск убийства процессов на портах (используйте --force-kill)${NC}"
fi

# ============================================
# DONE
# ============================================

echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║${NC}  ${BOLD}ВСЕ СЕРВИСЫ ОСТАНОВЛЕНЫ${NC}                                ${GREEN}║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""

if [ "$REMOVE_VOLUMES" = true ]; then
    echo -e "${YELLOW}⚠  Данные базы данных были удалены!${NC}"
    echo ""
fi

echo -e "${BOLD}Для повторного запуска:${NC}"
echo -e "  ${CYAN}./start.sh${NC}"
echo ""

# Show what's left
CONTAINERS=$(docker ps -a --filter "name=ai_slop_2" -q 2>/dev/null | wc -l)
VOLUMES=$(docker volume ls --filter "name=ai_slop_2" -q 2>/dev/null | wc -l)
IMAGES=$(docker images "ai_slop_2*" -q 2>/dev/null | wc -l)

if [ "$CONTAINERS" -gt 0 ] || [ "$VOLUMES" -gt 0 ] || [ "$IMAGES" -gt 0 ]; then
    echo -e "${BOLD}Осталось:${NC}"
    [ "$CONTAINERS" -gt 0 ] && echo -e "  Контейнеры: $CONTAINERS"
    [ "$VOLUMES" -gt 0 ] && echo -e "  Volumes: $VOLUMES"
    [ "$IMAGES" -gt 0 ] && echo -e "  Образы: $IMAGES"
    echo ""
    echo -e "Для полной очистки (с подтверждением DELETE): ${YELLOW}./stop.sh --full${NC}"
    echo ""
fi
