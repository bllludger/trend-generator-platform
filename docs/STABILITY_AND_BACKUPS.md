# Максимальная стабильность: чтобы данные и промпты не пропали никогда

Как сделать сервис устойчивым к падениям, перезапускам и сбоям диска. Актуальные подходы и технологии.

---

## 1. Что уже сделано в проекте

| Компонент | Сейчас | Переживёт перезапуск контейнеров? |
|-----------|--------|-----------------------------------|
| **PostgreSQL** | Named volume `postgres_data` | Да (пока не вызываете `docker compose down -v`) |
| **Redis** | Named volume `redis_data` + **AOF** (`appendonly yes`) | Да; AOF дописывает каждую операцию на диск |
| **Промпты (YAML)** | Bind mount `./prompts` на хосте | Да |
| **Примеры трендов, генерации** | Bind mount `./data/trend_examples`, `./data/generated_images` | Да |
| **Бэкап** | Скрипт `scripts/backup.sh` | По расписанию (cron) — см. ниже |

---

## 2. Обязательные правила (без них данные можно потерять)

1. **Никогда не выполнять в продакшене** `docker compose down -v` (или ваш `stop.sh -v`). Флаг `-v` удаляет named volumes: БД и Redis обнулятся.
2. **Регулярные бэкапы** — единственная защита от сбоя диска, случайного удаления тома или ошибки приложения. Настроить cron на запуск `scripts/backup.sh` (и при желании выгрузку в S3).
3. **Каталоги на хосте** `./prompts`, `./data/trend_examples`, `./data/generated_images` должны быть на надёжном диске (не ephemeral). При использовании облака — отдельный volume/диск, который не удаляется при пересоздании инстанса.

---

## 3. Скрипт бэкапа (встроенный)

**Назначение:** один архив с дампом PostgreSQL и копией каталогов `prompts`, `data/trend_examples`, `data/generated_images`.

**Запуск из корня проекта:**
```bash
./scripts/backup.sh
```

**Переменные (можно задать в `.env` или перед запуском):**

| Переменная | По умолчанию | Описание |
|------------|--------------|----------|
| `BACKUP_DIR` | `./backups` | Каталог, куда класть архивы |
| `BACKUP_RETENTION_DAYS` | `14` | Удалять локальные бэкапы старше N дней |
| `BACKUP_S3_URI` | — | Если задан (например `s3://my-bucket/backups`), архив дополнительно загружается в S3 (нужен `aws` CLI) |
| `POSTGRES_USER`, `POSTGRES_DB` | `trends` | Для `pg_dump` (подхватываются из `.env`) |

**Пример cron (каждый день в 3:00):**
```bash
0 3 * * * cd /path/to/ai_slop_2 && ./scripts/backup.sh
```

**Восстановление после потери данных:**

1. Распаковать архив:
   ```bash
   cd /path/to/project
   tar -xzf backups/trend_generator_backup_YYYYMMDD_HHMMSS.tar.gz
   ```
2. Восстановить БД (контейнер `db` должен быть запущен):
   ```bash
   gunzip -c trend_generator_backup_YYYYMMDD_HHMMSS/db.sql.gz | docker compose exec -T db psql -U trends -d trends
   ```
3. Восстановить файлы:
   ```bash
   tar -xzf trend_generator_backup_YYYYMMDD_HHMMSS/data.tar.gz -C .
   ```
4. Удалить временную папку: `rm -rf trend_generator_backup_YYYYMMDD_HHMMSS`

---

## 4. Технологии 2025–2026: как добиться «данные не пропадут никогда»

### Уровень 1: Self-hosted + бэкапы (текущая схема)

- Docker Compose с named volumes и bind mount’ами.
- **Redis AOF** — уже включён в `docker-compose.yml`.
- **Регулярный запуск** `scripts/backup.sh` (cron).
- Опционально: **выгрузка бэкапов в S3/MinIO** (`BACKUP_S3_URI`) — защита от падения одного сервера.

Итог: перезапуски и падения контейнеров переживаются; при сбое диска или случайном `down -v` восстанавливаемся из бэкапа.

### Уровень 2: Управляемые БД и хранилище (облако)

Чтобы не зависеть от одного сервера и томов Docker:

| Компонент | Технология | Что даёт |
|-----------|------------|----------|
| **PostgreSQL** | **Managed DB**: AWS RDS, Google Cloud SQL, Azure Database for PostgreSQL, или Supabase/Neon | Автобэкапы, PITR (point-in-time recovery), реплики, патчи |
| **Redis** | **Managed Redis**: ElastiCache, Memorystore, Redis Cloud | Persistence (AOF/RDB), реплики, отказоустойчивость |
| **Файлы** (prompts, примеры трендов, генерации) | **Object storage**: S3, Google Cloud Storage, MinIO (self-hosted) | Дублирование, версионирование, жизнь по политикам; приложение хранит пути/URL в БД и читает из бакета |

Для «промпты и данные не пропадут никогда» в облаке типичная схема: managed PostgreSQL + managed Redis + S3/GCS для файлов, плюс политики бэкапов и retention в облаке.

### Уровень 3: Оркестрация и отказоустойчивость

- **Kubernetes** (или managed K8s: EKS, GKE, AKS): StatefulSet для БД, PersistentVolumeClaims — тома не привязаны к одному поду; при падении ноды поды и тома можно поднять на другой ноде.
- **Репликация PostgreSQL** (streaming replication): основной + реплика(и); при падении мастера — переключение на реплику (вручную или через Patroni, облачные managed DB делают это сами).
- **Резервный регион/зона**: реплики БД и копии бэкапов в другом регионе — защита от потери дата-центра.

---

## 5. Что включено в репозитории

1. **Redis AOF** в `docker-compose.yml` — данные Redis переживут перезапуск и сбой процесса.
2. **Скрипт `scripts/backup.sh`** — дамп БД + архив `prompts` и `data/`; опционально загрузка в S3.
3. **Правило в архитектуре** — не использовать `down -v` в продакшене; каталоги `./data/trend_examples` и т.п. создавать на хосте до первого деплоя.

Дальнейшие шаги по желанию:

- Вынести бэкапы в cron с выгрузкой в S3/MinIO.
- При росте нагрузки или требовании SLA — перенести PostgreSQL и Redis в managed-сервисы, файлы — в object storage и доработать приложение под чтение/запись из бакета.
