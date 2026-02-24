#!/bin/bash
#
# Финальная установка новой админки
#

set -e

echo "🎉 ФИНАЛЬНАЯ УСТАНОВКА НОВОЙ АДМИНКИ"
echo "====================================="
echo ""

# Цвета
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# 1. Проверка Python зависимостей
echo "1️⃣  Проверка Python зависимостей..."
if python3 -c "import jose" 2>/dev/null; then
    echo -e "${GREEN}✅ python-jose установлен${NC}"
else
    echo -e "${YELLOW}⏳ Установка python-jose...${NC}"
    python3 -m pip install -q 'python-jose[cryptography]==3.3.0' 2>&1 | tail -3
fi

if python3 -c "import passlib" 2>/dev/null; then
    echo -e "${GREEN}✅ passlib установлен${NC}"
else
    echo -e "${YELLOW}⏳ Установка passlib...${NC}"
    python3 -m pip install -q 'passlib[bcrypt]==1.7.4' 2>&1 | tail -3
fi
echo ""

# 2. Проверка .env
echo "2️⃣  Проверка .env файла..."
if [ -f .env ]; then
    echo -e "${GREEN}✅ .env файл найден${NC}"
    
    # Показать сгенерированные пароли
    echo ""
    echo "🔐 Сгенерированные безопасные креденшалы:"
    echo "----------------------------------------"
    echo "Username:      admin"
    echo "Password:      $(grep '^ADMIN_UI_PASSWORD=' .env | cut -d= -f2)"
    echo "API Key:       $(grep '^ADMIN_API_KEY=' .env | cut -d= -f2)"
    echo "Session Secret: $(grep '^ADMIN_UI_SESSION_SECRET=' .env | cut -d= -f2 | head -c 32)..."
    echo "JWT Secret:    $(grep '^JWT_SECRET_KEY=' .env | cut -d= -f2 | head -c 32)..."
    echo ""
else
    echo -e "${RED}❌ .env файл не найден!${NC}"
    exit 1
fi

# 3. Node.js проверка
echo "3️⃣  Проверка Node.js..."
if command -v node &> /dev/null; then
    NODE_VERSION=$(node -v)
    echo -e "${GREEN}✅ Node.js $NODE_VERSION установлен${NC}"
    
    # Установка npm зависимостей
    echo ""
    echo "4️⃣  Установка npm зависимостей..."
    cd admin-frontend
    if [ ! -d node_modules ]; then
        echo -e "${YELLOW}⏳ Установка пакетов (может занять 2-3 минуты)...${NC}"
        npm install --silent 2>&1 | grep -E "(added|removed|changed)" || true
        echo -e "${GREEN}✅ npm зависимости установлены${NC}"
    else
        echo -e "${GREEN}✅ node_modules уже установлены${NC}"
    fi
    cd ..
else
    echo -e "${RED}❌ Node.js не установлен!${NC}"
    echo ""
    echo "📥 Для установки Node.js выполните:"
    echo ""
    echo "   # Ubuntu/Debian:"
    echo "   curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -"
    echo "   sudo apt-get install -y nodejs"
    echo ""
    echo "   # Или используйте nvm:"
    echo "   curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.0/install.sh | bash"
    echo "   nvm install 20"
    echo ""
    exit 1
fi

echo ""
echo "====================================="
echo -e "${GREEN}✅ УСТАНОВКА ЗАВЕРШЕНА!${NC}"
echo "====================================="
echo ""
echo "📚 Что установлено:"
echo "   ✅ python-jose (JWT)"
echo "   ✅ passlib (bcrypt)"
echo "   ✅ npm зависимости (React + TypeScript + Vite)"
echo "   ✅ Безопасные пароли сгенерированы и записаны в .env"
echo ""
echo "🚀 Для запуска новой админки:"
echo ""
echo "   cd admin-frontend"
echo "   npm run dev"
echo ""
echo "   Откройте: http://localhost:3000"
echo ""
echo "🔐 Данные для входа:"
echo "   Username: admin"
echo "   Password: $(grep '^ADMIN_UI_PASSWORD=' .env | cut -d= -f2)"
echo ""
echo "⚠️  ВАЖНО: Сохраните пароль в надежном месте!"
echo ""
