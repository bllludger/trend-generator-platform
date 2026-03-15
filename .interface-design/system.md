# Система интерфейса админки

Зафиксированные решения после аудита interface-design (аналитика по трендам и общие компоненты).

## Глубина (Depth)

- **Стратегия:** только границы, без теней у карточек.
- Карточки: `border border-border`, без `shadow-sm`.
- Выпадающие списки и попапы могут использовать тень для отделения от поверхности (один уровень выше).

## Сетка отступов

- **Базовый шаг:** 4px.
- Все отступы и размеры — кратные 4 (4, 8, 12, 16, 20, 24 …). Не использовать 10px (py-2.5, px-2.5).
- Типичные значения: `p-3` (12px), `p-4` (16px), `p-6` (24px), `gap-2` (8px), `gap-3` (12px), `gap-4` (16px).

## Токены семантики цветов

- **Успех:** `--success` / `text-success`, `bg-success`, `bg-success/10`.
- **Ошибка/деструктивное:** `--destructive` / `text-destructive`, `bg-destructive`, `bg-destructive/10`.
- **Предупреждение:** `--warning` / `text-warning`, `bg-warning`, `bg-warning/10`.
- Не использовать жёсткие цвета (emerald-600, red-600, amber-600) — только токены.

## Границы

- **Основная:** `--border`, класс `border-border`.
- **Мягкая (разделение строк, второстепенные блоки):** `--border-muted`, класс `border-border-muted`.
- Таблица: заголовок и строки с `border-border-muted`.

## Иерархия текста

- **Primary:** `text-foreground` — основной контент.
- **Secondary:** `text-foreground-secondary` — подзаголовки, акценты.
- **Tertiary:** `text-foreground-tertiary` — вспомогательный текст.
- **Muted:** `text-muted-foreground` — метаданные, подписи, disabled.

## Паттерны компонентов

### Карточка аналитики
- Карточка: `rounded-lg border border-border bg-card`, без тени.
- Заголовок карточки: `CardTitle` (text-2xl font-semibold), описание: `CardDescription` (text-sm text-muted-foreground).
- Внутренние отступы: `p-6` у CardHeader/CardContent.

### Строка тренда / списка (топ трендов, топ пользователей)
- Контейнер: `rounded-lg border border-border-muted bg-muted/30 px-3 py-3`, hover: `hover:bg-muted/50`.
- Отступ по вертикали между строками: `space-y-2` или `space-y-3` (8px или 12px).

### Badge
- Отступы: `px-3 py-0.5` (сетка 4px).
