# 🎨 Trend Generator Admin Panel (Modern React)

Современная админ-панель на React + TypeScript + Vite для управления сервисом генерации трендовых изображений.

## 🚀 Технологический стек

- ⚛️ **React 18** + TypeScript
- ⚡ **Vite** - сверхбыстрая сборка
- 🎨 **Tailwind CSS** + **shadcn/ui** - современный UI
- 🔄 **TanStack Query** (React Query v5) - управление состоянием сервера
- 🔒 **JWT Authentication** - безопасная аутентификация
- 📊 **Recharts** - графики и визуализация
- 🌙 **Dark Mode** - темная тема
- 📱 **Responsive Design** - адаптивность

## 📦 Установка

```bash
# Установка зависимостей
npm install

# Или с помощью yarn
yarn install

# Или с помощью pnpm
pnpm install
```

## 🔧 Конфигурация

Создайте файл `.env`:

```env
VITE_API_BASE=http://localhost:8000
```

## 🎯 Запуск

### Development режим

```bash
npm run dev
```

Админка будет доступна на `http://localhost:3000`

### Production build

```bash
npm run build
npm run preview
```

## 🏗️ Структура проекта

```
admin-frontend/
├── src/
│   ├── components/
│   │   ├── ui/              # shadcn/ui компоненты
│   │   └── layout/          # Layout компоненты (Sidebar, Header)
│   ├── pages/               # Страницы приложения
│   │   ├── LoginPage.tsx
│   │   ├── DashboardPage.tsx
│   │   ├── UsersPage.tsx
│   │   ├── JobsPage.tsx
│   │   └── TrendsPage.tsx
│   ├── services/            # API клиенты
│   ├── stores/              # Zustand stores
│   ├── lib/                 # Утилиты
│   ├── hooks/               # Custom hooks
│   ├── types/               # TypeScript типы
│   ├── App.tsx              # Главный компонент с роутингом
│   └── main.tsx             # Entry point
├── public/
├── index.html
├── vite.config.ts
├── tailwind.config.js
├── tsconfig.json
└── package.json
```

## 🎨 Фичи

### ✅ Реализовано

- [x] **JWT Authentication** - безопасный вход с токенами
- [x] **Dashboard** - статистика в реальном времени
- [x] **Users Management** - управление пользователями
- [x] **Jobs Monitoring** - мониторинг задач
- [x] **Trends Management** - управление трендами
- [x] **Dark Mode** - переключение темы
- [x] **Responsive Design** - адаптивность для мобильных
- [x] **Real-time Updates** - автообновление данных каждые 30 сек
- [x] **Pagination** - постраничная навигация
- [x] **Filtering & Search** - фильтрация и поиск

### 🚧 В разработке

- [ ] **Charts & Analytics** - графики с Recharts
- [ ] **Prompts Editor** - редактор промптов
- [ ] **Telemetry** - детальная телеметрия
- [ ] **Audit Logs** - журнал аудита
- [ ] **Settings** - настройки системы
- [ ] **CSV Export** - экспорт данных
- [ ] **WebSocket** - real-time updates через WS

## 🔐 Безопасность

### JWT Authentication

Новая админка использует JWT токены вместо session cookies:

- **Access Token** сохраняется в localStorage
- **Bearer Authentication** для всех API запросов
- **Автоматический logout** при истечении токена
- **Secure by default** - HTTPS в production

### Backend API

Обновленные эндпоинты:

```
POST /admin/auth/login  - Вход (возвращает JWT)
POST /admin/auth/logout - Выход
GET  /admin/auth/me     - Текущий пользователь
```

Все остальные `/admin/*` эндпоинты теперь требуют JWT в заголовке:

```
Authorization: Bearer <token>
```

## 🎨 Дизайн-система

### Цветовая палитра

- **Primary**: Blue (#3B82F6) - основной цвет
- **Secondary**: Gray - второстепенные элементы
- **Success**: Green - успешные действия
- **Warning**: Yellow - предупреждения
- **Error**: Red - ошибки
- **Info**: Blue - информация

### Компоненты

Используем **shadcn/ui** - высококачественные компоненты на базе Radix UI:

- Buttons
- Cards
- Inputs
- Select
- Badges
- Dialogs
- Toasts (sonner)

## 📊 API Integration

### TanStack Query (React Query)

Все запросы к API управляются через React Query:

```typescript
const { data, isLoading } = useQuery({
  queryKey: ['users', page],
  queryFn: () => usersService.list({ page }),
  refetchInterval: 30000, // Auto-refresh
})
```

### API Services

```typescript
// services/api.ts
export const usersService = {
  list: (params) => api.get('/admin/users', { params }),
  get: (id) => api.get(`/admin/users/${id}`),
  update: (id, data) => api.put(`/admin/users/${id}`, data),
}
```

## 🌙 Dark Mode

Переключение темы через кнопку в Header:

- Сохраняется в localStorage
- Плавные переходы между темами
- Все компоненты поддерживают dark mode

## 📱 Responsive Design

- **Desktop** (lg): Полная sidebar навигация
- **Tablet** (md): Коллапсирующая sidebar
- **Mobile** (sm): Hamburger меню

## 🔄 Миграция со старой админки

### Что изменилось

| Старая версия | Новая версия |
|--------------|--------------|
| Jinja2 templates | React SPA |
| Session cookies | JWT tokens |
| Inline CSS | Tailwind CSS |
| jQuery/Vanilla JS | React + TypeScript |
| Manual fetch | TanStack Query |
| alert() | Toast notifications |
| confirm() | Modal dialogs |

### Сравнение

| Метрика | Старая | Новая |
|---------|--------|-------|
| Производительность | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| UX | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| Безопасность | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| Масштабируемость | ⭐⭐ | ⭐⭐⭐⭐⭐ |
| Developer Experience | ⭐⭐ | ⭐⭐⭐⭐⭐ |

## 🚀 Деплой

### Docker

```bash
# Build
docker build -t trend-admin-frontend .

# Run
docker run -p 3000:80 trend-admin-frontend
```

### Production build

```bash
npm run build
# dist/ содержит готовые файлы для деплоя
```

### Nginx конфигурация

```nginx
server {
    listen 80;
    server_name admin.example.com;
    
    root /var/www/admin;
    index index.html;
    
    location / {
        try_files $uri $uri/ /index.html;
    }
    
    location /api {
        proxy_pass http://backend:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

## 🤝 Contributing

1. Fork репозиторий
2. Создайте feature branch (`git checkout -b feature/amazing-feature`)
3. Commit изменения (`git commit -m 'Add amazing feature'`)
4. Push в branch (`git push origin feature/amazing-feature`)
5. Создайте Pull Request

## 📝 License

MIT

## 🙏 Благодарности

- [shadcn/ui](https://ui.shadcn.com/) - за отличные компоненты
- [TanStack Query](https://tanstack.com/query) - за управление состоянием
- [Vite](https://vitejs.dev/) - за скорость
- [Tailwind CSS](https://tailwindcss.com/) - за утилиты
