#!/bin/bash
#
# Автоматическая миграция админки
# Проверка безопасности и установка новой версии
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "🔒 МИГРАЦИЯ АДМИНКИ НА НОВУЮ ВЕРСИЮ"
echo "===================================="
echo ""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 1. Проверка зависимостей
echo "1️⃣  Проверка Python зависимостей..."
if pip list 2>/dev/null | grep -q python-jose; then
    echo -e "${GREEN}✅ python-jose установлен${NC}"
else
    echo -e "${YELLOW}⏳ Установка python-jose...${NC}"
    pip install 'python-jose[cryptography]==3.3.0'
fi

if pip list 2>/dev/null | grep -q passlib; then
    echo -e "${GREEN}✅ passlib установлен${NC}"
else
    echo -e "${YELLOW}⏳ Установка passlib...${NC}"
    pip install 'passlib[bcrypt]==1.7.4'
fi
echo ""

# 2. Проверка .env
echo "2️⃣  Проверка .env файла..."
if [ ! -f .env ]; then
    if [ -f .env_test ]; then
        echo -e "${YELLOW}⚠️  .env не найден, копирую из .env_test${NC}"
        cp .env_test .env
    else
        echo -e "${RED}❌ .env файл не найден!${NC}"
        exit 1
    fi
fi

# Проверка критичных переменных
REQUIRED_VARS=("ADMIN_UI_USERNAME" "ADMIN_UI_PASSWORD" "ADMIN_UI_SESSION_SECRET")
MISSING=0
for VAR in "${REQUIRED_VARS[@]}"; do
    if ! grep -q "^${VAR}=" .env; then
        echo -e "${RED}❌ ${VAR} не найден в .env!${NC}"
        MISSING=1
    fi
done

if [ $MISSING -eq 1 ]; then
    exit 1
fi
echo -e "${GREEN}✅ .env файл проверен${NC}"
echo ""

# 3. Проверка безопасности
echo "3️⃣  🔒 Проверка безопасности паролей..."
SECURITY_ISSUES=0

if grep -qE "^ADMIN_UI_PASSWORD=(admin|password|123456|changeme)$" .env; then
    echo -e "${RED}⚠️  КРИТИЧНО: Слабый пароль обнаружен!${NC}"
    echo "   Текущий пароль: $(grep '^ADMIN_UI_PASSWORD=' .env | cut -d= -f2)"
    echo "   Пожалуйста, смените ADMIN_UI_PASSWORD в .env файле"
    echo "   Рекомендуется: минимум 12 символов, mixed case + цифры + спецсимволы"
    SECURITY_ISSUES=1
fi

if grep -qE "^ADMIN_UI_SESSION_SECRET=(changeme|secret|admin|password)$" .env; then
    echo -e "${RED}⚠️  КРИТИЧНО: Слабый session secret обнаружен!${NC}"
    echo "   Сгенерируйте новый: openssl rand -hex 32"
    echo "   И замените ADMIN_UI_SESSION_SECRET в .env"
    SECURITY_ISSUES=1
fi

if grep -qE "^ADMIN_API_KEY=(changeme|admin|password)$" .env; then
    echo -e "${YELLOW}⚠️  ВНИМАНИЕ: Слабый API key обнаружен!${NC}"
    echo "   Сгенерируйте новый: openssl rand -hex 16"
    echo "   И замените ADMIN_API_KEY в .env"
fi

if [ $SECURITY_ISSUES -eq 1 ]; then
    echo ""
    echo -e "${RED}❌ Обнаружены критические проблемы безопасности!${NC}"
    echo "   Исправьте их в .env файле перед продолжением"
    echo ""
    exit 1
fi
echo -e "${GREEN}✅ Проверка безопасности пройдена${NC}"
echo ""

# 4. Проверка Node.js
echo "4️⃣  Проверка Node.js..."
if ! command -v node &> /dev/null; then
    echo -e "${RED}❌ Node.js не установлен!${NC}"
    echo "   Установите Node.js 18+ и попробуйте снова"
    exit 1
fi

NODE_VERSION=$(node -v | cut -d'v' -f2 | cut -d'.' -f1)
if [ "$NODE_VERSION" -lt 18 ]; then
    echo -e "${RED}❌ Требуется Node.js 18+. Текущая версия: $(node -v)${NC}"
    exit 1
fi
echo -e "${GREEN}✅ Node.js $(node -v) установлен${NC}"
echo ""

# 5. Установка frontend
echo "5️⃣  Установка frontend зависимостей..."
cd admin-frontend
if [ ! -d node_modules ]; then
    echo "⏳ Установка npm пакетов (это может занять минуту)..."
    npm install --silent
else
    echo -e "${GREEN}✅ node_modules уже установлены${NC}"
fi
cd ..
echo -e "${GREEN}✅ Frontend установлен${NC}"
echo ""

# 6. Проверка backend
echo "6️⃣  Проверка backend..."
if curl -f http://localhost:8000/health &> /dev/null; then
    echo -e "${GREEN}✅ Backend работает на http://localhost:8000${NC}"
else
    echo -e "${YELLOW}⚠️  Backend не отвечает на http://localhost:8000${NC}"
    echo "   Запустите backend перед запуском frontend:"
    echo ""
    echo "   docker-compose up db redis -d"
    echo "   uvicorn app.main:app --reload"
    echo ""
fi

# 7. Финальные инструкции
echo ""
echo "===================================="
echo -e "${GREEN}✅ МИГРАЦИЯ ПОДГОТОВЛЕНА!${NC}"
echo "===================================="
echo ""
echo "📚 Следующие шаги:"
echo ""
echo "1️⃣  Запустите новую админку:"
echo "   ${GREEN}cd admin-frontend && npm run dev${NC}"
echo ""
echo "2️⃣  Откройте в браузере:"
echo "   ${GREEN}http://localhost:3000${NC}"
echo ""
echo "3️⃣  Войдите с учетными данными из .env:"
USERNAME=$(grep '^ADMIN_UI_USERNAME=' .env | cut -d= -f2)
PASSWORD=$(grep '^ADMIN_UI_PASSWORD=' .env | cut -d= -f2)
echo "   Username: ${GREEN}${USERNAME}${NC}"
echo "   Password: ${GREEN}${PASSWORD}${NC}"
echo ""
echo "4️⃣  После успешного тестирования:"
echo "   - Старая админка останется доступна на http://localhost:8000/admin-ui"
echo "   - Новая админка будет на http://localhost:3000"
echo "   - Обе могут работать параллельно"
echo ""
echo "📊 Что получили:"
echo "   ✅ JWT authentication (безопаснее session cookies)"
echo "   ✅ bcrypt пароли (безопаснее SHA256)"
echo "   ✅ React + TypeScript (современный стек)"
echo "   ✅ Dark Mode 🌙"
echo "   ✅ Responsive design 📱"
echo "   ✅ Real-time updates ⚡"
echo ""
echo "⚠️  ВАЖНО для production:"
echo "   - Смените пароли в .env на сильные"
echo "   - Включите HTTPS"
echo "   - Настройте rate limiting"
echo "   - Прочитайте: SECURITY_AND_MIGRATION.md"
echo ""
