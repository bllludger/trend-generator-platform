#!/usr/bin/env python3
"""
Вывести все диплинки трендов (имя + ссылка «Попробовать этот тренд»).
Запуск из корня проекта: python -m scripts.print_deeplinks
или: PYTHONPATH=. python scripts/print_deeplinks.py
"""
import os
import sys

# корень проекта в PYTHONPATH
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings
from app.db.session import SessionLocal
from app.services.trends.service import TrendService


def main():
    username = (getattr(settings, "telegram_bot_username", None) or "").strip()
    if not username:
        print("TELEGRAM_BOT_USERNAME не задан в .env — диплинки недоступны.")
        return
    db = SessionLocal()
    try:
        service = TrendService(db)
        trends = service.list_all()
        if not trends:
            print("Трендов в БД нет.")
            return
        print(f"Диплинки (бот: @{username}):\n")
        for t in trends:
            link = f"https://t.me/{username}?start=trend_{t.id}"
            print(f"  {t.name}\n    {link}\n")
    finally:
        db.close()


if __name__ == "__main__":
    main()
