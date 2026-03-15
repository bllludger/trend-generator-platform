"""Тесты last_active: _as_utc и сравнение max(Job, Take) без падения при naive/aware."""
from datetime import datetime, timedelta, timezone


class TestAsUtc:
    """Нормализация дат в UTC для безопасного max() при смеси naive/aware."""

    def test_none_returns_none(self):
        from app.api.routes.admin import _as_utc
        assert _as_utc(None) is None

    def test_naive_becomes_aware_utc(self):
        from app.api.routes.admin import _as_utc
        naive = datetime(2025, 3, 1, 12, 0, 0)
        result = _as_utc(naive)
        assert result is not None
        assert result.tzinfo is not None
        assert result.tzinfo.utcoffset(None).total_seconds() == 0
        assert result.year == 2025 and result.month == 3 and result.day == 1
        assert result.hour == 12 and result.minute == 0

    def test_aware_unchanged_moment(self):
        from app.api.routes.admin import _as_utc
        utc_dt = datetime(2025, 3, 1, 12, 0, 0, tzinfo=timezone.utc)
        result = _as_utc(utc_dt)
        assert result == utc_dt
        # non-UTC aware
        msk = timezone(timedelta(hours=3))
        msk_dt = datetime(2025, 3, 1, 15, 0, 0, tzinfo=msk)
        result2 = _as_utc(msk_dt)
        assert result2.tzinfo == timezone.utc
        assert result2.hour == 12 and result2.minute == 0  # same instant as UTC noon


class TestLastActiveMaxNaiveAware:
    """last_active = max(job_last, take_last) не падает при naive Job и aware Take."""

    def test_max_naive_and_aware_no_error(self):
        from app.api.routes.admin import _as_utc
        job_last = datetime(2025, 3, 1, 10, 0, 0)  # naive
        take_last = datetime(2025, 3, 1, 14, 0, 0, tzinfo=timezone.utc)  # aware
        last = max(_as_utc(job_last), _as_utc(take_last))
        assert last.isoformat().endswith("14:00:00+00:00") or "14:00:00" in last.isoformat()

    def test_max_both_naive_no_error(self):
        from app.api.routes.admin import _as_utc
        job_last = datetime(2025, 3, 1, 10, 0, 0)
        take_last = datetime(2025, 3, 1, 12, 0, 0)
        last = max(_as_utc(job_last), _as_utc(take_last))
        assert last.hour == 12

    def test_max_both_aware_no_error(self):
        from app.api.routes.admin import _as_utc
        job_last = datetime(2025, 3, 1, 14, 0, 0, tzinfo=timezone.utc)
        take_last = datetime(2025, 3, 1, 10, 0, 0, tzinfo=timezone.utc)
        last = max(_as_utc(job_last), _as_utc(take_last))
        assert last.hour == 14
