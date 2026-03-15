#!/bin/bash
# Перезапуск только admin-ui, api и bot без остановки остальных сервисов (postgres, redis, celery и т.д.)
set -e
cd "$(dirname "${BASH_SOURCE[0]}")"
docker compose up -d --build admin-ui api bot
