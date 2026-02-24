#!/bin/bash
#
# TREND GENERATOR - RESTART SCRIPT
# Перезапуск всех сервисов (stop + start с --force, чтобы подхватить новый compose/конфиг)
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

echo ""
echo -e "${CYAN}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║${NC}  ${BOLD}TREND GENERATOR - ПЕРЕЗАПУСК${NC}                           ${CYAN}║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""

# Stop without removing data (no -v/--full)
./stop.sh

# Start with --force so we always run full startup (migrations, up), even if stop left something behind
./start.sh --force
