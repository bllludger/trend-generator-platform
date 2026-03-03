"""
Глобальные константы приложения. ЦА (целевая аудитория) — единый источник правды.
"""

# Целевая аудитория: в каких потоках показывать тематики/тренды
AUDIENCE_WOMEN = "women"
AUDIENCE_MEN = "men"
AUDIENCE_COUPLES = "couples"

AUDIENCE_CHOICES = (AUDIENCE_WOMEN, AUDIENCE_MEN, AUDIENCE_COUPLES)
AUDIENCE_DEFAULT = AUDIENCE_WOMEN


def normalize_target_audiences(value) -> list[str]:
    """Вернуть список ЦА из БД; null/пусто/невалид → ['women']."""
    if value is None:
        return [AUDIENCE_WOMEN]
    if isinstance(value, list):
        out = [str(x).strip().lower() for x in value if x and str(x).strip()]
        return out if out else [AUDIENCE_WOMEN]
    return [AUDIENCE_WOMEN]


def audience_in_target_audiences(audience: str, target_audiences) -> bool:
    """Проверить, входит ли выбранная ЦА в список target_audiences темы/тренда."""
    if not audience:
        return False
    allowed = normalize_target_audiences(target_audiences)
    return audience.strip().lower() in allowed
