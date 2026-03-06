"""
Admin API: security, settings, users, telegram messages, telemetry, bank transfer,
payments, packs, trends, audit, broadcast, jobs, copy style, cleanup.
Paths match admin-frontend/src/services/api.ts. Order: /users/analytics and /users before /users/{id}.
"""
import logging
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.db.session import get_db
from app.models.audit_log import AuditLog
from app.models.product_event import ProductEvent
from app.models.bank_transfer_receipt_log import BankTransferReceiptLog
from app.models.job import Job
from app.models.pack import Pack
from app.models.take import Take
from app.models.payment import Payment
from app.constants import AUDIENCE_CHOICES, normalize_target_audiences
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
from app.models.traffic_source import TrafficSource
from app.models.ad_campaign import AdCampaign
from app.models.photo_merge_job import PhotoMergeJob
from app.models.poster_settings import PosterSettings
from app.models.trend_post import TrendPost
from app.services.photo_merge.settings_service import PhotoMergeSettingsService
from app.services.telegram.client import TelegramClient

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
    svc = GenerationPromptSettingsService(db)
    app_svc = AppSettingsService(db)
    result = svc.as_dict()
    app_dict = app_svc.as_dict()
    result["use_nano_banana_pro"] = app_dict.get("use_nano_banana_pro", False)
    result["watermark_text"] = app_dict.get("watermark_text")
    result["watermark_text_effective"] = (
        app_dict.get("watermark_text") or getattr(app_settings, "watermark_text", "NanoBanan Preview")
    )
    result["watermark_opacity"] = app_dict.get("watermark_opacity", 60)
    result["watermark_tile_spacing"] = app_dict.get("watermark_tile_spacing", 200)
    result["take_preview_max_dim"] = app_dict.get("take_preview_max_dim", 800)
    return result


@router.put("/settings/master-prompt")
def master_prompt_put(payload: dict, db: Session = Depends(get_db)):
    svc = GenerationPromptSettingsService(db)
    app_svc = AppSettingsService(db)
    app_keys = {"use_nano_banana_pro", "watermark_text", "watermark_opacity", "watermark_tile_spacing", "take_preview_max_dim"}
    app_payload = {k: v for k, v in payload.items() if k in app_keys}
    if app_payload:
        app_svc.update(app_payload)
    data = {k: v for k, v in payload.items() if k not in app_keys}
    if data:
        svc.update(data)
    return master_prompt_get(db)


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
    jobs_in_window = (
        db.query(
            Job.user_id,
            func.count(Job.job_id).label("jobs_count"),
            func.sum(case((Job.status == "SUCCEEDED", 1), else_=0)).label("succeeded"),
            func.sum(case((Job.status.in_(["FAILED", "ERROR"]), 1), else_=0)).label("failed"),
        )
        .filter(Job.created_at >= since)
        .group_by(Job.user_id)
    )
    total_jobs = 0
    top_list = []
    for row in jobs_in_window:
        total_jobs += row.jobs_count or 0
        top_list.append({
            "user_id": row.user_id,
            "jobs_count": int(row.jobs_count or 0),
            "succeeded": int(row.succeeded or 0),
            "failed": int(row.failed or 0),
        })
    top_list.sort(key=lambda x: x["jobs_count"], reverse=True)
    users_with_jobs = len(top_list)
    user_ids = [t["user_id"] for t in top_list[:20]]
    users_rows = db.query(User).filter(User.id.in_(user_ids)).all() if user_ids else []
    users_map = {}
    for u in users_rows:
        if u.telegram_username:
            display_name = f"@{u.telegram_username}"
        else:
            name = f"{u.telegram_first_name or ''} {u.telegram_last_name or ''}".strip()
            display_name = name or u.telegram_id
        users_map[u.id] = {
            "telegram_id": u.telegram_id,
            "user_display_name": display_name,
            "subscription_active": u.subscription_active,
            "token_balance": u.token_balance or 0,
        }
    top_users = []
    for t in top_list[:10]:
        u = users_map.get(t["user_id"], {})
        top_users.append({
            "telegram_id": u.get("telegram_id", t["user_id"]),
            "user_display_name": u.get("user_display_name"),
            "jobs_count": t["jobs_count"],
            "succeeded": t["succeeded"],
            "failed": t["failed"],
            "subscription_active": u.get("subscription_active", False),
            "token_balance": u.get("token_balance", 0),
        })
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
    takes_window = (
        db.query(func.count(Take.id)).filter(Take.created_at >= since).scalar() or 0
    )
    succeeded = (db.query(func.count(Job.job_id)).filter(Job.status == "SUCCEEDED").scalar() or 0)
    queue_length = (db.query(func.count(Job.job_id)).filter(Job.status.in_(["CREATED", "RUNNING"])).scalar() or 0)
    # Статистика Take по трендам за окно (снимки — основной флоу «Создать фото»)
    take_stats_q = (
        db.query(
            Take.trend_id,
            func.count(Take.id).label("takes_window"),
            func.sum(case((Take.status.in_(["ready", "partial_fail"]), 1), else_=0)).label("takes_succeeded"),
            func.sum(case((Take.status == "failed", 1), else_=0)).label("takes_failed"),
        )
        .filter(Take.trend_id.isnot(None), Take.trend_id != "", Take.created_at >= since)
        .group_by(Take.trend_id)
        .all()
    )
    take_stats_by_trend = {
        r.trend_id: {
            "takes_window": r.takes_window or 0,
            "takes_succeeded": r.takes_succeeded or 0,
            "takes_failed": r.takes_failed or 0,
        }
        for r in take_stats_q
    }
    # Топ трендов за окно: по Job (задачи) и по Take (снимки)
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
            "takes_window": take_stats_by_trend.get(r.id, {}).get("takes_window", 0),
            "takes_succeeded_window": take_stats_by_trend.get(r.id, {}).get("takes_succeeded", 0),
            "takes_failed_window": take_stats_by_trend.get(r.id, {}).get("takes_failed", 0),
        }
        for r in trend_stats
    ]
    # Добавить тренды, у которых есть только Take (снимки), без Job
    trend_ids_in_analytics = {t["trend_id"] for t in trend_analytics_window}
    only_take_trend_ids = [tid for tid in take_stats_by_trend if tid not in trend_ids_in_analytics]
    if only_take_trend_ids:
        for trend_row in db.query(Trend).filter(Trend.id.in_(only_take_trend_ids)).all():
            ts = take_stats_by_trend.get(trend_row.id, {})
            trend_analytics_window.append({
                "trend_id": trend_row.id,
                "name": trend_row.name or trend_row.id,
                "emoji": trend_row.emoji or "",
                "jobs_window": 0,
                "succeeded_window": 0,
                "failed_window": 0,
                "takes_window": ts.get("takes_window", 0),
                "takes_succeeded_window": ts.get("takes_succeeded", 0),
                "takes_failed_window": ts.get("takes_failed", 0),
            })
    # Телеметрия «какие картинки выбраны»: выбор варианта (в избранное) по трендам за окно
    chosen_actions = ("choose_best_variant", "favorites_auto_add")
    chosen_q = (
        db.query(
            func.coalesce(AuditLog.payload["trend_id"].astext, "").label("trend_id"),
            func.count(AuditLog.id).label("cnt"),
        )
        .filter(
            AuditLog.action.in_(chosen_actions),
            AuditLog.created_at >= since,
        )
        .group_by(func.coalesce(AuditLog.payload["trend_id"].astext, ""))
    )
    variants_chosen_by_trend = {
        r.trend_id: r.cnt for r in chosen_q.all() if r.trend_id and str(r.trend_id).strip()
    }
    for t in trend_analytics_window:
        t["chosen_window"] = variants_chosen_by_trend.get(t["trend_id"], 0)
    # Сортировка по суммарной активности (задачи + снимки), чтобы топ был релевантным
    def _trend_activity(t: dict) -> int:
        return (t.get("jobs_window") or 0) + (t.get("takes_window") or 0)
    trend_analytics_window.sort(key=_trend_activity, reverse=True)
    trend_ids_in_analytics = {t["trend_id"] for t in trend_analytics_window}
    only_chosen_ids = [tid for tid in variants_chosen_by_trend if tid not in trend_ids_in_analytics]
    if only_chosen_ids:
        for trend_row in db.query(Trend).filter(Trend.id.in_(only_chosen_ids)).all():
            ts = take_stats_by_trend.get(trend_row.id, {})
            trend_analytics_window.append({
                "trend_id": trend_row.id,
                "name": trend_row.name or trend_row.id,
                "emoji": trend_row.emoji or "",
                "jobs_window": 0,
                "succeeded_window": 0,
                "failed_window": 0,
                "takes_window": ts.get("takes_window", 0),
                "takes_succeeded_window": ts.get("takes_succeeded", 0),
                "takes_failed_window": ts.get("takes_failed", 0),
                "chosen_window": variants_chosen_by_trend.get(trend_row.id, 0),
            })
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
        "takes_window": takes_window,
        "queue_length": queue_length,
        "succeeded": succeeded,
        "jobs_by_status": jobs_by_status,
        "jobs_failed_by_error": jobs_failed_by_error,
        "trend_analytics_window": trend_analytics_window,
        "variants_chosen_by_trend": variants_chosen_by_trend,
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


@router.get("/telemetry/errors")
def telemetry_errors(db: Session = Depends(get_db), window_days: int = Query(30, ge=1, le=90)):
    """Телеметрия ошибок за период: Job и Take по error_code + распределение по датам. По умолчанию 30 дней."""
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=window_days)
    job_errors = (
        db.query(func.coalesce(Job.error_code, "unknown").label("code"), func.count(Job.job_id).label("cnt"))
        .filter(Job.status == "FAILED", Job.created_at >= since)
        .group_by(func.coalesce(Job.error_code, "unknown"))
        .all()
    )
    take_errors = (
        db.query(func.coalesce(Take.error_code, "unknown").label("code"), func.count(Take.id).label("cnt"))
        .filter(Take.status == "failed", Take.created_at >= since)
        .group_by(func.coalesce(Take.error_code, "unknown"))
        .all()
    )
    jobs_failed_by_error = {row[0]: row[1] for row in job_errors}
    takes_failed_by_error = {row[0]: row[1] for row in take_errors}
    combined: dict[str, dict[str, int]] = {}
    for code, cnt in job_errors:
        combined.setdefault(code, {"job": 0, "take": 0})["job"] = cnt
    for code, cnt in take_errors:
        combined.setdefault(code, {"job": 0, "take": 0})["take"] = cnt

    # Распределение ошибок по датам за окно (для графика)
    jobs_by_day = (
        db.query(func.date(Job.created_at).label("date"), func.count(Job.job_id).label("cnt"))
        .filter(Job.status == "FAILED", Job.created_at >= since)
        .group_by(func.date(Job.created_at))
        .all()
    )
    takes_by_day = (
        db.query(func.date(Take.created_at).label("date"), func.count(Take.id).label("cnt"))
        .filter(Take.status == "failed", Take.created_at >= since)
        .group_by(func.date(Take.created_at))
        .all()
    )
    jobs_failed_by_date = {str(r.date): r.cnt for r in jobs_by_day}
    takes_failed_by_date = {str(r.date): r.cnt for r in takes_by_day}
    errors_by_day = []
    for i in range(window_days):
        d = (now - timedelta(days=window_days - 1 - i)).date()
        key = str(d)
        j_cnt = jobs_failed_by_date.get(key, 0)
        t_cnt = takes_failed_by_date.get(key, 0)
        errors_by_day.append({
            "date": key,
            "jobs_failed": j_cnt,
            "takes_failed": t_cnt,
            "total": j_cnt + t_cnt,
        })

    return {
        "window_days": window_days,
        "jobs_failed_by_error": jobs_failed_by_error,
        "takes_failed_by_error": takes_failed_by_error,
        "combined": {code: data["job"] + data["take"] for code, data in combined.items()},
        "errors_by_day": errors_by_day,
    }


@router.get("/telemetry/history")
def telemetry_history(db: Session = Depends(get_db), window_days: int = Query(7, ge=1)):
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=window_days)
    day_j = func.date(Job.created_at)
    q_jobs = (
        db.query(
            day_j.label("date"),
            func.count(Job.job_id).label("jobs_total"),
            func.sum(case((Job.status == "SUCCEEDED", 1), else_=0)).label("jobs_succeeded"),
            func.sum(case((Job.status == "FAILED", 1), else_=0)).label("jobs_failed"),
            func.count(func.distinct(Job.user_id)).label("job_users"),
        )
        .filter(Job.created_at >= since)
        .group_by(day_j)
        .order_by(day_j)
    )
    jobs_rows = q_jobs.all()
    by_date = {
        str(r.date): {
            "jobs_total": r.jobs_total or 0,
            "jobs_succeeded": r.jobs_succeeded or 0,
            "jobs_failed": r.jobs_failed or 0,
        }
        for r in jobs_rows
    }
    job_user_pairs = (
        db.query(func.date(Job.created_at).label("date"), Job.user_id)
        .filter(Job.created_at >= since, Job.user_id.isnot(None))
        .distinct()
        .all()
    )
    take_user_pairs = (
        db.query(func.date(Take.created_at).label("date"), Take.user_id)
        .filter(Take.created_at >= since, Take.user_id.isnot(None))
        .distinct()
        .all()
    )
    users_by_date: dict[str, set[str]] = {}
    for d, uid in job_user_pairs:
        if uid:
            users_by_date.setdefault(str(d), set()).add(uid)
    for d, uid in take_user_pairs:
        if uid:
            users_by_date.setdefault(str(d), set()).add(uid)
    takes_by_date = (
        db.query(func.date(Take.created_at).label("date"), func.count(Take.id).label("cnt"))
        .filter(Take.created_at >= since)
        .group_by(func.date(Take.created_at))
        .all()
    )
    takes_by_date_map = {str(r.date): r.cnt for r in takes_by_date}
    history = []
    for i in range(window_days):
        d = (now - timedelta(days=window_days - 1 - i)).date()
        key = str(d)
        row = by_date.get(key, {"jobs_total": 0, "jobs_succeeded": 0, "jobs_failed": 0})
        active_users = len(users_by_date.get(key, set()))
        history.append({
            "date": key,
            "jobs_total": row["jobs_total"],
            "jobs_succeeded": row["jobs_succeeded"],
            "jobs_failed": row["jobs_failed"],
            "active_users": active_users,
            "takes_total": takes_by_date_map.get(key, 0),
        })
    return {"window_days": window_days, "history": history}


def _active_user_ids_in_period(db: Session, since: datetime) -> set[str]:
    """Уникальные user_id, у которых есть хотя бы один Job или Take за период (основной поток — Take)."""
    job_users = {
        r[0] for r in db.query(Job.user_id).filter(Job.created_at >= since).distinct().all()
        if r[0]
    }
    take_users = {
        r[0] for r in db.query(Take.user_id).filter(Take.created_at >= since).distinct().all()
        if r[0]
    }
    return job_users | take_users


@router.get("/telemetry/product-metrics")
def telemetry_product_metrics(db: Session = Depends(get_db), window_days: int = Query(7, ge=1)):
    now = datetime.now(timezone.utc)
    since_1d = now - timedelta(days=1)
    since_7d = now - timedelta(days=7)
    since_30d = now - timedelta(days=30)

    dau = len(_active_user_ids_in_period(db, since_1d))
    wau = len(_active_user_ids_in_period(db, since_7d))
    mau = len(_active_user_ids_in_period(db, since_30d))
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

    # Распределение пользователей по числу задач (Job) за окно — для графика Engagement
    jobs_per_user_q = (
        db.query(Job.user_id, func.count(Job.job_id).label("cnt"))
        .filter(Job.created_at >= since_window, Job.user_id.isnot(None))
        .group_by(Job.user_id)
    )
    dist_1 = dist_2_5 = dist_6_10 = dist_11_20 = dist_21_plus = 0
    for _uid, cnt in jobs_per_user_q.all():
        if cnt >= 21:
            dist_21_plus += 1
        elif cnt >= 11:
            dist_11_20 += 1
        elif cnt >= 6:
            dist_6_10 += 1
        elif cnt >= 2:
            dist_2_5 += 1
        else:
            dist_1 += 1
    jobs_per_user_distribution = {
        "1": dist_1,
        "2_5": dist_2_5,
        "6_10": dist_6_10,
        "11_20": dist_11_20,
        "21_plus": dist_21_plus,
    }

    # Ответ плоский, чтобы фронт мог использовать productMetrics.dau без .metrics
    return {
        "window_days": window_days,
        "dau": dau,
        "wau": wau,
        "mau": mau,
        "stickiness_pct": stickiness_pct,
        "funnel_counts": funnel_counts,
        "share_trial_purchases": share_trial_purchases,
        "avg_stars_per_pay_success": avg_stars_per_pay_success,
        "trial_purchases_count": trial_purchases,
        "total_pay_success_count": total_pay_success,
        "jobs_per_user_distribution": jobs_per_user_distribution,
    }


# ---------- Product analytics (product_events) ----------
FUNNEL_EVENT_NAMES = [
    "bot_started",
    "photo_uploaded",
    "take_preview_ready",
    "favorite_selected",
    "paywall_viewed",
    "pay_initiated",
    "pay_success",
    "hd_delivered",
]


@router.get("/telemetry/product-funnel")
def telemetry_product_funnel(
    db: Session = Depends(get_db),
    window_days: int = Query(7, ge=1, le=90),
):
    """Funnel counts from product_events (for product analytics dashboard)."""
    since = datetime.now(timezone.utc) - timedelta(days=window_days)
    rows = (
        db.query(ProductEvent.event_name, func.count(ProductEvent.id))
        .filter(ProductEvent.timestamp >= since, ProductEvent.event_name.in_(FUNNEL_EVENT_NAMES))
        .group_by(ProductEvent.event_name)
        .all()
    )
    funnel_counts = {name: 0 for name in FUNNEL_EVENT_NAMES}
    for name, cnt in rows:
        funnel_counts[name] = cnt
    return {"window_days": window_days, "funnel_counts": funnel_counts}


@router.get("/telemetry/product-metrics-v2")
def telemetry_product_metrics_v2(
    db: Session = Depends(get_db),
    window_days: int = Query(7, ge=1, le=90),
):
    """Calculated product metrics from product_events: preview_to_pay, hit_rate, AOV, etc."""
    since = datetime.now(timezone.utc) - timedelta(days=window_days)
    # Counts
    take_preview = db.query(func.count(ProductEvent.id)).filter(
        ProductEvent.event_name == "take_preview_ready", ProductEvent.timestamp >= since
    ).scalar() or 0
    pay_success_count = db.query(func.count(ProductEvent.id)).filter(
        ProductEvent.event_name == "pay_success", ProductEvent.timestamp >= since
    ).scalar() or 0
    # Preview -> Pay conversion
    preview_to_pay = round((pay_success_count / take_preview * 100), 1) if take_preview else 0.0
    # Sessions with favorite vs with preview (Hit Rate)
    sessions_with_preview = db.query(func.count(func.distinct(ProductEvent.session_id))).filter(
        ProductEvent.event_name == "take_preview_ready",
        ProductEvent.timestamp >= since,
        ProductEvent.session_id.isnot(None),
    ).scalar() or 0
    sessions_with_favorite = db.query(func.count(func.distinct(ProductEvent.session_id))).filter(
        ProductEvent.event_name == "favorite_selected",
        ProductEvent.timestamp >= since,
        ProductEvent.session_id.isnot(None),
    ).scalar() or 0
    hit_rate = round((sessions_with_favorite / sessions_with_preview * 100), 1) if sessions_with_preview else 0.0
    # Revenue from pay_success (properties.price in stars)
    pay_events = (
        db.query(ProductEvent.properties)
        .filter(ProductEvent.event_name == "pay_success", ProductEvent.timestamp >= since)
        .all()
    )
    def _safe_price(props: dict | None) -> int:
        try:
            return int(float((props or {}).get("price", 0) or 0))
        except (TypeError, ValueError):
            return 0
    total_stars = sum(_safe_price(p[0]) for p in pay_events)
    aov_stars = round(total_stars / pay_success_count, 1) if pay_success_count else 0.0
    # Likeness: generation_likeness_feedback with likeness=yes
    likeness_events = (
        db.query(ProductEvent.properties)
        .filter(
            ProductEvent.event_name == "generation_likeness_feedback",
            ProductEvent.timestamp >= since,
        )
        .all()
    )
    total_likeness = len(likeness_events)
    likeness_yes = sum(1 for p in likeness_events if (p[0] or {}).get("likeness") == "yes")
    likeness_score = round((likeness_yes / total_likeness * 100), 1) if total_likeness else 0.0
    # Repeat purchase: users with 2+ pay_success
    pay_per_user = (
        db.query(ProductEvent.user_id, func.count(ProductEvent.id))
        .filter(ProductEvent.event_name == "pay_success", ProductEvent.timestamp >= since)
        .group_by(ProductEvent.user_id)
        .all()
    )
    paying_users = len(pay_per_user)
    users_2plus = sum(1 for _u, c in pay_per_user if c >= 2)
    repeat_purchase_rate = round((users_2plus / paying_users * 100), 1) if paying_users else 0.0
    # Unique users (bot_started) and paying users
    users_started = db.query(func.count(func.distinct(ProductEvent.user_id))).filter(
        ProductEvent.event_name == "bot_started", ProductEvent.timestamp >= since
    ).scalar() or 0
    return {
        "window_days": window_days,
        "preview_to_pay_pct": preview_to_pay,
        "hit_rate_pct": hit_rate,
        "aov_stars": aov_stars,
        "total_stars": total_stars,
        "pay_success_count": pay_success_count,
        "take_preview_ready_count": take_preview,
        "sessions_with_preview": sessions_with_preview,
        "sessions_with_favorite": sessions_with_favorite,
        "likeness_score_pct": likeness_score,
        "total_likeness_feedback": total_likeness,
        "repeat_purchase_rate_pct": repeat_purchase_rate,
        "paying_users": paying_users,
        "users_started": users_started,
    }


@router.get("/telemetry/revenue")
def telemetry_revenue(
    db: Session = Depends(get_db),
    window_days: int = Query(30, ge=1, le=90),
):
    """Revenue by pack and by source from product_events pay_success."""
    since = datetime.now(timezone.utc) - timedelta(days=window_days)
    events = (
        db.query(ProductEvent.pack_id, ProductEvent.source, ProductEvent.properties)
        .filter(ProductEvent.event_name == "pay_success", ProductEvent.timestamp >= since)
        .all()
    )
    by_pack: dict[str, int] = {}
    by_source: dict[str, int] = {}
    total_stars = 0
    def _safe_price(p: dict | None) -> int:
        try:
            return int(float((p or {}).get("price", 0) or 0))
        except (TypeError, ValueError):
            return 0
    for pack_id, source, props in events:
        price = _safe_price(props)
        total_stars += price
        pack_key = pack_id or "unknown"
        by_pack[pack_key] = by_pack.get(pack_key, 0) + price
        src_key = source or "organic"
        by_source[src_key] = by_source.get(src_key, 0) + price
    rate = getattr(app_settings, "star_to_rub", 1.3)
    return {
        "window_days": window_days,
        "total_stars": total_stars,
        "revenue_rub_approx": round(total_stars * rate, 2),
        "by_pack": by_pack,
        "by_source": by_source,
    }


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
THEME_EDIT_FIELDS = {"name", "emoji", "order_index", "enabled", "target_audiences"}


def _theme_to_item(theme: Theme) -> dict:
    audiences = getattr(theme, "target_audiences", None)
    return {
        "id": theme.id,
        "name": theme.name,
        "emoji": theme.emoji or "",
        "order_index": theme.order_index,
        "enabled": theme.enabled,
        "target_audiences": normalize_target_audiences(audiences),
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


def _normalize_theme_target_audiences(value) -> list:
    """Валидация: только women, men, couples; минимум один."""
    normalized = normalize_target_audiences(value)
    allowed = [x for x in normalized if x in AUDIENCE_CHOICES]
    return allowed if allowed else ["women"]


@router.post("/themes")
def admin_themes_post(payload: dict = Body(...), db: Session = Depends(get_db)):
    svc = ThemeService(db)
    data = {k: v for k, v in payload.items() if k in THEME_EDIT_FIELDS}
    data.setdefault("emoji", "")
    data.setdefault("order_index", 0)
    data.setdefault("enabled", True)
    if "target_audiences" in data:
        data["target_audiences"] = _normalize_theme_target_audiences(data["target_audiences"])
    else:
        data.setdefault("target_audiences", ["women"])
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
    if "target_audiences" in data:
        data["target_audiences"] = _normalize_theme_target_audiences(data["target_audiences"])
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
    "max_images", "enabled", "order_index", "theme_id", "target_audiences",
    "prompt_sections", "prompt_model", "prompt_size", "prompt_format", "prompt_temperature", "prompt_seed", "prompt_image_size_tier",
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
        "target_audiences": normalize_target_audiences(getattr(t, "target_audiences", None)),
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
        "target_audiences": normalize_target_audiences(getattr(t, "target_audiences", None)),
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


@router.get("/trends/analytics")
def admin_trends_analytics(
    db: Session = Depends(get_db),
    window_days: int = Query(30, ge=1, le=365),
):
    """Аналитика по всем трендам: сколько успешно сгенерировано, сколько с ошибкой/не доставлено."""
    since = datetime.now(timezone.utc) - timedelta(days=window_days)
    svc = TrendService(db)
    all_trends = svc.list_all()
    trend_ids = [t.id for t in all_trends]
    # Job по trend_id за окно
    job_stats = (
        db.query(
            Job.trend_id,
            func.count(Job.job_id).label("total"),
            func.sum(case((Job.status == "SUCCEEDED", 1), else_=0)).label("succeeded"),
            func.sum(case((Job.status.in_(["FAILED", "ERROR"]), 1), else_=0)).label("failed"),
        )
        .filter(Job.trend_id.in_(trend_ids), Job.created_at >= since)
        .group_by(Job.trend_id)
        .all()
    )
    job_by_trend = {
        r.trend_id: {"total": r.total or 0, "succeeded": r.succeeded or 0, "failed": r.failed or 0}
        for r in job_stats
    }
    # Take по trend_id за окно
    take_stats = (
        db.query(
            Take.trend_id,
            func.count(Take.id).label("total"),
            func.sum(case((Take.status.in_(["ready", "partial_fail"]), 1), else_=0)).label("succeeded"),
            func.sum(case((Take.status == "failed", 1), else_=0)).label("failed"),
        )
        .filter(Take.trend_id.in_(trend_ids), Take.created_at >= since)
        .group_by(Take.trend_id)
        .all()
    )
    take_by_trend = {
        r.trend_id: {"total": r.total or 0, "succeeded": r.succeeded or 0, "failed": r.failed or 0}
        for r in take_stats
    }
    items = []
    for t in all_trends:
        j = job_by_trend.get(t.id, {"total": 0, "succeeded": 0, "failed": 0})
        tk = take_by_trend.get(t.id, {"total": 0, "succeeded": 0, "failed": 0})
        items.append({
            "trend_id": t.id,
            "name": t.name or t.id,
            "emoji": t.emoji or "",
            "theme_id": t.theme_id,
            "jobs_total": j["total"],
            "jobs_succeeded": j["succeeded"],
            "jobs_failed": j["failed"],
            "takes_total": tk["total"],
            "takes_succeeded": tk["succeeded"],
            "takes_failed": tk["failed"],
        })
    return {"window_days": window_days, "items": items}


@router.get("/trends/{trend_id}")
def admin_trends_get(trend_id: str, db: Session = Depends(get_db)):
    svc = TrendService(db)
    trend = svc.get(trend_id)
    if not trend:
        raise HTTPException(404, "Trend not found")
    return _trend_to_detail(trend)


def _normalize_trend_payload(data: dict) -> dict:
    """Нормализуем theme_id и target_audiences."""
    if "theme_id" in data and (data["theme_id"] is None or data["theme_id"] == ""):
        data = {**data, "theme_id": None}
    if "target_audiences" in data:
        data["target_audiences"] = _normalize_theme_target_audiences(data["target_audiences"])
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
    effective = gs.get_effective(profile="preview")
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


# ---------- Trend posts (автопостер в канал) ----------
def _render_poster_caption(
    template: str,
    name: str,
    emoji: str,
    description: str,
    deeplink: str,
    theme_name: str = "",
    theme_emoji: str = "",
) -> str:
    """Подставляет в шаблон {name}, {emoji}, {description}, {theme}, {theme_emoji}; ссылку в шаблон не вставляем — кнопка отдельно."""
    t = template or ""
    t = t.replace("{name}", name or "").replace("{emoji}", emoji or "").replace("{description}", description or "")
    t = t.replace("{theme}", theme_name or "").replace("{theme_emoji}", theme_emoji or "")
    return t.strip()


@router.get("/trend-posts")
def trend_posts_list(
    db: Session = Depends(get_db),
    status: str | None = Query(None, description="draft | sent | deleted"),
):
    """Список публикаций трендов (с данными тренда)."""
    if status and status not in ("draft", "sent", "deleted"):
        raise HTTPException(400, "status must be one of: draft, sent, deleted")
    q = db.query(TrendPost).join(Trend, TrendPost.trend_id == Trend.id)
    if status:
        q = q.filter(TrendPost.status == status)
    q = q.order_by(TrendPost.sent_at.desc().nulls_last(), TrendPost.created_at.desc())
    posts = q.all()
    ps = db.query(PosterSettings).filter(PosterSettings.id == 1).one_or_none()
    db_bot = (getattr(ps, "poster_bot_username", None) or "").strip() if ps else ""
    env_bot = (getattr(app_settings, "telegram_bot_username", None) or "").strip()
    bot_username = (db_bot or env_bot).lstrip("@")
    items = []
    for p in posts:
        t = p.trend
        deeplink = f"https://t.me/{bot_username}?start=trend_{p.trend_id}" if bot_username else None
        items.append({
            "id": p.id,
            "trend_id": p.trend_id,
            "trend_name": t.name if t else None,
            "trend_emoji": t.emoji if t else None,
            "channel_id": p.channel_id,
            "caption": p.caption,
            "telegram_message_id": p.telegram_message_id,
            "status": p.status,
            "sent_at": p.sent_at.isoformat() if p.sent_at else None,
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "updated_at": p.updated_at.isoformat() if p.updated_at else None,
            "deeplink": deeplink,
        })
    return {"items": items}


@router.get("/trend-posts/unpublished")
def trend_posts_unpublished(db: Session = Depends(get_db)):
    """Тренды (enabled), у которых нет отправленной публикации (status=sent). С темами для группировки по блокам."""
    rows = db.query(TrendPost.trend_id).filter(TrendPost.status == "sent").distinct().all()
    sent_trend_ids = {row[0] for row in rows}
    all_trends = (
        db.query(Trend)
        .options(joinedload(Trend.theme))
        .outerjoin(Theme, Trend.theme_id == Theme.id)
        .order_by(Theme.order_index.asc().nulls_last(), Trend.order_index.asc())
        .all()
    )
    ps = db.query(PosterSettings).filter(PosterSettings.id == 1).one_or_none()
    db_bot = (getattr(ps, "poster_bot_username", None) or "").strip() if ps else ""
    env_bot = (getattr(app_settings, "telegram_bot_username", None) or "").strip()
    bot_username = (db_bot or env_bot).lstrip("@")
    unpublished = []
    for t in all_trends:
        if not t.enabled or t.id in sent_trend_ids:
            continue
        example_path = _resolve_trend_media_path(t.example_image_path, t.id, "_example")
        deeplink = f"https://t.me/{bot_username}?start=trend_{t.id}" if bot_username else None
        theme = getattr(t, "theme", None)
        theme_order = theme.order_index if theme else 9999
        theme_name = (theme.name or "Без тематики") if theme else "Без тематики"
        theme_emoji = (theme.emoji or "") if theme else ""
        unpublished.append({
            "id": t.id,
            "name": t.name,
            "emoji": t.emoji,
            "description": t.description or "",
            "has_example": example_path is not None,
            "deeplink": deeplink,
            "theme_id": t.theme_id,
            "theme_name": theme_name,
            "theme_emoji": theme_emoji,
            "theme_order_index": theme_order,
        })
    return {"items": unpublished}


@router.post("/trend-posts/preview")
def trend_posts_preview(
    payload: dict = Body(...),
    db: Session = Depends(get_db),
):
    """Рендер подписи по шаблону. Возвращает caption и признак наличия картинки."""
    trend_id = payload.get("trend_id")
    caption_template = payload.get("caption") or payload.get("caption_template") or ""
    if not trend_id:
        raise HTTPException(400, "trend_id required")
    trend = db.query(Trend).options(joinedload(Trend.theme)).filter(Trend.id == trend_id).one_or_none()
    if not trend:
        raise HTTPException(404, "Trend not found")
    # Если caption не передан — берём дефолтный шаблон из poster_settings
    if not caption_template.strip():
        ps = db.query(PosterSettings).filter(PosterSettings.id == 1).one_or_none()
        caption_template = (ps.poster_default_template if ps else "") or "{emoji} {name}\n\n{description}\n\nПопробовать тут:"
    deeplink = ""
    ps_bot = db.query(PosterSettings).filter(PosterSettings.id == 1).one_or_none()
    db_bot = (getattr(ps_bot, "poster_bot_username", None) or "").strip() if ps_bot else ""
    env_bot = (getattr(app_settings, "telegram_bot_username", None) or "").strip()
    bot_username = (db_bot or env_bot).lstrip("@")
    if bot_username:
        deeplink = f"https://t.me/{bot_username}?start=trend_{trend_id}"
    theme = getattr(trend, "theme", None)
    theme_name = (theme.name or "") if theme else ""
    theme_emoji = (theme.emoji or "") if theme else ""
    caption = _render_poster_caption(
        caption_template,
        trend.name or "",
        trend.emoji or "",
        trend.description or "",
        deeplink,
        theme_name=theme_name,
        theme_emoji=theme_emoji,
    )
    # В превью тоже не добавляем URL в текст — только кнопка будет с ссылкой
    example_path = _resolve_trend_media_path(trend.example_image_path, trend_id, "_example")
    return {
        "trend_id": trend_id,
        "caption": caption,
        "has_example": example_path is not None,
        "deeplink": deeplink,
    }


@router.post("/trend-posts/publish")
def trend_posts_publish(
    payload: dict = Body(...),
    db: Session = Depends(get_db),
):
    """Отправить пост в канал: фото + подпись + кнопка «Попробовать»."""
    trend_id = payload.get("trend_id") or payload.get("trendId")
    caption = (payload.get("caption") or "").strip()
    if not trend_id:
        logger.warning("trend_posts_publish: trend_id missing in payload")
        raise HTTPException(400, "trend_id required")
    # Канал: сначала из настроек в БД, иначе из env
    ps_channel = ""
    ps = db.query(PosterSettings).filter(PosterSettings.id == 1).one_or_none()
    if ps and (ps.poster_channel_id or "").strip():
        ps_channel = (ps.poster_channel_id or "").strip()
    env_channel = (getattr(app_settings, "poster_channel_id", None) or "").strip()
    channel_id = ps_channel or env_channel
    if not channel_id:
        logger.warning("trend_posts_publish: channel not set; set in Admin → Автопостер → Настройки or POSTER_CHANNEL_ID in .env")
        raise HTTPException(
            400,
            "Не задан канал для автопостера. Укажите канал в Настройках (Автопостер → Настройки → ID канала) или задайте POSTER_CHANNEL_ID в .env и перезапустите API.",
        )
    # Telegram: для канала по username нужен @ (напр. @nanobanana_al); числовой ID — как есть (напр. -1003808081075)
    if not channel_id.lstrip("-").isdigit() and not channel_id.startswith("@"):
        channel_id = "@" + channel_id
    trend = db.query(Trend).options(joinedload(Trend.theme)).filter(Trend.id == trend_id).one_or_none()
    if not trend:
        raise HTTPException(404, "Trend not found")
    example_path = _resolve_trend_media_path(trend.example_image_path, trend_id, "_example")
    if not example_path or not os.path.isfile(example_path):
        examples_dir = _get_trend_examples_dir()
        logger.warning(
            "trend_posts_publish: example image not found for trend_id=%s, example_image_path=%s, resolved=%s, examples_dir=%s",
            trend_id,
            getattr(trend, "example_image_path", None),
            example_path,
            examples_dir,
        )
        raise HTTPException(
            400,
            "У тренда нет картинки-примера. Загрузите пример в карточке тренда (Тренды → редактировать тренд → загрузить пример). Каталог примеров на сервере: " + examples_dir,
        )
    # Username бота для диплинка: сначала из настроек БД (ps уже загружен выше), иначе из env (без @ в значении)
    db_bot = (getattr(ps, "poster_bot_username", None) or "").strip() if ps else ""
    env_bot = (getattr(app_settings, "telegram_bot_username", None) or "").strip()
    bot_username = (db_bot or env_bot).lstrip("@")
    deeplink = f"https://t.me/{bot_username}?start=trend_{trend_id}" if bot_username else ""
    if not deeplink:
        logger.warning("trend_posts_publish: bot username not set; no deeplink/button. Set in Настройки → Username бота or TELEGRAM_BOT_USERNAME in .env")
    # Всегда рендерим подпись из шаблона на сервере (подставляем name, emoji, description, theme, theme_emoji).
    # Игнорируем caption из payload — фронт может передать сырой шаблон с плейсхолдерами.
    ps = db.query(PosterSettings).filter(PosterSettings.id == 1).one_or_none()
    template = (ps.poster_default_template if ps else "") or "{emoji} {name}\n\n{description}\n\nПопробовать тут:"
    theme = getattr(trend, "theme", None)
    theme_name = (theme.name or "") if theme else ""
    theme_emoji = (theme.emoji or "") if theme else ""
    caption = _render_poster_caption(
        template,
        trend.name or "",
        trend.emoji or "",
        trend.description or "",
        deeplink,
        theme_name=theme_name,
        theme_emoji=theme_emoji,
    )
    # Диплинк не добавляем в текст подписи — только в инлайн-кнопку под постом
    if len(caption) > 1024:
        logger.warning("trend_posts_publish: caption length %s > 1024 for trend_id=%s", len(caption), trend_id)
        raise HTTPException(400, "Подпись слишком длинная (Telegram: макс. 1024 символа)")
    reply_markup = None
    if deeplink:
        btn_text = "Попробовать"
        if ps := db.query(PosterSettings).filter(PosterSettings.id == 1).one_or_none():
            if (t := (ps.poster_button_text or "").strip()):
                btn_text = t[:64]  # Telegram: label max 64 chars
        reply_markup = {"inline_keyboard": [[{"text": btn_text or "Попробовать", "url": deeplink}]]}
    telegram = TelegramClient()
    try:
        result = telegram.send_photo(
            channel_id,
            example_path,
            caption=caption,
            reply_markup=reply_markup,
            parse_mode="HTML",
        )
    except Exception as e:
        raise HTTPException(502, f"Ошибка отправки в Telegram: {e}")
    finally:
        telegram.close()
    message_id = (result.get("result") or {}).get("message_id") if isinstance(result, dict) else None
    # Создаём или обновляем запись
    existing = db.query(TrendPost).filter(TrendPost.trend_id == trend_id, TrendPost.status == "sent").first()
    if existing:
        existing.caption = caption
        existing.telegram_message_id = message_id
        existing.sent_at = datetime.now(timezone.utc)
        existing.updated_at = datetime.now(timezone.utc)
        db.add(existing)
        db.commit()
        db.refresh(existing)
        post = existing
    else:
        post = TrendPost(
            trend_id=trend_id,
            channel_id=channel_id,
            caption=caption,
            telegram_message_id=message_id,
            status="sent",
            sent_at=datetime.now(timezone.utc),
        )
        db.add(post)
        db.commit()
        db.refresh(post)
    return {
        "id": post.id,
        "trend_id": post.trend_id,
        "status": post.status,
        "telegram_message_id": post.telegram_message_id,
        "sent_at": post.sent_at.isoformat() if post.sent_at else None,
    }


@router.delete("/trend-posts/{post_id}")
def trend_posts_delete(post_id: str, db: Session = Depends(get_db)):
    """Удалить пост из канала и пометить запись как deleted."""
    post = db.query(TrendPost).filter(TrendPost.id == post_id).one_or_none()
    if not post:
        raise HTTPException(404, "Post not found")
    channel_id = post.channel_id
    msg_id = post.telegram_message_id
    if channel_id and msg_id is not None:
        telegram = TelegramClient()
        try:
            telegram.delete_message(channel_id, msg_id)
        except Exception:
            pass
        finally:
            telegram.close()
    post.status = "deleted"
    post.telegram_message_id = None
    db.add(post)
    db.commit()
    db.refresh(post)
    return {"id": post.id, "status": post.status}


@router.get("/trend-posts/settings")
def trend_posts_settings_get(db: Session = Depends(get_db)):
    """Настройки автопостера: channel, bot_username, шаблон и текст кнопки из БД или config."""
    ps = db.query(PosterSettings).filter(PosterSettings.id == 1).one_or_none()
    env_channel = (getattr(app_settings, "poster_channel_id", None) or "").strip()
    db_channel = (ps.poster_channel_id or "").strip() if ps else ""
    channel_id = db_channel or env_channel
    env_bot = (getattr(app_settings, "telegram_bot_username", None) or "").strip()
    db_bot = (getattr(ps, "poster_bot_username", None) or "").strip() if ps else ""
    poster_bot_username = db_bot or env_bot
    template = ps.poster_default_template if ps else "{emoji} {name}\n\n{description}\n\nПопробовать тут:"
    button_text = (ps.poster_button_text or "Попробовать").strip() or "Попробовать" if ps else "Попробовать"
    return {
        "poster_channel_id": channel_id,
        "poster_channel_id_editable": db_channel or "",
        "poster_bot_username": poster_bot_username,
        "poster_default_template": template or "",
        "poster_button_text": button_text,
    }


@router.put("/trend-posts/settings")
def trend_posts_settings_put(
    payload: dict = Body(...),
    db: Session = Depends(get_db),
):
    """Обновить канал, username бота, шаблон подписи и/или текст инлайн-кнопки."""
    template = (payload.get("poster_default_template") or "").strip()
    button_text = (payload.get("poster_button_text") or "").strip() or "Попробовать"
    channel_id = (payload.get("poster_channel_id") or "").strip()
    bot_username = (payload.get("poster_bot_username") or "").strip().lstrip("@")
    if len(button_text) > 64:
        raise HTTPException(400, "Текст инлайн-кнопки не более 64 символов (лимит Telegram)")
    ps = db.query(PosterSettings).filter(PosterSettings.id == 1).one_or_none()
    if not ps:
        ps = PosterSettings(
            id=1,
            poster_channel_id=channel_id or None,
            poster_bot_username=bot_username or None,
            poster_default_template=template or "",
            poster_button_text=button_text,
        )
        db.add(ps)
    else:
        if "poster_channel_id" in payload:
            ps.poster_channel_id = channel_id or None
        if "poster_bot_username" in payload:
            ps.poster_bot_username = bot_username or None
        if "poster_default_template" in payload:
            ps.poster_default_template = template or ""
        if "poster_button_text" in payload:
            ps.poster_button_text = button_text
        ps.updated_at = datetime.now(timezone.utc)
        db.add(ps)
    db.commit()
    db.refresh(ps)
    env_channel = (getattr(app_settings, "poster_channel_id", None) or "").strip()
    db_channel = (ps.poster_channel_id or "").strip()
    env_bot = (getattr(app_settings, "telegram_bot_username", None) or "").strip()
    db_bot = (getattr(ps, "poster_bot_username", None) or "").strip()
    return {
        "poster_channel_id": db_channel or env_channel,
        "poster_channel_id_editable": db_channel,
        "poster_bot_username": db_bot or env_bot,
        "poster_default_template": ps.poster_default_template,
        "poster_button_text": (ps.poster_button_text or "Попробовать").strip() or "Попробовать",
    }


# ---------- Audit ----------
@router.get("/audit")
def audit_list(
    db: Session = Depends(get_db),
    action: str | None = None,
    actor_type: str | None = None,
    entity_type: str | None = None,
    audience: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    search: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    q = db.query(AuditLog)
    if action:
        q = q.filter(AuditLog.action == action)
    if audience and audience.strip() in ("women", "men", "couples"):
        q = q.filter(AuditLog.payload["audience"].astext == audience.strip())
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

    actor_ids = {r.actor_id for r in rows if r.actor_type == "user" and r.actor_id}
    display_map: dict[str, str] = {}
    if actor_ids:
        users = (
            db.query(
                User.telegram_id,
                User.telegram_username,
                User.telegram_first_name,
                User.telegram_last_name,
            )
            .filter(User.telegram_id.in_(actor_ids))
            .all()
        )
        for u in users:
            if u.telegram_username:
                display_map[u.telegram_id] = f"@{u.telegram_username}"
            else:
                name = f"{u.telegram_first_name or ''} {u.telegram_last_name or ''}".strip()
                display_map[u.telegram_id] = name or u.telegram_id

    items = [
        {
            "id": r.id,
            "actor_type": r.actor_type,
            "actor_id": r.actor_id,
            "actor_display_name": display_map.get(r.actor_id) if r.actor_type == "user" and r.actor_id else None,
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


@router.get("/audit/analytics")
def audit_analytics(
    db: Session = Depends(get_db),
    date_from: str | None = None,
    date_to: str | None = None,
    action: str | None = None,
    actor_type: str | None = None,
    entity_type: str | None = None,
    audience: str | None = None,
):
    """Aggregations for audit log: events by day, by action, top actors (users)."""
    q = db.query(AuditLog)
    if action:
        q = q.filter(AuditLog.action == action)
    if actor_type:
        q = q.filter(AuditLog.actor_type == actor_type)
    if entity_type:
        q = q.filter(AuditLog.entity_type == entity_type)
    if audience and audience.strip() in ("women", "men", "couples"):
        q = q.filter(AuditLog.payload["audience"].astext == audience.strip())
    since: datetime | None = None
    until: datetime | None = None
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

    base_q = q

    events_by_day = (
        base_q.with_entities(
            func.date_trunc("day", AuditLog.created_at).label("day"),
            func.count(AuditLog.id).label("cnt"),
        )
        .group_by(func.date_trunc("day", AuditLog.created_at))
        .order_by(func.date_trunc("day", AuditLog.created_at))
        .all()
    )
    events_by_day_list = [
        {"date": d.day.isoformat() if d.day else None, "count": d.cnt}
        for d in events_by_day
    ]

    by_action_rows = (
        base_q.with_entities(AuditLog.action, func.count(AuditLog.id))
        .group_by(AuditLog.action)
        .all()
    )
    by_action = {r[0]: r[1] for r in by_action_rows}

    by_actor_type_rows = (
        base_q.with_entities(AuditLog.actor_type, func.count(AuditLog.id))
        .group_by(AuditLog.actor_type)
        .all()
    )
    by_actor_type = dict(by_actor_type_rows)

    top_actors_subq = (
        db.query(AuditLog.actor_id, func.count(AuditLog.id).label("cnt"))
        .filter(AuditLog.actor_type == "user", AuditLog.actor_id.isnot(None))
    )
    if since:
        top_actors_subq = top_actors_subq.filter(AuditLog.created_at >= since)
    if until:
        top_actors_subq = top_actors_subq.filter(AuditLog.created_at <= until)
    if action:
        top_actors_subq = top_actors_subq.filter(AuditLog.action == action)
    if entity_type:
        top_actors_subq = top_actors_subq.filter(AuditLog.entity_type == entity_type)
    if audience and audience.strip() in ("women", "men", "couples"):
        top_actors_subq = top_actors_subq.filter(
            AuditLog.payload["audience"].astext == audience.strip()
        )
    top_actors_subq = (
        top_actors_subq.group_by(AuditLog.actor_id)
        .order_by(func.count(AuditLog.id).desc())
        .limit(20)
        .all()
    )
    top_actor_ids = [r.actor_id for r in top_actors_subq]
    display_map: dict[str, str] = {}
    if top_actor_ids:
        users = (
            db.query(
                User.telegram_id,
                User.telegram_username,
                User.telegram_first_name,
                User.telegram_last_name,
            )
            .filter(User.telegram_id.in_(top_actor_ids))
            .all()
        )
        for u in users:
            if u.telegram_username:
                display_map[u.telegram_id] = f"@{u.telegram_username}"
            else:
                name = f"{u.telegram_first_name or ''} {u.telegram_last_name or ''}".strip()
                display_map[u.telegram_id] = name or u.telegram_id
    top_actors = [
        {
            "actor_id": r.actor_id,
            "actor_display_name": display_map.get(r.actor_id, r.actor_id),
            "count": r.cnt,
        }
        for r in top_actors_subq
    ]

    return {
        "events_by_day": events_by_day_list,
        "by_action": by_action,
        "by_actor_type": by_actor_type,
        "top_actors": top_actors,
    }


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
        user_display_name = None
        if u:
            if u.telegram_username:
                user_display_name = f"@{u.telegram_username}"
            else:
                name = f"{u.telegram_first_name or ''} {u.telegram_last_name or ''}".strip()
                user_display_name = name or u.telegram_id
        items.append({
            "job_id": j.job_id,
            "user_id": j.user_id,
            "telegram_id": u.telegram_id if u else None,
            "user_display_name": user_display_name,
            "trend_id": j.trend_id,
            "trend_name": t.name if t else None,
            "trend_emoji": t.emoji if t else None,
            "status": j.status,
            "is_preview": getattr(j, "is_preview", False),
            "reserved_tokens": j.reserved_tokens,
            "error_code": j.error_code,
            "created_at": j.created_at.isoformat() if j.created_at else None,
        })
    return {"items": items, "total": total, "page": page, "pages": (total + page_size - 1) // page_size}


@router.get("/jobs/analytics")
def jobs_analytics(
    db: Session = Depends(get_db),
    hours: int | None = Query(None, ge=1, le=720),
    date_from: str | None = None,
    date_to: str | None = None,
    trend_id: str | None = None,
    status: str | None = None,
):
    """Aggregations for jobs: by day, by status, by trend, top users."""
    q = db.query(Job)
    if trend_id:
        q = q.filter(Job.trend_id == trend_id)
    if status:
        q = q.filter(Job.status == status)
    since: datetime | None = None
    until: datetime | None = None
    if hours is not None:
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        q = q.filter(Job.created_at >= since)
    if date_from:
        try:
            since = datetime.fromisoformat(date_from.replace("Z", "+00:00"))
            q = q.filter(Job.created_at >= since)
        except (ValueError, TypeError):
            pass
    if date_to:
        try:
            until = datetime.fromisoformat(date_to.replace("Z", "+00:00"))
            q = q.filter(Job.created_at <= until)
        except (ValueError, TypeError):
            pass

    base_q = q

    jobs_by_day = (
        base_q.with_entities(
            func.date_trunc("day", Job.created_at).label("day"),
            func.count(Job.job_id).label("cnt"),
        )
        .group_by(func.date_trunc("day", Job.created_at))
        .order_by(func.date_trunc("day", Job.created_at))
        .all()
    )
    by_date_counts = {}
    for d in jobs_by_day:
        if d.day:
            key = d.day.date() if hasattr(d.day, "date") else d.day
            by_date_counts[str(key)] = d.cnt
    if since:
        # Заполняем все дни в окне нулями, чтобы график «Задачи по дням» всегда имел точки
        now_utc = datetime.now(timezone.utc)
        start_date = since.date() if hasattr(since, "date") else since
        end_date = (until.date() if until and hasattr(until, "date") else until) if until else now_utc.date()
        jobs_by_day_list = []
        d = start_date
        while d <= end_date:
            jobs_by_day_list.append({"date": str(d), "count": by_date_counts.get(str(d), 0)})
            d = d + timedelta(days=1)
        jobs_by_day_list.sort(key=lambda x: x["date"])
    else:
        jobs_by_day_list = [
            {"date": str(d.day.date() if hasattr(d.day, "date") else d.day), "count": d.cnt}
            for d in jobs_by_day
            if d.day
        ]
        jobs_by_day_list.sort(key=lambda x: x["date"])

    by_status_rows = (
        base_q.with_entities(Job.status, func.count(Job.job_id))
        .group_by(Job.status)
        .all()
    )
    by_status = {r[0]: r[1] for r in by_status_rows}
    # Чтобы график «По статусам» не был пустым при отсутствии задач — задаём нули для известных статусов
    for st in ("CREATED", "RUNNING", "SUCCEEDED", "FAILED", "ERROR"):
        if st not in by_status:
            by_status[st] = 0

    by_trend_rows = (
        base_q.with_entities(Job.trend_id, func.count(Job.job_id).label("cnt"))
        .group_by(Job.trend_id)
        .order_by(func.count(Job.job_id).desc())
        .limit(20)
        .all()
    )
    trend_ids_analytics = [r.trend_id for r in by_trend_rows]
    trends_map = {}
    if trend_ids_analytics:
        for t in db.query(Trend).filter(Trend.id.in_(trend_ids_analytics)).all():
            trends_map[t.id] = {"name": t.name, "emoji": t.emoji}
    by_trend = [
        {
            "trend_id": r.trend_id,
            "trend_name": trends_map.get(r.trend_id, {}).get("name", r.trend_id),
            "trend_emoji": trends_map.get(r.trend_id, {}).get("emoji"),
            "count": r.cnt,
        }
        for r in by_trend_rows
    ]

    top_users_subq = (
        db.query(Job.user_id, func.count(Job.job_id).label("cnt"))
        .filter(Job.user_id.isnot(None))
    )
    if since:
        top_users_subq = top_users_subq.filter(Job.created_at >= since)
    if until:
        top_users_subq = top_users_subq.filter(Job.created_at <= until)
    if trend_id:
        top_users_subq = top_users_subq.filter(Job.trend_id == trend_id)
    if status:
        top_users_subq = top_users_subq.filter(Job.status == status)
    top_users_subq = (
        top_users_subq.group_by(Job.user_id)
        .order_by(func.count(Job.job_id).desc())
        .limit(20)
        .all()
    )
    user_ids_analytics = [r.user_id for r in top_users_subq]
    users_map: dict[str, dict[str, Any]] = {}
    if user_ids_analytics:
        for u in (
            db.query(
                User.id,
                User.telegram_id,
                User.telegram_username,
                User.telegram_first_name,
                User.telegram_last_name,
            )
            .filter(User.id.in_(user_ids_analytics))
            .all()
        ):
            disp = u.telegram_username and f"@{u.telegram_username}" or (
                f"{u.telegram_first_name or ''} {u.telegram_last_name or ''}".strip() or u.telegram_id
            )
            users_map[u.id] = {"telegram_id": u.telegram_id, "user_display_name": disp}
    top_users = [
        {
            "user_id": r.user_id,
            "telegram_id": users_map.get(r.user_id, {}).get("telegram_id"),
            "user_display_name": users_map.get(r.user_id, {}).get("user_display_name", r.user_id),
            "count": r.cnt,
        }
        for r in top_users_subq
    ]

    return {
        "jobs_by_day": jobs_by_day_list,
        "by_status": by_status,
        "by_trend": by_trend,
        "top_users": top_users,
    }


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


# ===========================================
# Traffic sources & ad campaigns — deep links (?start=src_<slug>), budget, ROI
# ===========================================

@router.get("/bot-info")
def bot_info():
    """Bot username for generating deep links (t.me/username?start=src_...)."""
    username = (getattr(app_settings, "telegram_bot_username", None) or "").strip()
    return {"username": username or None}


@router.get("/traffic-sources")
def traffic_sources_list(db: Session = Depends(get_db), active_only: bool = Query(False)):
    """List traffic sources (channels/publics where we place links)."""
    q = db.query(TrafficSource)
    if active_only:
        q = q.filter(TrafficSource.is_active.is_(True))
    sources = q.order_by(TrafficSource.name).all()
    return [
        {
            "id": s.id,
            "slug": s.slug,
            "name": s.name,
            "url": s.url,
            "platform": s.platform,
            "is_active": s.is_active,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "updated_at": s.updated_at.isoformat() if s.updated_at else None,
        }
        for s in sources
    ]


class TrafficSourceCreate(BaseModel):
    slug: str
    name: str
    url: str | None = None
    platform: str = "other"


class TrafficSourceUpdate(BaseModel):
    name: str | None = None
    url: str | None = None
    is_active: bool | None = None


@router.post("/traffic-sources")
def traffic_sources_create(body: TrafficSourceCreate, db: Session = Depends(get_db)):
    """Create a traffic source. Slug: [a-zA-Z0-9_-], max 50 chars for start param headroom."""
    slug = (body.slug or "").strip()
    if not slug or len(slug) > 50:
        raise HTTPException(400, "slug required, max 50 characters")
    if not all(c.isalnum() or c in "_-" for c in slug):
        raise HTTPException(400, "slug must contain only letters, digits, underscore, hyphen")
    existing = db.query(TrafficSource).filter(TrafficSource.slug == slug).first()
    if existing:
        raise HTTPException(400, "slug already exists")
    source = TrafficSource(
        slug=slug,
        name=(body.name or "").strip() or slug,
        url=(body.url or "").strip() or None,
        platform=(body.platform or "other").strip().lower() or "other",
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    return {
        "id": source.id,
        "slug": source.slug,
        "name": source.name,
        "url": source.url,
        "platform": source.platform,
        "is_active": source.is_active,
        "created_at": source.created_at.isoformat() if source.created_at else None,
    }


@router.patch("/traffic-sources/{source_id}")
def traffic_sources_update(source_id: str, body: TrafficSourceUpdate, db: Session = Depends(get_db)):
    """Update traffic source."""
    source = db.query(TrafficSource).filter(TrafficSource.id == source_id).first()
    if not source:
        raise HTTPException(404, "Traffic source not found")
    if body.name is not None:
        source.name = body.name.strip() or source.name
    if body.url is not None:
        source.url = body.url.strip() or None
    if body.is_active is not None:
        source.is_active = body.is_active
    db.commit()
    db.refresh(source)
    return {
        "id": source.id,
        "slug": source.slug,
        "name": source.name,
        "url": source.url,
        "platform": source.platform,
        "is_active": source.is_active,
        "updated_at": source.updated_at.isoformat() if source.updated_at else None,
    }


@router.delete("/traffic-sources/{source_id}")
def traffic_sources_delete(source_id: str, db: Session = Depends(get_db)):
    """Soft-delete: set is_active=False."""
    source = db.query(TrafficSource).filter(TrafficSource.id == source_id).first()
    if not source:
        raise HTTPException(404, "Traffic source not found")
    source.is_active = False
    db.commit()
    return {"ok": True}


@router.get("/traffic-sources/stats")
def traffic_sources_stats(
    db: Session = Depends(get_db),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
):
    """Aggregate stats per traffic source for the period. Clicks from audit traffic_start, users/buyers/revenue from User+Payment."""
    df = None
    dt = None
    if date_from:
        try:
            df = datetime.fromisoformat(date_from.replace("Z", "+00:00")).date()
        except ValueError:
            pass
    if date_to:
        try:
            dt = datetime.fromisoformat(date_to.replace("Z", "+00:00")).date()
        except ValueError:
            pass

    # Clicks: count of traffic_start audit events (by payload->traffic_source)
    audit_base = db.query(AuditLog).filter(AuditLog.action == "traffic_start")
    if df is not None:
        audit_base = audit_base.filter(AuditLog.created_at >= datetime.combine(df, datetime.min.time()).replace(tzinfo=timezone.utc))
    if dt is not None:
        audit_base = audit_base.filter(AuditLog.created_at <= datetime.combine(dt, datetime.max.time()).replace(tzinfo=timezone.utc))

    clicks_subq = (
        db.query(
            AuditLog.payload["traffic_source"].astext.label("source"),
            func.count(AuditLog.id).label("clicks"),
        )
        .filter(AuditLog.action == "traffic_start")
    )
    if df is not None:
        clicks_subq = clicks_subq.filter(AuditLog.created_at >= datetime.combine(df, datetime.min.time()).replace(tzinfo=timezone.utc))
    if dt is not None:
        clicks_subq = clicks_subq.filter(AuditLog.created_at <= datetime.combine(dt, datetime.max.time()).replace(tzinfo=timezone.utc))
    clicks_subq = clicks_subq.group_by(AuditLog.payload["traffic_source"].astext)
    clicks_map = {row.source: row.clicks for row in clicks_subq.all()}

    # Users with traffic_source set (first-touch), new users in period, buyers, revenue
    sources = db.query(TrafficSource).filter(TrafficSource.is_active.is_(True)).all()
    result = []
    for s in sources:
        q_u = db.query(User).filter(User.traffic_source == s.slug)
        if df is not None:
            q_u = q_u.filter(User.created_at >= datetime.combine(df, datetime.min.time()).replace(tzinfo=timezone.utc))
        if dt is not None:
            q_u = q_u.filter(User.created_at <= datetime.combine(dt, datetime.max.time()).replace(tzinfo=timezone.utc))
        user_ids = [u.id for u in q_u.all()]
        new_users = len(user_ids)

        buyers = 0
        revenue_stars = 0
        if user_ids:
            buyers = db.query(func.count(func.distinct(Payment.user_id))).filter(
                Payment.user_id.in_(user_ids),
                Payment.status == "completed",
            ).scalar() or 0
            rev = db.query(func.coalesce(func.sum(Payment.stars_amount), 0)).filter(
                Payment.user_id.in_(user_ids),
                Payment.status == "completed",
            ).scalar() or 0
            revenue_stars = int(rev)

        clicks = clicks_map.get(s.slug, 0)
        revenue_rub = round(revenue_stars * STAR_RUB_RATE, 0)
        cr_pct = round(100.0 * buyers / new_users, 1) if new_users else 0
        result.append({
            "source_id": s.id,
            "slug": s.slug,
            "name": s.name,
            "platform": s.platform,
            "clicks": clicks,
            "new_users": new_users,
            "buyers": buyers,
            "revenue_stars": revenue_stars,
            "revenue_rub": revenue_rub,
            "conversion_rate_pct": cr_pct,
        })
    return {"sources": result, "date_from": date_from, "date_to": date_to}


@router.get("/traffic-sources/overview")
def traffic_sources_overview(
    db: Session = Depends(get_db),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
):
    """Overview totals for the period: total clicks, new users from traffic, conversion, revenue, and daily series for chart."""
    df = None
    dt = None
    if date_from:
        try:
            df = datetime.fromisoformat(date_from.replace("Z", "+00:00")).date()
        except ValueError:
            pass
    if date_to:
        try:
            dt = datetime.fromisoformat(date_to.replace("Z", "+00:00")).date()
        except ValueError:
            pass

    base_user = db.query(User).filter(User.traffic_source.isnot(None))
    if df is not None:
        base_user = base_user.filter(User.created_at >= datetime.combine(df, datetime.min.time()).replace(tzinfo=timezone.utc))
    if dt is not None:
        base_user = base_user.filter(User.created_at <= datetime.combine(dt, datetime.max.time()).replace(tzinfo=timezone.utc))
    user_ids = [u.id for u in base_user.all()]
    new_users = len(user_ids)

    total_clicks = db.query(func.count(AuditLog.id)).filter(AuditLog.action == "traffic_start")
    if df is not None:
        total_clicks = total_clicks.filter(AuditLog.created_at >= datetime.combine(df, datetime.min.time()).replace(tzinfo=timezone.utc))
    if dt is not None:
        total_clicks = total_clicks.filter(AuditLog.created_at <= datetime.combine(dt, datetime.max.time()).replace(tzinfo=timezone.utc))
    total_clicks = total_clicks.scalar() or 0

    buyers = 0
    revenue_stars = 0
    if user_ids:
        buyers = db.query(func.count(func.distinct(Payment.user_id))).filter(
            Payment.user_id.in_(user_ids), Payment.status == "completed"
        ).scalar() or 0
        rev = db.query(func.coalesce(func.sum(Payment.stars_amount), 0)).filter(
            Payment.user_id.in_(user_ids), Payment.status == "completed"
        ).scalar() or 0
        revenue_stars = int(rev)
    revenue_rub = round(revenue_stars * STAR_RUB_RATE, 0)
    cr_pct = round(100.0 * buyers / new_users, 1) if new_users else 0

    # Daily series: clicks and purchases by day
    daily_q = db.query(
        func.date_trunc("day", AuditLog.created_at).label("day"),
        func.count(AuditLog.id).label("clicks"),
    ).filter(AuditLog.action == "traffic_start")
    if df is not None:
        daily_q = daily_q.filter(AuditLog.created_at >= datetime.combine(df, datetime.min.time()).replace(tzinfo=timezone.utc))
    if dt is not None:
        daily_q = daily_q.filter(AuditLog.created_at <= datetime.combine(dt, datetime.max.time()).replace(tzinfo=timezone.utc))
    daily_q = daily_q.group_by(func.date_trunc("day", AuditLog.created_at)).order_by(func.date_trunc("day", AuditLog.created_at))
    daily_clicks = [{"date": (r.day.date().isoformat() if hasattr(r.day, "date") else str(r.day)), "clicks": r.clicks} for r in daily_q.all()]

    if user_ids:
        daily_payments_q = db.query(
            func.date(Payment.created_at).label("day"),
            func.count(Payment.id).label("payments"),
            func.coalesce(func.sum(Payment.stars_amount), 0).label("stars"),
        ).filter(Payment.status == "completed", Payment.user_id.in_(user_ids))
        if df is not None:
            daily_payments_q = daily_payments_q.filter(Payment.created_at >= datetime.combine(df, datetime.min.time()).replace(tzinfo=timezone.utc))
        if dt is not None:
            daily_payments_q = daily_payments_q.filter(Payment.created_at <= datetime.combine(dt, datetime.max.time()).replace(tzinfo=timezone.utc))
        daily_payments_q = daily_payments_q.group_by(func.date(Payment.created_at)).order_by(func.date(Payment.created_at))
        daily_purchases = [{"date": (r.day.isoformat() if hasattr(r.day, "isoformat") else str(r.day)), "payments": r.payments, "stars": int(r.stars)} for r in daily_payments_q.all()]
    else:
        daily_purchases = []

    return {
        "total_clicks": total_clicks,
        "new_users": new_users,
        "buyers": buyers,
        "revenue_stars": revenue_stars,
        "revenue_rub": revenue_rub,
        "conversion_rate_pct": cr_pct,
        "daily_clicks": daily_clicks,
        "daily_purchases": daily_purchases,
        "date_from": date_from,
        "date_to": date_to,
    }


@router.get("/traffic-sources/{slug}/funnel")
def traffic_source_funnel(
    slug: str,
    db: Session = Depends(get_db),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
):
    """Funnel for one source: starts -> subscribed -> first_generation -> first_purchase -> repeat_purchase."""
    df = None
    dt = None
    if date_from:
        try:
            df = datetime.fromisoformat(date_from.replace("Z", "+00:00")).date()
        except ValueError:
            pass
    if date_to:
        try:
            dt = datetime.fromisoformat(date_to.replace("Z", "+00:00")).date()
        except ValueError:
            pass

    base = db.query(User).filter(User.traffic_source == slug)
    if df is not None:
        base = base.filter(User.created_at >= datetime.combine(df, datetime.min.time()).replace(tzinfo=timezone.utc))
    if dt is not None:
        base = base.filter(User.created_at <= datetime.combine(dt, datetime.max.time()).replace(tzinfo=timezone.utc))
    users = base.all()
    user_ids = [u.id for u in users]
    starts = len(user_ids)

    subscribed = sum(1 for u in users if (u.flags or {}).get("subscribed_examples_channel"))
    with_take_or_job = set()
    if user_ids:
        take_users = db.query(Take.user_id).filter(Take.user_id.in_(user_ids)).distinct().all()
        job_users = db.query(Job.user_id).filter(Job.user_id.in_(user_ids)).distinct().all()
        with_take_or_job = {r[0] for r in take_users + job_users}
    first_generation = len(with_take_or_job)

    buyers = set()
    repeat_buyers = set()
    if user_ids:
        pay_per_user = db.query(Payment.user_id, func.count(Payment.id).label("cnt")).filter(
            Payment.user_id.in_(user_ids), Payment.status == "completed"
        ).group_by(Payment.user_id).all()
        for uid, cnt in pay_per_user:
            buyers.add(uid)
            if cnt >= 2:
                repeat_buyers.add(uid)
    first_purchase = len(buyers)
    repeat_purchase = len(repeat_buyers)

    return {
        "slug": slug,
        "steps": [
            {"name": "start", "label": "/start", "count": starts, "pct": 100.0},
            {"name": "subscribed", "label": "Подписка на канал", "count": subscribed, "pct": round(100.0 * subscribed / starts, 1) if starts else 0},
            {"name": "first_generation", "label": "Первая генерация", "count": first_generation, "pct": round(100.0 * first_generation / starts, 1) if starts else 0},
            {"name": "first_purchase", "label": "Первая покупка", "count": first_purchase, "pct": round(100.0 * first_purchase / starts, 1) if starts else 0},
            {"name": "repeat_purchase", "label": "Повторная покупка", "count": repeat_purchase, "pct": round(100.0 * repeat_purchase / starts, 1) if starts else 0},
        ],
        "date_from": date_from,
        "date_to": date_to,
    }


@router.get("/traffic-sources/{slug}/users")
def traffic_source_users(
    slug: str,
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """Last users attributed to this source (for detail view)."""
    q = db.query(User).filter(User.traffic_source == slug).order_by(User.created_at.desc()).offset(offset).limit(limit)
    users = q.all()
    user_ids = [u.id for u in users]
    bought = set()
    if user_ids:
        bought = {r[0] for r in db.query(Payment.user_id).filter(Payment.user_id.in_(user_ids), Payment.status == "completed").distinct().all()}
    items = []
    for u in users:
        items.append({
            "id": u.id,
            "telegram_id": u.telegram_id,
            "username": u.telegram_username,
            "first_name": u.telegram_first_name,
            "created_at": u.created_at.isoformat() if u.created_at else None,
            "has_purchased": u.id in bought,
        })
    return {"items": items, "total": db.query(User).filter(User.traffic_source == slug).count()}


# ---------- Ad campaigns (budget, ROI) ----------

class AdCampaignCreate(BaseModel):
    source_id: str
    name: str
    budget_rub: float = 0
    date_from: str
    date_to: str
    notes: str | None = None


class AdCampaignUpdate(BaseModel):
    name: str | None = None
    budget_rub: float | None = None
    date_from: str | None = None
    date_to: str | None = None
    is_active: bool | None = None
    notes: str | None = None


@router.get("/ad-campaigns")
def ad_campaigns_list(db: Session = Depends(get_db)):
    """List ad campaigns with source name."""
    campaigns = db.query(AdCampaign).order_by(AdCampaign.date_from.desc()).all()
    source_ids = list({c.source_id for c in campaigns})
    sources_map = {}
    if source_ids:
        for s in db.query(TrafficSource).filter(TrafficSource.id.in_(source_ids)).all():
            sources_map[s.id] = {"id": s.id, "slug": s.slug, "name": s.name}
    out = []
    for c in campaigns:
        out.append({
            "id": c.id,
            "source_id": c.source_id,
            "source": sources_map.get(c.source_id, {}),
            "name": c.name,
            "slug": c.slug,
            "budget_rub": float(c.budget_rub),
            "date_from": c.date_from.isoformat() if c.date_from else None,
            "date_to": c.date_to.isoformat() if c.date_to else None,
            "is_active": c.is_active,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "notes": c.notes,
        })
    return out


@router.post("/ad-campaigns")
def ad_campaigns_create(body: AdCampaignCreate, db: Session = Depends(get_db)):
    """Create ad campaign."""
    source = db.query(TrafficSource).filter(TrafficSource.id == body.source_id).first()
    if not source:
        raise HTTPException(404, "Traffic source not found")
    try:
        d_from = datetime.fromisoformat(body.date_from.replace("Z", "")).date()
        d_to = datetime.fromisoformat(body.date_to.replace("Z", "")).date()
    except (ValueError, AttributeError):
        raise HTTPException(400, "date_from and date_to must be ISO date (YYYY-MM-DD)")
    if d_from > d_to:
        raise HTTPException(400, "date_from must be <= date_to")
    campaign = AdCampaign(
        source_id=body.source_id,
        name=body.name.strip() or "Campaign",
        budget_rub=body.budget_rub,
        date_from=d_from,
        date_to=d_to,
        notes=(body.notes or "").strip() or None,
    )
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    return {
        "id": campaign.id,
        "source_id": campaign.source_id,
        "name": campaign.name,
        "budget_rub": float(campaign.budget_rub),
        "date_from": campaign.date_from.isoformat(),
        "date_to": campaign.date_to.isoformat(),
        "is_active": campaign.is_active,
        "created_at": campaign.created_at.isoformat() if campaign.created_at else None,
        "notes": campaign.notes,
    }


@router.patch("/ad-campaigns/{campaign_id}")
def ad_campaigns_update(campaign_id: str, body: AdCampaignUpdate, db: Session = Depends(get_db)):
    """Update ad campaign."""
    campaign = db.query(AdCampaign).filter(AdCampaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(404, "Campaign not found")
    if body.name is not None:
        campaign.name = body.name.strip() or campaign.name
    if body.budget_rub is not None:
        campaign.budget_rub = body.budget_rub
    if body.date_from is not None:
        try:
            campaign.date_from = datetime.fromisoformat(body.date_from.replace("Z", "")).date()
        except (ValueError, AttributeError):
            raise HTTPException(400, "Invalid date_from")
    if body.date_to is not None:
        try:
            campaign.date_to = datetime.fromisoformat(body.date_to.replace("Z", "")).date()
        except (ValueError, AttributeError):
            raise HTTPException(400, "Invalid date_to")
    if body.is_active is not None:
        campaign.is_active = body.is_active
    if body.notes is not None:
        campaign.notes = body.notes.strip() if body.notes else None
    db.commit()
    db.refresh(campaign)
    return {
        "id": campaign.id,
        "source_id": campaign.source_id,
        "name": campaign.name,
        "budget_rub": float(campaign.budget_rub),
        "date_from": campaign.date_from.isoformat(),
        "date_to": campaign.date_to.isoformat(),
        "is_active": campaign.is_active,
        "notes": campaign.notes,
        "updated_at": campaign.updated_at.isoformat() if campaign.updated_at else None,
    }


@router.get("/ad-campaigns/{campaign_id}/roi")
def ad_campaign_roi(campaign_id: str, db: Session = Depends(get_db)):
    """CPA, CPP, ROAS for this campaign. Uses campaign period and source slug."""
    campaign = db.query(AdCampaign).filter(AdCampaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(404, "Campaign not found")
    source = db.query(TrafficSource).filter(TrafficSource.id == campaign.source_id).first()
    if not source:
        raise HTTPException(404, "Source not found")
    slug = source.slug
    d_from = campaign.date_from
    d_to = campaign.date_to
    ts_from = datetime.combine(d_from, datetime.min.time()).replace(tzinfo=timezone.utc)
    ts_to = datetime.combine(d_to, datetime.max.time()).replace(tzinfo=timezone.utc)

    base = db.query(User).filter(User.traffic_source == slug, User.created_at >= ts_from, User.created_at <= ts_to)
    user_ids = [u.id for u in base.all()]
    new_users = len(user_ids)
    budget = float(campaign.budget_rub)
    cpa = round(budget / new_users, 2) if new_users else None
    buyers = 0
    revenue_stars = 0
    if user_ids:
        buyers = db.query(func.count(func.distinct(Payment.user_id))).filter(
            Payment.user_id.in_(user_ids), Payment.status == "completed"
        ).scalar() or 0
        rev = db.query(func.coalesce(func.sum(Payment.stars_amount), 0)).filter(
            Payment.user_id.in_(user_ids), Payment.status == "completed"
        ).scalar() or 0
        revenue_stars = int(rev)
    revenue_rub = round(revenue_stars * STAR_RUB_RATE, 0)
    cpp = round(budget / buyers, 2) if buyers else None
    roas = round(revenue_rub / budget, 2) if budget and budget > 0 else None
    return {
        "campaign_id": campaign_id,
        "source_slug": slug,
        "name": campaign.name,
        "budget_rub": budget,
        "date_from": d_from.isoformat(),
        "date_to": d_to.isoformat(),
        "new_users": new_users,
        "buyers": buyers,
        "revenue_stars": revenue_stars,
        "revenue_rub": revenue_rub,
        "cpa_rub": cpa,
        "cpp_rub": cpp,
        "roas": roas,
    }


# ===========================================
# Photo Merge — admin endpoints
# ===========================================

@router.get("/photo-merge/jobs")
def photo_merge_jobs_list(
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    status: str | None = Query(None),
    user_id: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
):
    """Список заданий склейки с фильтрами."""
    q = db.query(PhotoMergeJob)
    if status:
        q = q.filter(PhotoMergeJob.status == status)
    if user_id:
        q = q.filter(PhotoMergeJob.user_id == user_id)
    if date_from:
        try:
            q = q.filter(PhotoMergeJob.created_at >= datetime.fromisoformat(date_from))
        except ValueError:
            pass
    if date_to:
        try:
            q = q.filter(PhotoMergeJob.created_at <= datetime.fromisoformat(date_to))
        except ValueError:
            pass
    total = q.count()
    rows = q.order_by(PhotoMergeJob.created_at.desc()).offset(offset).limit(limit).all()

    # Обогащаем никами пользователей
    user_ids = list({r.user_id for r in rows})
    users_map: dict[str, Any] = {}
    if user_ids:
        for u in db.query(User).filter(User.telegram_id.in_(user_ids)).all():
            users_map[u.telegram_id] = (u.telegram_username or u.telegram_first_name or u.telegram_id)

    items = []
    for r in rows:
        items.append({
            "id": r.id,
            "user_id": r.user_id,
            "user_display_name": users_map.get(r.user_id, r.user_id),
            "status": r.status,
            "input_count": r.input_count,
            "output_format": r.output_format,
            "input_bytes": r.input_bytes,
            "output_bytes": r.output_bytes,
            "duration_ms": r.duration_ms,
            "error_code": r.error_code,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        })
    return {"total": total, "items": items}


@router.get("/photo-merge/stats")
def photo_merge_stats(
    db: Session = Depends(get_db),
    window_days: int = Query(30, ge=1, le=365),
):
    """Аналитика сервиса склейки за указанный период."""
    since = datetime.now(timezone.utc) - timedelta(days=window_days)
    q = db.query(PhotoMergeJob).filter(PhotoMergeJob.created_at >= since)

    total = q.count()
    succeeded = q.filter(PhotoMergeJob.status == "succeeded").count()
    failed = q.filter(PhotoMergeJob.status == "failed").count()
    processing = q.filter(PhotoMergeJob.status == "processing").count()

    # Среднее время обработки (только успешные)
    durations = [r.duration_ms for r in q.filter(PhotoMergeJob.status == "succeeded").all() if r.duration_ms]
    durations_sorted = sorted(durations)
    p50 = durations_sorted[len(durations_sorted) // 2] if durations_sorted else None
    p95 = durations_sorted[int(len(durations_sorted) * 0.95)] if durations_sorted else None
    avg_duration_ms = int(sum(durations) / len(durations)) if durations else None

    # Топ пользователей
    user_counts = {}
    for row in db.query(PhotoMergeJob).filter(PhotoMergeJob.created_at >= since).all():
        user_counts[row.user_id] = user_counts.get(row.user_id, 0) + 1
    top_users_raw = sorted(user_counts.items(), key=lambda x: x[1], reverse=True)[:10]
    user_ids = [uid for uid, _ in top_users_raw]
    users_map = {}
    if user_ids:
        for u in db.query(User).filter(User.telegram_id.in_(user_ids)).all():
            users_map[u.telegram_id] = (u.telegram_username or u.telegram_first_name or u.telegram_id)
    top_users = [{"user_id": uid, "display_name": users_map.get(uid, uid), "count": cnt} for uid, cnt in top_users_raw]

    # Распределение по дням
    by_day: dict[str, dict] = {}
    for row in db.query(PhotoMergeJob).filter(PhotoMergeJob.created_at >= since).all():
        day = row.created_at.strftime("%Y-%m-%d")
        if day not in by_day:
            by_day[day] = {"date": day, "total": 0, "succeeded": 0, "failed": 0}
        by_day[day]["total"] += 1
        if row.status == "succeeded":
            by_day[day]["succeeded"] += 1
        elif row.status == "failed":
            by_day[day]["failed"] += 1
    by_day_list = sorted(by_day.values(), key=lambda x: x["date"])

    # Объемы
    vol_input = sum(r.input_bytes or 0 for r in q.filter(PhotoMergeJob.status == "succeeded").all())
    vol_output = sum(r.output_bytes or 0 for r in q.filter(PhotoMergeJob.status == "succeeded").all())

    return {
        "window_days": window_days,
        "total": total,
        "succeeded": succeeded,
        "failed": failed,
        "processing": processing,
        "success_rate": round(succeeded / total * 100, 1) if total > 0 else 0,
        "avg_duration_ms": avg_duration_ms,
        "p50_duration_ms": p50,
        "p95_duration_ms": p95,
        "total_input_bytes": vol_input,
        "total_output_bytes": vol_output,
        "top_users": top_users,
        "by_day": by_day_list,
    }


@router.get("/photo-merge/settings")
def photo_merge_settings_get(db: Session = Depends(get_db)):
    """Текущие настройки сервиса склейки."""
    svc = PhotoMergeSettingsService(db)
    return svc.as_dict()


@router.put("/photo-merge/settings")
def photo_merge_settings_put(payload: dict, db: Session = Depends(get_db)):
    """Обновить настройки сервиса склейки."""
    svc = PhotoMergeSettingsService(db)
    return svc.update(payload)
