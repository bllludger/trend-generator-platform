# Безопасное обновление при большом количестве пользователей

## Вариант 1: Последовательный рестарт (без смены инфраструктуры)

Подходит, если краткий простой API (5–20 сек) и бота (несколько секунд) допустим. Минимизирует риск поломки очереди и «половинчатого» состояния.

**Когда лучше запускать:** в окно с минимальным трафиком (ночь, утро).

### Шаги

```bash
# 0. Собрать образы заранее (чтобы не тянуть билд во время рестарта)
docker compose build

# 1. Воркеры — даём старым доработать текущие задачи, затем поднимаем новые
docker compose up -d --force-recreate worker beat
sleep 25

# 2. API — рестарт, затем ждём, пока новый контейнер станет healthy
docker compose up -d --force-recreate api
echo "Ждём готовности API (до 90 сек)..."
for i in $(seq 1 18); do
  if docker compose exec -T api curl -sf --connect-timeout 3 http://localhost:8000/health >/dev/null 2>&1; then
    echo "API готов."
    break
  fi
  sleep 5
done
sleep 5

# 3. Бот — краткий разрыв в приёме апдейтов
docker compose up -d --force-recreate bot
sleep 10

# 4. Админка (статика)
docker compose up -d --force-recreate admin-ui
echo "Готово."
```

**Одной строкой** (без ожидания готовности API по health):

```bash
docker compose build && \
docker compose up -d --force-recreate worker beat && sleep 25 && \
docker compose up -d --force-recreate api && sleep 20 && \
docker compose up -d --force-recreate bot && sleep 10 && \
docker compose up -d --force-recreate admin-ui
```

---

## Вариант 2: Минимальный простой (rolling) за счёт реплик

При двух репликах API (и при желании бота) Compose при `up -d` поднимает новый контейнер и только потом снимает старый — запросы продолжают идти в старый экземпляр, пока новый не готов.

### Настройка один раз

Создай файл `docker-compose.override.yml` в корне проекта (рядом с `docker-compose.yml`):

```yaml
# docker-compose.override.yml — реплики для безаварийного обновления
services:
  api:
    deploy:
      replicas: 2
    # Порты: при 2 репликах один порт маппится на оба контейнера (round-robin)
  bot:
    deploy:
      replicas: 2
```

**Важно:** один порт `8000:8000` при двух репликах API в обычном Compose без внешнего балансировщика может вести себя по-разному (часто только один контейнер получает трафик). Чтобы оба экземпляра реально использовались, перед ними должен стоять балансировщик (nginx/traefik/caddy), который сам ходит на оба контейнера. Иначе оставь реплику только для **плавного переключения**: при `up -d --force-recreate` Compose по очереди пересоздаёт контейнеры, и простой будет только в момент переключения на последний экземпляр.

**Упрощённый вариант без балансировщика:** оставить 1 реплику API, но увеличить `stop_grace_period`, чтобы текущие запросы успели завершиться:

В `docker-compose.yml` для сервисов `api` и `bot` можно добавить:

```yaml
  api:
    stop_grace_period: 30s
  bot:
    stop_grace_period: 20s
```

Тогда при рестарте процесс получит SIGTERM и 30 (или 20) секунд на корректное завершение соединений.

### Обновление при включённых репликах

```bash
docker compose build
docker compose up -d --force-recreate worker beat
sleep 20
docker compose up -d --force-recreate api   # при 2 репликах — по очереди
sleep 15
docker compose up -d --force-recreate bot
sleep 10
docker compose up -d --force-recreate admin-ui
```

---

## Рекомендация

- **Сейчас:** использовать **вариант 1** с циклом ожидания health API и окном по трафику.
- **Позже:** при росте нагрузки — вынести API (и при необходимости бота) за nginx/traefik с 2 репликами и обновлять через `docker compose up -d` для rolling без простоя.
