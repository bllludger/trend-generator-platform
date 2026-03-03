"""
Тупой слой: на вход job_id + UnlockOptions, на выход — reply_markup (dict для Telegram API).
Без i18n и A/B логики; текст кнопок простой (константы).
"""
from __future__ import annotations

from typing import Any

from app.paywall.models import UnlockOptions


def build_unlock_markup(
    job_id: str,
    options: UnlockOptions,
    *,
    show_hd_credits: bool = False,
) -> dict[str, Any]:
    """
    Собрать inline_keyboard для кнопок разблокировки.
    show_hd_credits добавляет кнопку «За бонус 4K» (реферальные бонусы).
    """
    rows: list[list[dict[str, Any]]] = []
    if show_hd_credits:
        rows.append([
            {
                "text": "🎁 За бонус 4K",
                "callback_data": f"unlock_hd:{job_id}",
            }
        ])
    if options.show_tokens:
        rows.append([
            {
                "text": f"Разблокировать за {options.cost_tokens} токен",
                "callback_data": f"unlock_tokens:{job_id}",
            }
        ])
    # Unlock за Stars убран из UX (только тарифы лестницы). Кнопка не показывается.
    # if options.show_stars:
    #     rows.append([{"text": "Разблокировать за Stars", "callback_data": f"unlock:{job_id}"}])
    return {"inline_keyboard": rows}
