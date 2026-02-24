"""Форматирование цен в Stars с примерным эквивалентом в рублях."""


def format_stars_rub(stars: int | float, rate: float) -> str:
    """Вернуть строку вида «25⭐ (~33 ₽)» по курсу rate (руб за 1 Star)."""
    rub = round(float(stars) * rate, 0)
    return f"{int(stars)}⭐ (~{int(rub)} ₽)"
