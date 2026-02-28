"""
Admin API: security, settings, users, telegram messages, telemetry, bank transfer,
payments, packs, trends, audit, broadcast, jobs, copy style, cleanup.
Paths match admin-frontend/src/services/api.ts. Order: /users/analytics and /users before /users/{id}.
"""
from datetime import datetime, timedelta, timezone
from typing import Any

import os

from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.audit_log import AuditLog
from app.models.bank_transfer_receipt_log import BankTransferReceiptLog
from app.models.job import Job
from app.models.pack import Pack
from app.models.payment import Payment
from app.models.theme import Theme
from app.models.trend import Trend
from app.models.user import User
from app.services.auth.jwt import get_current_user
from app.services.app_settings.settings_service import AppSettingsService
from app.services.audit.service import AuditService
from app.services.bank_transfer.settings_service import BankTransferSettingsService
from app.services.cleanup.service import CleanupService
from app.services.copy_style.settings_service import CopyStyleSettingsService
from app.services.jobs.service import JobService
from app.services.payments.service import PaymentService
from app.services.security.settings_service import SecuritySettingsService
from app.services.telegram_messages.service import TelegramMessageTemplateService
from app.services.transfer_policy.service import get_all as transfer_get_all, get_effective as transfer_get_effective, update_both as transfer_update_both
from app.services.themes.service import ThemeService
from app.services.trends.service import TrendService
from app.services.generation_prompt.settings_service import GenerationPromptSettingsService
from app.core.config import settings as app_settings
from app.api.routes.playground import trend_to_playground_config
from app.workers.tasks.broadcast import broadcast_message
from app.models.referral_bonus import ReferralBonus
from app.referral.service import ReferralService

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(get_current_user)])


# ---------- Security ----------
@router.get("/security/settings")
def security_get_settings(db: Session = Depends(get_db)):
    svc = SecuritySettingsService(db)
    return svc.as_dict()


@router.put("/security/settings")
def security_update_settings(payload: dict, db: Session = Depends(get_db)):
    svc = SecuritySettingsService(db)
    return svc.update(payload)


@router.get("/security/overview")
def security_overview(db: Session = Depends(get_db)):
    total = db.query(User).count()
    banned = db.query(User).filter(User.is_banned.is_(True)).count()
    suspended = db.query(User).filter(User.is_suspended.is_(True)).count()
    rate_limited = db.query(User).filter(User.rate_limit_per_hour.isnot(None)).count()
    moderators = db.query(User).filter(User.is_moderator.is_(True)).count()
    return {
        "banned_count": banned,
        "suspended_count": suspended,
        "rate_limited_count": rate_limited,
        "moderators_count": moderators,
        "total_users": total,
    }


@router.get("/security/users")
def security_users(
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    filter_status: str | None = None,
    telegram_id: str | None = None,
):
    q = db.query(User)
    if telegram_id:
        q = q.filter(User.telegram_id == telegram_id)
    if filter_status == "banned":
        q = q.filter(User.is_banned.is_(True))
    elif filter_status == "suspended":
        q = q.filter(User.is_suspended.is_(True))
    elif filter_status == "rate_limited":
        q = q.filter(User.rate_limit_per_hour.isnot(None))
    elif filter_status == "active":
        q = q.filter(User.is_banned.is_(False), User.is_suspended.is_(False))
    total = q.count()
    q = q.order_by(User.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    users = q.all()
    user_ids = [u.id for u in users]
    jobs_count_map = {}
    if user_ids:
        job_counts = (
            db.query(Job.user_id, func.count(Job.job_id).label("cnt"))
            .filter(Job.user_id.in_(user_ids))
            .group_by(Job.user_id)
        )
        jobs_count_map = {row.user_id: row.cnt for row in job_counts}
    items = []
    for u in users:
        items.append({
            "id": u.id,
            "telegram_id": u.telegram_id,
            "telegram_username": u.telegram_username,
            "telegram_first_name": u.telegram_first_name,
            "telegram_last_name": u.telegram_last_name,
            "token_balance": u.token_balance,
            "subscription_active": u.subscription_active,
            "is_banned": u.is_banned,
            "ban_reason": u.ban_reason,
            "is_suspended": u.is_suspended,
            "suspended_until": u.suspended_until.isoformat() if u.suspended_until else None,
            "rate_limit_per_hour": u.rate_limit_per_hour,
            "is_moderator": u.is_moderator,
            "created_at": u.created_at.isoformat() if u.created_at else None,
            "jobs_count": jobs_count_map.get(u.id, 0),
        })
    return {"items": items, "total": total, "page": page, "pages": (total + page_size - 1) // page_size}


@router.post("/security/users/{user_id}/ban")
def security_ban_user(user_id: str, payload: dict | None = None, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    user.is_banned = True
    user.ban_reason = (payload or {}).get("reason") if payload else None
    user.banned_at = datetime.now(timezone.utc)
    db.add(user)
    db.commit()
    return {"ok": True}


@router.post("/security/users/{user_id}/unban")
def security_unban_user(user_id: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    user.is_banned = False
    user.ban_reason = None
    user.banned_at = None
    user.banned_by = None
    db.add(user)
    db.commit()
    return {"ok": True}


@router.post("/security/users/{user_id}/suspend")
def security_suspend_user(user_id: str, payload: dict, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    hours = int(payload.get("hours", 24))
    user.is_suspended = True
    user.suspended_until = datetime.now(timezone.utc) + timedelta(hours=hours)
    user.suspend_reason = payload.get("reason")
    db.add(user)
    db.commit()
    return {"ok": True}


@router.post("/security/users/{user_id}/resume")
def security_resume_user(user_id: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    user.is_suspended = False
    user.suspended_until = None
    user.suspend_reason = None
    db.add(user)
    db.commit()
    return {"ok": True}


@router.post("/security/users/{user_id}/rate-limit")
def security_set_rate_limit(user_id: str, payload: dict, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    limit = payload.get("limit")
    user.rate_limit_per_hour = int(limit) if limit is not None and limit != "" else None
    db.add(user)
    db.commit()
    return {"ok": True}


@router.post("/security/users/{user_id}/moderator")
def security_set_moderator(user_id: str, payload: dict, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    user.is_moderator = bool(payload.get("is_moderator", False))
    db.add(user)
    db.commit()
    return {"ok": True}


@router.post("/security/reset-limits")
def security_reset_limits(db: Session = Depends(get_db)):
    from app.services.users.service import UserService
    count = UserService(db).reset_all_limits()
    return {"users_updated": count}


# ---------- Transfer policy (оба набора: global, trends) ----------
@router.get("/settings/transfer-policy")
def transfer_policy_get(db: Session = Depends(get_db)):
    return transfer_get_all(db)


@router.put("/settings/transfer-policy")
def transfer_policy_put(payload: dict, db: Session = Depends(get_db)):
    return transfer_update_both(db, payload)


# ---------- Master prompt (Generation Prompt Settings: INPUT, TASK, IDENTITY, SAFETY + defaults) ----------
@router.get("/settings/master-prompt")
def master_prompt_get(db: Session = Depends(get_db)):
    from app.services.generation_prompt.settings_service import GenerationPromptSettingsService
    svc = GenerationPromptSettingsService(db)
    return svc.as_dict()


@router.put("/settings/master-prompt")
def master_prompt_put(payload: dict, db: Session = Depends(get_db)):
    from app.services.generation_prompt.settings_service import GenerationPromptSettingsService
    svc = GenerationPromptSettingsService(db)
    return svc.update(payload)


# ---------- Env / App settings ----------
@router.get("/settings/env")
def settings_env():
    import os
    items = []
    for key in sorted(os.environ.keys()):
        if any(key.startswith(p) for p in ("DATABASE", "REDIS", "TELEGRAM", "OPENAI", "GEMINI", "ADMIN", "CORS", "APP_ENV")):
            items.append({"key": key, "value": "***" if "KEY" in key or "TOKEN" in key or "SECRET" in key or "PASSWORD" in key else os.environ[key], "category": "app"})
    return {"items": items, "source": "environment"}


@router.get("/settings/app")
def settings_app_get(db: Session = Depends(get_db)):
    svc = AppSettingsService(db)
    return svc.as_dict()


@router.put("/settings/app")
def settings_app_put(payload: dict, db: Session = Depends(get_db)):
    svc = AppSettingsService(db)
    return svc.update(payload)


# ---------- Users (order: analytics and list before /users/{id}) ----------
def _users_analytics_since(db: Session, since: datetime) -> tuple[int, int, list[dict], list[dict]]:
    """Returns (users_with_jobs_count, total_jobs, growth_list, top_users_list)."""
    now = datetime.now(timezone.utc)
    # New users per day: last 14 days from today
    growth_since = now - timedelta(days=14)
    growth_q = (
        db.query(func.date(User.created_at).label("day"), func.count(User.id).label("cnt"))
        .filter(User.created_at >= growth_since)
        .group_by(func.date(User.created_at))
    )
    growth_map = {str(row.day): row.cnt for row in growth_q}
    growth_list = []
    for i in range(14):
        d = (now - timedelta(days=13 - i)).date()
        growth_list.append({"date": str(d), "new_users": growth_map.get(str(d), 0)})
    # Jobs in window: total and per user
    jobs_in_window = (
        db.query(Job.user_id, func.count(Job.job_id).label("jobs_count"), func.sum(case((Job.status == "SUCCEEDED", 1), else_=0)).label("succeeded"))
        .filter(Job.created_at >= since)
        .group_by(Job.user_id)
    )
    total_jobs = 0
    top_list = []
    for row in jobs_in_window:
        total_jobs += row.jobs_count or 0
        top_list.append({"user_id": row.user_id, "jobs_count": int(row.jobs_count or 0), "succeeded": int(row.succeeded or 0)})
    top_list.sort(key=lambda x: x["jobs_count"], reverse=True)
    users_with_jobs = len(top_list)
    # Enrich top with telegram_id from User
    user_ids = [t["user_id"] for t in top_list[:20]]
    users_map = {u.id: u.telegram_id for u in db.query(User).filter(User.id.in_(user_ids)).all()} if user_ids else {}
    for t in top_list[:10]:
        t["telegram_id"] = users_map.get(t["user_id"], t["user_id"])
    top_users = [{"telegram_id": t["telegram_id"], "jobs_count": t["jobs_count"], "succeeded": t["succeeded"]} for t in top_list[:10]]
    return users_with_jobs, total_jobs, growth_list, top_users


@router.get("/users/analytics")
def users_analytics(db: Session = Depends(get_db), time_window: str | None = Query(None)):
    total_users = db.query(User).count()
    active_subscribers = db.query(User).filter(User.subscription_active.is_(True)).count()
    conversion_rate = round(100.0 * active_subscribers / total_users, 1) if total_users else 0
    window_days = 30
    try:
        if time_window:
            window_days = int(time_window)
    except (TypeError, ValueError):
        pass
    since = datetime.now(timezone.utc) - timedelta(days=window_days)
    users_with_jobs, total_jobs, growth_list, top_users = _users_analytics_since(db, since)
    avg_jobs_per_user = round(total_jobs / users_with_jobs, 1) if users_with_jobs else 0
    # Cohorts: new users by month (last 12 months)
    cohort_since = datetime.now(timezone.utc) - timedelta(days=365)
    cohort_rows = (
        db.query(func.date_trunc("month", User.created_at).label("month"), func.count(User.id).label("count"))
        .filter(User.created_at >= cohort_since)
        .group_by(func.date_trunc("month", User.created_at))
        .order_by(func.date_trunc("month", User.created_at))
    )
    cohorts = [{"month": (row.month.strftime("%Y-%m") if hasattr(row.month, "strftime") else str(row.month)[:7]), "count": row.count} for row in cohort_rows]
    # Activity segments: users with 0, 1-5, 6-20, 21+ jobs in window
    job_counts_subq = (
        db.query(Job.user_id, func.count(Job.job_id).label("cnt"))
        .filter(Job.created_at >= since)
        .group_by(Job.user_id)
        .subquery()
    )
    bucket_case = case(
        (func.coalesce(job_counts_subq.c.cnt, 0) == 0, "0"),
        (func.coalesce(job_counts_subq.c.cnt, 0) <= 5, "1_5"),
        (func.coalesce(job_counts_subq.c.cnt, 0) <= 20, "6_20"),
        else_="21",
    )
    seg_q = (
        db.query(bucket_case.label("bucket"), func.count(User.id).label("users"))
        .outerjoin(job_counts_subq, User.id == job_counts_subq.c.user_id)
        .group_by(bucket_case)
    )
    seg_map = {row.bucket: row.users for row in seg_q}
    activity_segments = [
        {"segment": "Без задач", "users": seg_map.get("0", 0)},
        {"segment": "1–5 задач", "users": seg_map.get("1_5", 0)},
        {"segment": "6–20 задач", "users": seg_map.get("6_20", 0)},
        {"segment": "21+ задач", "users": seg_map.get("21", 0)},
    ]
    # Token distribution: 0, 1-100, 101-500, 501-1000, 1001+
    tok_0 = db.query(User).filter(User.token_balance == 0).count()
    tok_1_100 = db.query(User).filter(User.token_balance >= 1, User.token_balance <= 100).count()
    tok_101_500 = db.query(User).filter(User.token_balance >= 101, User.token_balance <= 500).count()
    tok_501_1000 = db.query(User).filter(User.token_balance >= 501, User.token_balance <= 1000).count()
    tok_1001 = db.query(User).filter(User.token_balance >= 1001).count()
    token_distribution = [
        {"range": "0", "count": tok_0},
        {"range": "1–100", "count": tok_1_100},
        {"range": "101–500", "count": tok_101_500},
        {"range": "501–1000", "count": tok_501_1000},
        {"range": "1001+", "count": tok_1001},
    ]
    return {
        "time_window": str(window_days),
        "overview": {
            "total_users": total_users,
            "active_subscribers": active_subscribers,
            "conversion_rate": conversion_rate,
            "users_with_jobs": users_with_jobs,
            "avg_jobs_per_user": avg_jobs_per_user,
        },
        "growth": growth_list,
        "top_users": top_users,
        "cohorts": cohorts,
        "activity_segments": activity_segments,
        "token_distribution": token_distribution,
    }


@router.get("/users")
def users_list(
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    search: str | None = None,
    telegram_id: str | None = None,
    subscription_active: bool | None = None,
):
    q = db.query(User)
    search_val = search or telegram_id
    if search_val:
        s = f"%{search_val}%"
        q = q.filter(
            User.telegram_id.ilike(s) |
            User.telegram_username.ilike(s) |
            User.telegram_first_name.ilike(s) |
            User.telegram_last_name.ilike(s)
        )
    if subscription_active is not None:
        q = q.filter(User.subscription_active.is_(subscription_active))
    total = q.count()
    q = q.order_by(User.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    users = q.all()
    user_ids = [u.id for u in users]
    # Job stats per user: jobs_count, succeeded, failed, last_active (max updated_at)
    job_stats = {}
    if user_ids:
        job_agg = (
            db.query(
                Job.user_id,
                func.count(Job.job_id).label("jobs_count"),
                func.sum(case((Job.status == "SUCCEEDED", 1), else_=0)).label("succeeded"),
                func.sum(case((Job.status.in_(["FAILED", "ERROR"]), 1), else_=0)).label("failed"),
                func.max(Job.updated_at).label("last_active"),
            )
            .filter(Job.user_id.in_(user_ids))
            .group_by(Job.user_id)
        )
        for row in job_agg:
            job_stats[row.user_id] = {
                "jobs_count": row.jobs_count or 0,
                "succeeded": int(row.succeeded or 0),
                "failed": int(row.failed or 0),
                "last_active": row.last_active.isoformat() if row.last_active else None,
            }
    items = []
    for u in users:
        stats = job_stats.get(u.id, {"jobs_count": 0, "succeeded": 0, "failed": 0, "last_active": None})
        items.append({
            "id": u.id,
            "telegram_id": u.telegram_id,
            "telegram_username": u.telegram_username,
            "telegram_first_name": u.telegram_first_name,
            "telegram_last_name": u.telegram_last_name,
            "token_balance": u.token_balance,
            "subscription_active": u.subscription_active,
            "free_generations_used": u.free_generations_used,
            "copy_generations_used": u.copy_generations_used,
            "created_at": u.created_at.isoformat() if u.created_at else None,
            "jobs_count": stats["jobs_count"],
            "succeeded": stats["succeeded"],
            "failed": stats["failed"],
            "last_active": stats["last_active"],
        })
    return {"items": items, "total": total, "page": page, "pages": (total + page_size - 1) // page_size}


# ---------- Telegram messages ----------
@router.get("/telegram-messages")
def telegram_messages_list(db: Session = Depends(get_db)):
    svc = TelegramMessageTemplateService(db)
    return {"items": svc.list_templates()}


class TelegramBulkItem(BaseModel):
    key: str
    value: str


@router.post("/telegram-messages/bulk")
def telegram_messages_bulk(payload: dict, db: Session = Depends(get_db)):
    items = payload.get("items", [])
    svc = TelegramMessageTemplateService(db)
    result = svc.bulk_upsert(items, updated_by="admin")
    return {"updated": result["updated"]}


@router.post("/telegram-messages/reset")
def telegram_messages_reset(db: Session = Depends(get_db)):
    svc = TelegramMessageTemplateService(db)
    result = svc.reset_defaults(updated_by="admin")
    return {"reset": result.get("reset", 0)}


# ---------- Telemetry (dashboard from Job / User / Trend) ----------
def _telemetry_since(db: Session, since: datetime) -> tuple[int, dict[str, int]]:
    """Jobs in window: total and by_status."""
    q = db.query(Job.status, func.count(Job.job_id)).filter(Job.created_at >= since).group_by(Job.status)
    by_status = {row[0]: row[1] for row in q}
    total = sum(by_status.values())
    return total, by_status


@router.get("/telemetry")
def telemetry_dashboard(db: Session = Depends(get_db), window_hours: int = Query(24, ge=1)):
    since = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    users_total = db.query(func.count(User.id)).scalar() or 0
    users_subscribed = db.query(func.count(User.id)).filter(User.subscription_active.is_(True)).scalar() or 0
    jobs_total = db.query(func.count(Job.job_id)).scalar() or 0
    jobs_window, jobs_by_status = _telemetry_since(db, since)
    succeeded = (db.query(func.count(Job.job_id)).filter(Job.status == "SUCCEEDED").scalar() or 0)
    queue_length = (db.query(func.count(Job.job_id)).filter(Job.status.in_(["CREATED", "RUNNING"])).scalar() or 0)
    # Топ трендов за окно: trend_id, name, emoji, jobs_window, succeeded_window, failed_window
    trend_stats = (
        db.query(
            Trend.id,
            Trend.name,
            Trend.emoji,
            func.count(Job.job_id).label("jobs_window"),
            func.sum(case((Job.status == "SUCCEEDED", 1), else_=0)).label("succeeded_window"),
            func.sum(case((Job.status.in_(["FAILED", "ERROR"]), 1), else_=0)).label("failed_window"),
        )
        .outerjoin(Job, (Job.trend_id == Trend.id) & (Job.created_at >= since))
        .group_by(Trend.id, Trend.name, Trend.emoji)
        .order_by(func.count(Job.job_id).desc())
        .limit(20)
        .all()
    )
    trend_analytics_window = [
        {
            "trend_id": r.id,
            "name": r.name,
            "emoji": r.emoji or "",
            "jobs_window": r.jobs_window or 0,
            "succeeded_window": r.succeeded_window or 0,
            "failed_window": r.failed_window or 0,
        }
        for r in trend_stats
    ]
    # Ошибки по коду за окно
    failed_by_code_q = (
        db.query(func.coalesce(Job.error_code, "unknown").label("code"), func.count(Job.job_id).label("cnt"))
        .filter(Job.status == "FAILED", Job.created_at >= since)
        .group_by(func.coalesce(Job.error_code, "unknown"))
    )
    jobs_failed_by_error = {row[0]: row[1] for row in failed_by_code_q}
    return {
        "window_hours": window_hours,
        "users_total": users_total,
        "users_subscribed": users_subscribed,
        "jobs_total": jobs_total,
        "jobs_window": jobs_window,
        "queue_length": queue_length,
        "succeeded": succeeded,
        "jobs_by_status": jobs_by_status,
        "jobs_failed_by_error": jobs_failed_by_error,
        "trend_analytics_window": trend_analytics_window,
    }


@router.get("/telemetry/trends")
def telemetry_trends(db: Session = Depends(get_db), window_hours: int = Query(24, ge=1)):
    since = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    trend_stats = (
        db.query(
            Trend.id,
            Trend.name,
            Trend.emoji,
            func.count(Job.job_id).label("jobs_window"),
            func.sum(case((Job.status == "SUCCEEDED", 1), else_=0)).label("succeeded_window"),
            func.sum(case((Job.status.in_(["FAILED", "ERROR"]), 1), else_=0)).label("failed_window"),
        )
        .outerjoin(Job, (Job.trend_id == Trend.id) & (Job.created_at >= since))
        .group_by(Trend.id, Trend.name, Trend.emoji)
        .order_by(func.count(Job.job_id).desc())
        .all()
    )
    trends = [
        {
            "trend_id": r.id,
            "name": r.name,
            "emoji": r.emoji or "",
            "jobs_window": r.jobs_window or 0,
            "succeeded_window": r.succeeded_window or 0,
            "failed_window": r.failed_window or 0,
        }
        for r in trend_stats
    ]
    return {"window_hours": window_hours, "trend_analytics_window": trends}


@router.get("/telemetry/history")
def telemetry_history(db: Session = Depends(get_db), window_days: int = Query(7, ge=1)):
    since = datetime.now(timezone.utc) - timedelta(days=window_days)
    # По дням: date, jobs_total, jobs_succeeded, jobs_failed, active_users
    day = func.date(Job.created_at)
    q = (
        db.query(
            day.label("date"),
            func.count(Job.job_id).label("jobs_total"),
            func.sum(case((Job.status == "SUCCEEDED", 1), else_=0)).label("jobs_succeeded"),
            func.sum(case((Job.status == "FAILED", 1), else_=0)).label("jobs_failed"),
            func.count(func.distinct(Job.user_id)).label("active_users"),
        )
        .filter(Job.created_at >= since)
        .group_by(day)
        .order_by(day)
    )
    history = [
        {
            "date": str(r.date),
            "jobs_total": r.jobs_total or 0,
            "jobs_succeeded": r.jobs_succeeded or 0,
            "jobs_failed": r.jobs_failed or 0,
            "active_users": r.active_users or 0,
        }
        for r in q.all()
    ]
    return {"window_days": window_days, "history": history}


@router.get("/telemetry/product-metrics")
def telemetry_product_metrics(db: Session = Depends(get_db), window_days: int = Query(7, ge=1)):
    now = datetime.now(timezone.utc)
    since_1d = now - timedelta(days=1)
    since_7d = now - timedelta(days=7)
    since_30d = now - timedelta(days=30)

    dau = (
        db.query(func.count(func.distinct(Job.user_id)))
        .filter(Job.created_at >= since_1d)
        .scalar()
        or 0
    )
    wau = (
        db.query(func.count(func.distinct(Job.user_id)))
        .filter(Job.created_at >= since_7d)
        .scalar()
        or 0
    )
    mau = (
        db.query(func.count(func.distinct(Job.user_id)))
        .filter(Job.created_at >= since_30d)
        .scalar()
        or 0
    )
    stickiness_pct = round((dau / mau * 100) if mau else 0)

    funnel_actions = [
        "collection_start", "take_previews_ready", "pay_success",
        "collection_complete", "hd_delivered",
    ]
    since_window = now - timedelta(days=window_days)
    funnel_rows = (
        db.query(AuditLog.action, func.count(AuditLog.id))
        .filter(AuditLog.action.in_(funnel_actions), AuditLog.created_at >= since_window)
        .group_by(AuditLog.action)
        .all()
    )
    funnel_counts = {action: 0 for action in funnel_actions}
    for action, cnt in funnel_rows:
        funnel_counts[action] = cnt

    # AOV и доля Trial: по pay_success из audit (payload: pack_id, stars)
    pay_success_rows = (
        db.query(AuditLog.payload)
        .filter(AuditLog.action == "pay_success", AuditLog.created_at >= since_window)
        .all()
    )
    pay_success_list = [r[0] for r in pay_success_rows if isinstance(r[0], dict)]
    total_pay_success = len(pay_success_list)
    trial_purchases = sum(1 for p in pay_success_list if p.get("pack_id") == "trial")
    share_trial_purchases = round((trial_purchases / total_pay_success * 100), 1) if total_pay_success else 0.0
    stars_sum = sum(int(p.get("stars", 0)) for p in pay_success_list)
    avg_stars_per_pay_success = round(stars_sum / total_pay_success, 1) if total_pay_success else 0.0

    metrics = {
        "dau": dau,
        "wau": wau,
        "mau": mau,
        "stickiness_pct": stickiness_pct,
        "funnel_counts": funnel_counts,
        "share_trial_purchases": share_trial_purchases,
        "avg_stars_per_pay_success": avg_stars_per_pay_success,
        "trial_purchases_count": trial_purchases,
        "total_pay_success_count": total_pay_success,
    }
    return {"window_days": window_days, "metrics": metrics}


# ---------- Bank transfer ----------
@router.get("/bank-transfer/settings")
def bank_transfer_settings_get(db: Session = Depends(get_db)):
    svc = BankTransferSettingsService(db)
    out = svc.as_dict(mask_card=True)
    payment_svc = PaymentService(db)
    ladder = payment_svc.list_product_ladder_packs()
    out["packs_for_buttons"] = [{"id": p.id, "name": p.name, "emoji": p.emoji, "stars_price": p.stars_price} for p in ladder]
    return out


@router.put("/bank-transfer/settings")
def bank_transfer_settings_put(payload: dict, db: Session = Depends(get_db)):
    svc = BankTransferSettingsService(db)
    return svc.update(payload)


@router.get("/bank-transfer/receipt-logs")
def bank_transfer_receipt_logs(
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    match_success: bool | None = None,
    telegram_user_id: str | None = None,
):
    q = db.query(BankTransferReceiptLog)
    if match_success is not None:
        q = q.filter(BankTransferReceiptLog.match_success == match_success)
    if telegram_user_id:
        q = q.filter(BankTransferReceiptLog.telegram_user_id == telegram_user_id)
    total = q.count()
    q = q.order_by(BankTransferReceiptLog.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    rows = q.all()
    items = []
    for r in rows:
        items.append({
            "id": r.id,
            "telegram_user_id": r.telegram_user_id,
            "match_success": r.match_success,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "raw_vision_response": (r.raw_vision_response or "")[:500],
            "extracted_amount_rub": float(r.extracted_amount_rub) if r.extracted_amount_rub is not None else None,
            "expected_rub": float(r.expected_rub) if r.expected_rub is not None else None,
            "rejection_reason": r.rejection_reason,
            "pack_id": r.pack_id,
            "payment_id": r.payment_id,
            "error_message": r.error_message,
        })
    return {"items": items, "total": total, "page": page, "pages": (total + page_size - 1) // page_size}


@router.get("/bank-transfer/receipt-logs/{log_id}/file")
def bank_transfer_receipt_log_file(log_id: str, db: Session = Depends(get_db)):
    row = db.query(BankTransferReceiptLog).filter(BankTransferReceiptLog.id == log_id).first()
    if not row or not row.file_path:
        raise HTTPException(404, "Log or file not found")
    import os
    if not os.path.isfile(row.file_path):
        raise HTTPException(404, "File not found")
    return FileResponse(row.file_path, filename=os.path.basename(row.file_path))


# ---------- Payments ----------
@router.get("/payments")
def payments_list(
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    payment_method: str | None = None,
):
    q = db.query(Payment)
    if payment_method:
        if payment_method == "stars":
            q = q.filter(Payment.telegram_payment_charge_id.isnot(None))
        elif payment_method == "bank_transfer":
            q = q.filter(Payment.payload.like("bank_transfer:%"))
    total = q.count()
    q = q.order_by(Payment.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    payments = q.all()
    user_ids = [p.user_id for p in payments]
    users = {u.id: u for u in db.query(User).filter(User.id.in_(user_ids)).all()} if user_ids else {}
    items = []
    for p in payments:
        u = users.get(p.user_id)
        items.append({
            "id": p.id,
            "user_id": p.user_id,
            "telegram_id": u.telegram_id if u else None,
            "username": u.telegram_username if u else None,
            "pack_id": p.pack_id,
            "stars_amount": p.stars_amount,
            "tokens_granted": p.tokens_granted,
            "status": p.status,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        })
    return {"items": items, "total": total, "page": page, "pages": (total + page_size - 1) // page_size}


# Примерные курсы для отображения (1 Star ≈ $0.013, ≈ 1.3 ₽)
STAR_USD_RATE = 0.013
STAR_RUB_RATE = 1.3


@router.get("/payments/stats")
def payments_stats(db: Session = Depends(get_db), days: int = Query(30, ge=1)):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    base = db.query(Payment).filter(Payment.status == "completed", Payment.created_at >= since)
    total_payments = base.count()
    total_stars = db.query(func.coalesce(func.sum(Payment.stars_amount), 0)).filter(
        Payment.status == "completed", Payment.created_at >= since
    ).scalar() or 0
    refunded = db.query(func.count(Payment.id)).filter(
        Payment.status == "refunded", Payment.created_at >= since
    ).scalar() or 0
    unique_buyers = db.query(func.count(func.distinct(Payment.user_id))).filter(
        Payment.status == "completed", Payment.created_at >= since
    ).scalar() or 0
    revenue_usd = float(total_stars) * STAR_USD_RATE
    revenue_rub = float(total_stars) * STAR_RUB_RATE
    by_pack_rows = (
        db.query(Payment.pack_id, func.count(Payment.id).label("cnt"), func.coalesce(func.sum(Payment.stars_amount), 0).label("stars"))
        .filter(Payment.status == "completed", Payment.created_at >= since)
        .group_by(Payment.pack_id)
    )
    by_pack = [{"pack_id": r.pack_id, "count": r.cnt, "stars": int(r.stars)} for r in by_pack_rows]
    return {
        "days": days,
        "total_stars": int(total_stars),
        "total_payments": total_payments,
        "refunds": refunded,
        "unique_buyers": unique_buyers,
        "revenue_usd_approx": round(revenue_usd, 2),
        "revenue_rub_approx": round(revenue_rub, 0),
        "star_to_rub": STAR_RUB_RATE,
        "by_pack": by_pack,
        "conversion_rate_pct": 0,
    }


@router.post("/payments/{payment_id}/refund")
def payments_refund(payment_id: str, db: Session = Depends(get_db)):
    svc = PaymentService(db)
    ok, msg, _ = svc.process_refund(payment_id)
    if not ok:
        raise HTTPException(400, msg)
    return {"ok": True}


# ---------- Packs ----------
@router.get("/packs")
def packs_list(db: Session = Depends(get_db)):
    packs = db.query(Pack).order_by(Pack.order_index).all()
    return [
        {
            "id": p.id,
            "name": p.name,
            "emoji": p.emoji,
            "tokens": p.tokens,
            "stars_price": p.stars_price,
            "enabled": p.enabled,
            "order_index": getattr(p, "order_index", 0),
            "takes_limit": p.takes_limit,
            "hd_amount": p.hd_amount,
            "is_trial": p.is_trial,
            "pack_type": p.pack_type,
            "upgrade_target_pack_ids": p.upgrade_target_pack_ids,
            "pack_subtype": getattr(p, "pack_subtype", "standalone"),
            "playlist": getattr(p, "playlist", None),
            "favorites_cap": getattr(p, "favorites_cap", None),
            "collection_label": getattr(p, "collection_label", None),
            "upsell_pack_ids": getattr(p, "upsell_pack_ids", None),
            "hd_sla_minutes": getattr(p, "hd_sla_minutes", 10),
        }
        for p in packs
    ]


@router.put("/packs/{pack_id}")
def packs_update(pack_id: str, payload: dict, db: Session = Depends(get_db)):
    pack = db.query(Pack).filter(Pack.id == pack_id).first()
    if not pack:
        raise HTTPException(404, "Pack not found")
    allowed_keys = (
        "name", "emoji", "tokens", "stars_price", "enabled", "order_index",
        "description", "takes_limit", "hd_amount", "is_trial", "pack_type",
        "upgrade_target_pack_ids",
        "pack_subtype", "playlist", "favorites_cap", "collection_label",
        "upsell_pack_ids", "hd_sla_minutes",
    )
    for key in allowed_keys:
        if key in payload:
            setattr(pack, key, payload[key])

    effective_subtype = getattr(pack, "pack_subtype", "standalone")
    if effective_subtype == "collection" and pack.enabled:
        pl = getattr(pack, "playlist", None)
        if not pl or not isinstance(pl, list) or len(pl) == 0:
            raise HTTPException(400, "Collection pack must have a non-empty playlist before enabling")

    db.add(pack)
    db.commit()
    db.refresh(pack)
    return {
        "id": pack.id, "name": pack.name, "emoji": pack.emoji,
        "tokens": pack.tokens, "stars_price": pack.stars_price,
        "enabled": pack.enabled, "order_index": getattr(pack, "order_index", 0),
        "pack_subtype": getattr(pack, "pack_subtype", "standalone"),
        "playlist": getattr(pack, "playlist", None),
        "favorites_cap": getattr(pack, "favorites_cap", None),
        "collection_label": getattr(pack, "collection_label", None),
        "upsell_pack_ids": getattr(pack, "upsell_pack_ids", None),
        "hd_sla_minutes": getattr(pack, "hd_sla_minutes", 10),
    }


@router.post("/packs")
def packs_create(payload: dict, db: Session = Depends(get_db)):
    subtype = payload.get("pack_subtype", "standalone")
    playlist = payload.get("playlist")
    is_enabled = bool(payload.get("enabled", True))

    if subtype == "collection" and is_enabled:
        if not playlist or not isinstance(playlist, list) or len(playlist) == 0:
            raise HTTPException(400, "Collection pack must have a non-empty playlist before enabling")

    pack = Pack(
        id=payload.get("id") or payload.get("name", "").lower().replace(" ", "_"),
        name=payload.get("name", "New Pack"),
        emoji=payload.get("emoji", "📦"),
        tokens=int(payload.get("tokens", 0)),
        stars_price=int(payload.get("stars_price", 0)),
        enabled=is_enabled,
        order_index=int(payload.get("order_index", 0)),
        takes_limit=payload.get("takes_limit"),
        hd_amount=payload.get("hd_amount"),
        is_trial=bool(payload.get("is_trial", False)),
        pack_type=payload.get("pack_type", "session"),
        upgrade_target_pack_ids=payload.get("upgrade_target_pack_ids"),
        pack_subtype=subtype,
        playlist=playlist,
        favorites_cap=payload.get("favorites_cap"),
        collection_label=payload.get("collection_label"),
        upsell_pack_ids=payload.get("upsell_pack_ids"),
        hd_sla_minutes=int(payload.get("hd_sla_minutes", 10)),
    )
    db.add(pack)
    db.commit()
    db.refresh(pack)
    return {
        "id": pack.id, "name": pack.name, "emoji": pack.emoji,
        "tokens": pack.tokens, "stars_price": pack.stars_price,
        "enabled": pack.enabled, "pack_subtype": pack.pack_subtype,
    }


@router.delete("/packs/{pack_id}")
def packs_delete(pack_id: str, db: Session = Depends(get_db)):
    pack = db.query(Pack).filter(Pack.id == pack_id).first()
    if not pack:
        raise HTTPException(404, "Pack not found")
    db.delete(pack)
    db.commit()
    return {"ok": True}


# ---------- Compensations ----------
from app.models.compensation import CompensationLog


@router.get("/compensations")
def compensations_list(
    db: Session = Depends(get_db),
    user_id: str | None = Query(None),
    reason: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    q = db.query(CompensationLog)
    if user_id:
        q = q.filter(CompensationLog.user_id == user_id)
    if reason:
        q = q.filter(CompensationLog.reason == reason)
    total = q.count()
    items = (
        q.order_by(CompensationLog.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "total": total,
        "page": page,
        "items": [
            {
                "id": c.id,
                "user_id": c.user_id,
                "favorite_id": c.favorite_id,
                "session_id": c.session_id,
                "reason": c.reason,
                "comp_type": c.comp_type,
                "amount": c.amount,
                "correlation_id": c.correlation_id,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in items
        ],
    }


@router.get("/compensations/stats")
def compensations_stats(db: Session = Depends(get_db)):
    total = db.query(func.count(CompensationLog.id)).scalar() or 0
    by_reason = dict(
        db.query(CompensationLog.reason, func.count(CompensationLog.id))
        .group_by(CompensationLog.reason)
        .all()
    )
    seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
    by_day_rows = (
        db.query(
            func.date(CompensationLog.created_at).label("day"),
            func.count(CompensationLog.id),
        )
        .filter(CompensationLog.created_at >= seven_days_ago)
        .group_by("day")
        .order_by("day")
        .all()
    )
    by_day = {str(row[0]): row[1] for row in by_day_rows}
    return {"total": total, "by_reason": by_reason, "by_day": by_day}


# ---------- Sessions ----------
from app.models.session import Session as SessionModel


@router.get("/sessions")
def sessions_list(
    db: Session = Depends(get_db),
    user_id: str | None = Query(None),
    status: str | None = Query(None),
    pack_id: str | None = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
):
    """List sessions with optional filters."""
    q = db.query(SessionModel)
    if user_id:
        q = q.filter(SessionModel.user_id == user_id)
    if status:
        q = q.filter(SessionModel.status == status)
    if pack_id:
        q = q.filter(SessionModel.pack_id == pack_id)
    total = q.count()
    sessions = q.order_by(SessionModel.created_at.desc()).offset(offset).limit(limit).all()
    return {
        "total": total,
        "items": [
            {
                "id": s.id,
                "user_id": s.user_id,
                "pack_id": s.pack_id,
                "takes_limit": s.takes_limit,
                "takes_used": s.takes_used,
                "status": s.status,
                "upgraded_from_session_id": s.upgraded_from_session_id,
                "upgrade_credit_stars": s.upgrade_credit_stars,
                "created_at": s.created_at.isoformat() if s.created_at else None,
                "updated_at": s.updated_at.isoformat() if s.updated_at else None,
            }
            for s in sessions
        ],
    }


# ---------- Themes ----------
THEME_EDIT_FIELDS = {"name", "emoji", "order_index", "enabled"}


def _theme_to_item(theme: Theme) -> dict:
    return {
        "id": theme.id,
        "name": theme.name,
        "emoji": theme.emoji or "",
        "order_index": theme.order_index,
        "enabled": theme.enabled,
    }


@router.get("/themes")
def admin_themes_list(db: Session = Depends(get_db)):
    svc = ThemeService(db)
    themes = svc.list_all()
    return [_theme_to_item(t) for t in themes]


@router.get("/themes/{theme_id}")
def admin_themes_get(theme_id: str, db: Session = Depends(get_db)):
    svc = ThemeService(db)
    theme = svc.get(theme_id)
    if not theme:
        raise HTTPException(404, "Theme not found")
    return _theme_to_item(theme)


@router.post("/themes")
def admin_themes_post(payload: dict = Body(...), db: Session = Depends(get_db)):
    svc = ThemeService(db)
    data = {k: v for k, v in payload.items() if k in THEME_EDIT_FIELDS}
    data.setdefault("emoji", "")
    data.setdefault("order_index", 0)
    data.setdefault("enabled", True)
    themes = svc.list_all()
    if themes:
        data.setdefault("order_index", max(t.order_index for t in themes) + 1)
    theme = svc.create(data)
    return _theme_to_item(theme)


@router.put("/themes/{theme_id}")
def admin_themes_put(theme_id: str, payload: dict = Body(...), db: Session = Depends(get_db)):
    svc = ThemeService(db)
    theme = svc.get(theme_id)
    if not theme:
        raise HTTPException(404, "Theme not found")
    data = {k: v for k, v in payload.items() if k in THEME_EDIT_FIELDS}
    if not data:
        return _theme_to_item(theme)
    svc.update(theme, data)
    return _theme_to_item(theme)


@router.patch("/themes/{theme_id}/order")
def admin_themes_patch_order(theme_id: str, payload: dict = Body(...), db: Session = Depends(get_db)):
    direction = payload.get("direction")
    if direction not in ("up", "down"):
        raise HTTPException(400, "direction must be 'up' or 'down'")
    svc = ThemeService(db)
    theme = svc.patch_order(theme_id, direction)
    if not theme:
        raise HTTPException(404, "Theme not found")
    return _theme_to_item(theme)


@router.delete("/themes/{theme_id}")
def admin_themes_delete(theme_id: str, db: Session = Depends(get_db)):
    svc = ThemeService(db)
    theme = svc.get(theme_id)
    if not theme:
        raise HTTPException(404, "Theme not found")
    svc.delete(theme)
    return {"ok": True}


# ---------- Trends ----------
# Allowed fields for trend create/update (subset of Trend model)
TREND_EDIT_FIELDS = {
    "name", "emoji", "description", "system_prompt", "scene_prompt", "subject_prompt",
    "negative_prompt", "negative_scene", "composition_prompt", "subject_mode", "framing_hint", "style_preset",
    "max_images", "enabled", "order_index", "theme_id", "prompt_sections", "prompt_model", "prompt_size",
    "prompt_format", "prompt_temperature", "prompt_seed", "prompt_image_size_tier",
}
MAX_TREND_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
ALLOWED_TREND_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}


def _trend_to_item(t: Trend) -> dict:
    sections = t.prompt_sections if isinstance(t.prompt_sections, list) else []
    has_playground = len(sections) > 0
    # has_example — по наличию файла на диске, а не только по пути в БД
    example_path = _resolve_trend_media_path(t.example_image_path, t.id, "_example")
    return {
        "id": t.id,
        "theme_id": t.theme_id,
        "name": t.name,
        "emoji": t.emoji,
        "description": t.description,
        "enabled": t.enabled,
        "order_index": t.order_index,
        "has_example": example_path is not None,
        "prompt_config_source": "playground" if has_playground else "scene",
        "subject_mode": t.subject_mode or "face",
        "framing_hint": t.framing_hint or "portrait",
    }


def _trend_to_detail(t: Trend) -> dict:
    return {
        "id": t.id,
        "theme_id": t.theme_id,
        "name": t.name,
        "emoji": t.emoji,
        "description": t.description,
        "system_prompt": t.system_prompt or "",
        "scene_prompt": t.scene_prompt,
        "subject_prompt": t.subject_prompt,
        "negative_prompt": t.negative_prompt or "",
        "negative_scene": t.negative_scene,
        "composition_prompt": getattr(t, "composition_prompt", None),
        "subject_mode": t.subject_mode,
        "framing_hint": t.framing_hint,
        "style_preset": t.style_preset,
        "max_images": t.max_images,
        "enabled": t.enabled,
        "order_index": t.order_index,
        "prompt_sections": t.prompt_sections,
        "prompt_model": t.prompt_model,
        "prompt_size": t.prompt_size,
        "prompt_format": t.prompt_format,
        "prompt_temperature": t.prompt_temperature,
        "prompt_seed": t.prompt_seed,
        "prompt_image_size_tier": getattr(t, "prompt_image_size_tier", None),
    }


def _get_trend_examples_dir() -> str:
    base = getattr(app_settings, "trend_examples_dir", "data/trend_examples")
    if os.path.isabs(base):
        return base
    return os.path.join(os.getcwd(), base)


@router.get("/trends")
def admin_trends_list(db: Session = Depends(get_db)):
    svc = TrendService(db)
    trends = svc.list_all()
    return [_trend_to_item(t) for t in trends]


@router.get("/trends/{trend_id}")
def admin_trends_get(trend_id: str, db: Session = Depends(get_db)):
    svc = TrendService(db)
    trend = svc.get(trend_id)
    if not trend:
        raise HTTPException(404, "Trend not found")
    return _trend_to_detail(trend)


def _normalize_trend_payload(data: dict) -> dict:
    """Нормализуем theme_id: пустая строка или пустое значение → None."""
    if "theme_id" in data and (data["theme_id"] is None or data["theme_id"] == ""):
        data = {**data, "theme_id": None}
    return data


@router.put("/trends/{trend_id}")
def admin_trends_put(trend_id: str, payload: dict = Body(...), db: Session = Depends(get_db)):
    svc = TrendService(db)
    trend = svc.get(trend_id)
    if not trend:
        raise HTTPException(404, "Trend not found")
    data = {k: v for k, v in payload.items() if k in TREND_EDIT_FIELDS}
    data = _normalize_trend_payload(data)
    if not data:
        return _trend_to_detail(trend)
    svc.update(trend, data)
    return _trend_to_detail(trend)


@router.post("/trends")
def admin_trends_post(payload: dict = Body(...), db: Session = Depends(get_db)):
    svc = TrendService(db)
    data = {k: v for k, v in payload.items() if k in TREND_EDIT_FIELDS}
    data = _normalize_trend_payload(data)
    data.setdefault("description", "")
    data.setdefault("system_prompt", "")
    data.setdefault("negative_prompt", "")
    if data.get("theme_id") is not None:
        trends_in_theme = [t for t in svc.list_all() if t.theme_id == data["theme_id"]]
        max_order = max((t.order_index for t in trends_in_theme), default=-1)
        data.setdefault("order_index", max_order + 1)
    trend = svc.create(data)
    return _trend_to_detail(trend)


def _serve_trend_file(path: str | None, trend_id: str, kind: str):
    if not path or not os.path.isfile(path):
        raise HTTPException(404, f"{kind} not found")
    ext = os.path.splitext(path)[1].lower() or ".jpg"
    media = "image/jpeg" if ext in (".jpg", ".jpeg") else "image/png" if ext == ".png" else "image/webp"
    return FileResponse(path, media_type=media)


def _resolve_trend_media_path(stored_path: str | None, trend_id: str, suffix: str) -> str | None:
    if not stored_path:
        return None
    if os.path.isabs(stored_path) and os.path.isfile(stored_path):
        return stored_path
    base = _get_trend_examples_dir()
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        p = os.path.join(base, f"{trend_id}{suffix}{ext}")
        if os.path.isfile(p):
            return p
    return None


@router.get("/trends/{trend_id}/example")
def admin_trends_get_example(trend_id: str, db: Session = Depends(get_db)):
    svc = TrendService(db)
    trend = svc.get(trend_id)
    if not trend:
        raise HTTPException(404, "Trend not found")
    path = _resolve_trend_media_path(trend.example_image_path, trend_id, "_example")
    if not path:
        raise HTTPException(404, "Example not found")
    return _serve_trend_file(path, trend_id, "Example")


def _save_trend_file(trend_id: str, file: UploadFile, suffix: str) -> str:
    if file.content_type and file.content_type.lower() not in ALLOWED_TREND_IMAGE_TYPES:
        raise HTTPException(400, "Недопустимый тип файла. Разрешены: JPEG, PNG, WebP")
    content = file.file.read()
    if len(content) > MAX_TREND_FILE_SIZE:
        raise HTTPException(400, "Файл слишком большой (макс. 10 MB)")
    base = _get_trend_examples_dir()
    os.makedirs(base, exist_ok=True)
    ext = ".jpg"
    if file.content_type:
        if "png" in file.content_type:
            ext = ".png"
        elif "webp" in file.content_type:
            ext = ".webp"
    path = os.path.join(base, f"{trend_id}{suffix}{ext}")
    with open(path, "wb") as f:
        f.write(content)
    return path


@router.post("/trends/{trend_id}/example")
def admin_trends_post_example(trend_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    svc = TrendService(db)
    trend = svc.get(trend_id)
    if not trend:
        raise HTTPException(404, "Trend not found")
    path = _save_trend_file(trend_id, file, "_example")
    svc.update(trend, {"example_image_path": path})
    return _trend_to_detail(trend)


@router.delete("/trends/{trend_id}/example")
def admin_trends_delete_example(trend_id: str, db: Session = Depends(get_db)):
    svc = TrendService(db)
    trend = svc.get(trend_id)
    if not trend:
        raise HTTPException(404, "Trend not found")
    path = trend.example_image_path
    if path and os.path.isfile(path):
        try:
            os.remove(path)
        except OSError:
            pass
    svc.update(trend, {"example_image_path": None})
    return _trend_to_detail(trend)


@router.get("/trends/{trend_id}/playground-config")
def admin_trends_playground_config(trend_id: str, db: Session = Depends(get_db)):
    """Return PlaygroundPromptConfig for this trend (single source of truth for Playground load)."""
    svc = TrendService(db)
    trend = svc.get(trend_id)
    if not trend:
        raise HTTPException(404, "Trend not found")
    gs = GenerationPromptSettingsService(db)
    effective = gs.get_effective()
    config = trend_to_playground_config(
        trend,
        default_model=effective.get("default_model", "gemini-2.5-flash-image"),
        default_temperature=effective.get("default_temperature", 0.4),
        default_format=effective.get("default_format", "png"),
        default_size=effective.get("default_size") or "1024x1024",
    )
    return config.model_dump()


@router.get("/trends/{trend_id}/prompt-preview")
def admin_trends_prompt_preview(trend_id: str, db: Session = Depends(get_db)):
    from app.workers.tasks.generation_v2 import _build_prompt_for_job
    svc = TrendService(db)
    trend = svc.get(trend_id)
    if not trend:
        raise HTTPException(404, "Trend not found")
    try:
        class _MockJob:
            image_size = getattr(trend, "prompt_size", None)
        prompt_text, negative, model, size = _build_prompt_for_job(db, _MockJob(), trend)
        return {
            "prompt": prompt_text,
            "model": model,
            "size": size,
            "format": "png",
            "request_as_seen": f"contents[0].parts = [ image (user photo), text (prompt) ]",
        }
    except Exception as e:
        import logging
        logging.getLogger(__name__).exception("prompt_preview_failed")
        raise HTTPException(500, "Не удалось построить превью промпта")


@router.patch("/trends/{trend_id}/order")
def admin_trends_patch_order(trend_id: str, payload: dict = Body(...), db: Session = Depends(get_db)):
    direction = payload.get("direction")
    if direction not in ("up", "down"):
        raise HTTPException(400, "direction must be 'up' or 'down'")
    svc = TrendService(db)
    trend = svc.get(trend_id)
    if not trend:
        raise HTTPException(404, "Trend not found")
    trends = svc.list_all()
    idx = next((i for i, t in enumerate(trends) if t.id == trend_id), None)
    if idx is None:
        raise HTTPException(404, "Trend not found")
    # Swap only within same theme (theme_id match, including both None)
    if direction == "up":
        swap_idx = next(
            (i for i in range(idx - 1, -1, -1) if trends[i].theme_id == trend.theme_id),
            None,
        )
    else:
        swap_idx = next(
            (i for i in range(idx + 1, len(trends)) if trends[i].theme_id == trend.theme_id),
            None,
        )
    if swap_idx is None:
        return _trend_to_detail(trend)
    other = trends[swap_idx]
    svc.update(trend, {"order_index": other.order_index})
    svc.update(other, {"order_index": trend.order_index})
    db.refresh(trend)
    return _trend_to_detail(trend)


# ---------- Audit ----------
@router.get("/audit")
def audit_list(
    db: Session = Depends(get_db),
    action: str | None = None,
    actor_type: str | None = None,
    entity_type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    search: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    q = db.query(AuditLog)
    if action:
        q = q.filter(AuditLog.action == action)
    if actor_type:
        q = q.filter(AuditLog.actor_type == actor_type)
    if entity_type:
        q = q.filter(AuditLog.entity_type == entity_type)
    if date_from:
        try:
            since = datetime.fromisoformat(date_from.replace("Z", "+00:00"))
            q = q.filter(AuditLog.created_at >= since)
        except (ValueError, TypeError):
            pass
    if date_to:
        try:
            until = datetime.fromisoformat(date_to.replace("Z", "+00:00"))
            q = q.filter(AuditLog.created_at <= until)
        except (ValueError, TypeError):
            pass
    if search and search.strip():
        term = f"%{search.strip()}%"
        q = q.filter(
            or_(
                and_(AuditLog.actor_id.isnot(None), AuditLog.actor_id.ilike(term)),
                and_(AuditLog.entity_id.isnot(None), AuditLog.entity_id.ilike(term)),
            )
        )
    total = q.count()
    q = q.order_by(AuditLog.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    rows = q.all()
    items = [
        {
            "id": r.id,
            "actor_type": r.actor_type,
            "actor_id": r.actor_id,
            "action": r.action,
            "entity_type": r.entity_type,
            "entity_id": r.entity_id,
            "payload": r.payload or {},
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
    return {"items": items, "total": total, "page": page, "pages": (total + page_size - 1) // page_size}


@router.get("/audit/stats")
def audit_stats(db: Session = Depends(get_db), window_hours: int = Query(24, ge=1)):
    since = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    total = db.query(AuditLog).filter(AuditLog.created_at >= since).count()
    by_actor = db.query(AuditLog.actor_type, func.count(AuditLog.id)).filter(AuditLog.created_at >= since).group_by(AuditLog.actor_type).all()
    return {"total": total, "by_actor_type": dict(by_actor), "window_hours": window_hours}


# ---------- Broadcast ----------
@router.get("/broadcast/preview")
def broadcast_preview(db: Session = Depends(get_db), include_blocked: bool = Query(False)):
    total = db.query(User).count()
    if include_blocked:
        return {"recipients": total, "total_users": total, "excluded": 0}
    now = datetime.now(timezone.utc)
    excluded = db.query(User).filter(User.is_banned.is_(True)).count()
    excluded += db.query(User).filter(User.is_suspended.is_(True), User.suspended_until.isnot(None), User.suspended_until > now).count()
    return {"recipients": max(0, total - excluded), "total_users": total, "excluded": excluded}


@router.post("/broadcast/send")
def broadcast_send(payload: dict, db: Session = Depends(get_db)):
    message = (payload.get("message") or "").strip()
    include_blocked = bool(payload.get("include_blocked", False))
    if not message:
        raise HTTPException(400, "message is required")
    result = broadcast_message.delay(message, include_blocked=include_blocked)
    return {"task_id": result.id, "message": "Broadcast task queued"}


# ---------- Jobs ----------
@router.get("/jobs/stats")
def jobs_stats(
    db: Session = Depends(get_db),
    hours: int = Query(24, ge=1, le=720),
):
    """Aggregates for jobs in the last N hours (for KPI cards)."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    q = db.query(Job).filter(Job.created_at >= since)
    total = q.count()
    succeeded = q.filter(Job.status == "SUCCEEDED").count()
    failed = q.filter(Job.status.in_(["FAILED", "ERROR"])).count()
    in_queue = q.filter(Job.status.in_(["CREATED", "RUNNING"])).count()
    return {
        "total": total,
        "succeeded": succeeded,
        "failed": failed,
        "in_queue": in_queue,
        "hours": hours,
    }


@router.get("/jobs")
def jobs_list(
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    status: str | None = None,
    telegram_id: str | None = None,
    trend_id: str | None = None,
    hours: int | None = Query(None, ge=1, le=720),
):
    q = db.query(Job)
    if status:
        q = q.filter(Job.status == status)
    if telegram_id:
        u = db.query(User).filter(User.telegram_id == telegram_id).first()
        if u:
            q = q.filter(Job.user_id == u.id)
        else:
            q = q.filter(Job.user_id == "")
    if trend_id:
        q = q.filter(Job.trend_id == trend_id)
    if hours is not None:
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        q = q.filter(Job.created_at >= since)
    total = q.count()
    q = q.order_by(Job.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    jobs = q.all()
    user_ids = [j.user_id for j in jobs]
    trend_ids = list({j.trend_id for j in jobs})
    users = {u.id: u for u in db.query(User).filter(User.id.in_(user_ids)).all()} if user_ids else {}
    trends = {t.id: t for t in db.query(Trend).filter(Trend.id.in_(trend_ids)).all()} if trend_ids else {}
    items = []
    for j in jobs:
        u = users.get(j.user_id)
        t = trends.get(j.trend_id)
        items.append({
            "job_id": j.job_id,
            "user_id": j.user_id,
            "telegram_id": u.telegram_id if u else None,
            "trend_id": j.trend_id,
            "trend_name": t.name if t else None,
            "trend_emoji": t.emoji if t else None,
            "status": j.status,
            "reserved_tokens": j.reserved_tokens,
            "error_code": j.error_code,
            "created_at": j.created_at.isoformat() if j.created_at else None,
        })
    return {"items": items, "total": total, "page": page, "pages": (total + page_size - 1) // page_size}


@router.get("/jobs/{job_id}")
def jobs_get(job_id: str, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.job_id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")
    u = db.query(User).filter(User.id == job.user_id).first()
    return {
        "job_id": job.job_id,
        "user_id": job.user_id,
        "telegram_id": u.telegram_id if u else None,
        "trend_id": job.trend_id,
        "status": job.status,
        "reserved_tokens": job.reserved_tokens,
        "error_code": job.error_code,
        "input_file_ids": job.input_file_ids,
        "output_path": job.output_path,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
    }


# ---------- Copy style ----------
@router.get("/settings/copy-style")
def copy_style_get(db: Session = Depends(get_db)):
    svc = CopyStyleSettingsService(db)
    return svc.get_effective()


@router.put("/settings/copy-style")
def copy_style_put(payload: dict, db: Session = Depends(get_db)):
    svc = CopyStyleSettingsService(db)
    return svc.update(payload)


# ---------- Cleanup ----------
@router.get("/cleanup/preview")
def cleanup_preview(db: Session = Depends(get_db), older_than_hours: int = Query(24, ge=1)):
    svc = CleanupService(db)
    return svc.preview_temp_cleanup(older_than_hours)


@router.post("/cleanup/run")
def cleanup_run(db: Session = Depends(get_db), older_than_hours: int = Query(24, ge=1)):
    svc = CleanupService(db)
    return svc.cleanup_temp_files(older_than_hours)


# ---------- Referrals ----------

@router.get("/referrals/stats")
def referrals_stats(db: Session = Depends(get_db)):
    """Aggregate referral program statistics."""
    total_attributed = (
        db.query(func.count(User.id))
        .filter(User.referred_by_user_id.isnot(None))
        .scalar() or 0
    )
    total_bonuses = db.query(func.count(ReferralBonus.id)).scalar() or 0
    pending = (
        db.query(func.count(ReferralBonus.id))
        .filter(ReferralBonus.status == "pending")
        .scalar() or 0
    )
    available = (
        db.query(func.count(ReferralBonus.id))
        .filter(ReferralBonus.status == "available")
        .scalar() or 0
    )
    spent = (
        db.query(func.count(ReferralBonus.id))
        .filter(ReferralBonus.status == "spent")
        .scalar() or 0
    )
    revoked = (
        db.query(func.count(ReferralBonus.id))
        .filter(ReferralBonus.status == "revoked")
        .scalar() or 0
    )
    total_credits_pending = (
        db.query(func.coalesce(func.sum(ReferralBonus.hd_credits_amount), 0))
        .filter(ReferralBonus.status == "pending")
        .scalar()
    )
    total_credits_available = (
        db.query(func.coalesce(func.sum(ReferralBonus.hd_credits_amount), 0))
        .filter(ReferralBonus.status == "available")
        .scalar()
    )
    total_credits_spent = (
        db.query(func.coalesce(func.sum(ReferralBonus.hd_credits_amount), 0))
        .filter(ReferralBonus.status == "spent")
        .scalar()
    )
    return {
        "total_attributed": total_attributed,
        "total_bonuses": total_bonuses,
        "by_status": {
            "pending": pending,
            "available": available,
            "spent": spent,
            "revoked": revoked,
        },
        "credits": {
            "pending": total_credits_pending,
            "available": total_credits_available,
            "spent": total_credits_spent,
        },
    }


@router.get("/referrals/bonuses")
def referrals_bonuses_list(
    status: str | None = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    db: Session = Depends(get_db),
):
    """List referral bonuses with optional status filter."""
    q = db.query(ReferralBonus)
    if status:
        q = q.filter(ReferralBonus.status == status)
    total = q.count()
    bonuses = q.order_by(ReferralBonus.created_at.desc()).offset(offset).limit(limit).all()

    items = []
    for b in bonuses:
        referrer = db.query(User.telegram_username, User.telegram_first_name).filter(User.id == b.referrer_user_id).first()
        referral = db.query(User.telegram_username, User.telegram_first_name).filter(User.id == b.referral_user_id).first()
        items.append({
            "id": b.id,
            "referrer_user_id": b.referrer_user_id,
            "referrer_name": (referrer.telegram_username or referrer.telegram_first_name) if referrer else None,
            "referral_user_id": b.referral_user_id,
            "referral_name": (referral.telegram_username or referral.telegram_first_name) if referral else None,
            "payment_id": b.payment_id,
            "pack_stars": b.pack_stars,
            "hd_credits_amount": b.hd_credits_amount,
            "status": b.status,
            "created_at": b.created_at.isoformat() if b.created_at else None,
            "available_at": b.available_at.isoformat() if b.available_at else None,
            "spent_at": b.spent_at.isoformat() if b.spent_at else None,
            "revoked_at": b.revoked_at.isoformat() if b.revoked_at else None,
            "revoke_reason": b.revoke_reason,
        })
    return {"total": total, "items": items}


@router.post("/referrals/bonuses/{bonus_id}/freeze")
def referrals_bonus_freeze(bonus_id: str, db: Session = Depends(get_db)):
    """Freeze a bonus for manual review."""
    ref_svc = ReferralService(db)
    ok = ref_svc.freeze_bonus(bonus_id)
    if not ok:
        raise HTTPException(400, "Cannot freeze this bonus (already spent/revoked or not found)")
    db.commit()
    return {"ok": True}
