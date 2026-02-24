#!/bin/bash
#
# Установка и запуск новой админ-панели
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/admin-frontend"

echo "🎨 TREND GENERATOR - Установка новой админки"
echo "============================================"
echo ""

# Check Node.js
if ! command -v node &> /dev/null; then
    echo "❌ Node.js не установлен. Установите Node.js 18+ и попробуйте снова."
    exit 1
fi

NODE_VERSION=$(node -v | cut -d'v' -f2 | cut -d'.' -f1)
if [ "$NODE_VERSION" -lt 18 ]; then
    echo "❌ Требуется Node.js 18+. Текущая версия: $(node -v)"
    exit 1
fi

echo "✅ Node.js $(node -v) установлен"
echo ""

# Install dependencies
echo "📦 Установка зависимостей..."
npm install

echo ""
echo "✅ Зависимости установлены!"
echo ""

# Check if backend is running
echo "🔍 Проверка backend..."
if curl -f http://localhost:8000/health &> /dev/null; then
    echo "✅ Backend работает"
else
    echo "⚠️  Backend не отвечает на http://localhost:8000"
    echo "   Запустите backend перед запуском админки:"
    echo "   docker-compose up db redis"
    echo "   uvicorn app.main:app --reload"
fi

echo ""
echo "============================================"
echo "  🚀 Готово к запуску!"
echo "============================================"
echo ""
echo "Для запуска dev сервера:"
echo "  cd admin-frontend"
echo "  npm run dev"
echo ""
echo "Админка будет доступна на: http://localhost:3000"
echo ""
echo "Для production build:"
echo "  npm run build"
echo "  npm run preview"
echo ""
