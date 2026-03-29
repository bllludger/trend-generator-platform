"""
Admin API: security, settings, users, telegram messages, telemetry, bank transfer,
payments, packs, trends, audit, broadcast, jobs, copy style, cleanup.
Paths match admin-frontend/src/services/api.ts. Order: /users/analytics and /users before /users/{id}.
"""
import logging
import os
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import and_, case, distinct, func, literal_column, or_, select
from sqlalchemy.orm import Session, joinedload

from app.db.session import get_db


def _as_utc(dt: datetime | None) -> datetime | None:
    """Normalize to timezone-aware UTC for safe max() with mixed naive/aware datetimes."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


FREE_PREVIEW_PACK_NAME = "Бесплатный (без 4К)"


from app.models.audit_log import AuditLog
from app.models.bank_transfer_receipt_log import BankTransferReceiptLog
from app.models.job import Job
from app.models.pack import Pack
from app.models.take import Take
from app.models.payment import Payment
from app.models.session import Session as SessionModel
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
from app.services.payments.service import PaymentService, PRODUCT_LADDER_IDS
from app.services.security.settings_service import SecuritySettingsService
from app.services.telegram_messages.service import TelegramMessageTemplateService
from app.services.transfer_policy.service import get_all as transfer_get_all, get_effective as transfer_get_effective, update_both as transfer_update_both
from app.services.themes.service import ThemeService
from app.services.trends.service import TrendService
from app.services.generation_prompt.settings_service import GenerationPromptSettingsService
from app.core.config import settings as app_settings
from app.api.routes.playground import trend_to_playground_config
from app.workers.tasks.broadcast import broadcast_message
from app.workers.tasks.send_user_message import send_telegram_to_user
from app.services.idempotency import get_admin_grant_response, set_admin_grant_response
from app.utils.metrics import admin_grant_pack_total, admin_reset_limits_total
from app.models.referral_bonus import ReferralBonus
from app.referral.service import ReferralService
from app.models.traffic_source import TrafficSource
from app.models.ad_campaign import AdCampaign
from app.models.photo_merge_job import PhotoMergeJob
from app.models.poster_settings import PosterSettings
from app.models.trial_v2_progress import TrialV2Progress
from app.models.trend_post import TrendPost
from app.services.photo_merge.settings_service import PhotoMergeSettingsService
from app.services.telegram.client import TelegramClient
from app.services.product_analytics.service import (
    FUNNEL_EVENT_NAMES as TRACKED_FUNNEL_EVENT_NAMES,
    PRODUCT_ANALYTICS_SCHEMA_VERSION,
    is_known_button_id,
    is_known_product_event,
)
from app.services.product_analytics.overview_v3 import build_overview_v3

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(get_current_user)])


def _admin_audit(
    db: Session,
    current_user: dict,
    action: str,
    entity_type: str,
    entity_id: str | None,
    payload: dict | None = None,
) -> None:
    """Log admin action to audit_logs. Swallows errors to avoid breaking the main flow."""
    try:
        AuditService(db).log(
            actor_type="admin",
            actor_id=current_user.get("username") or "unknown",
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            payload=payload or {},
        )
    except Exception:
        logger.exception("admin audit log failed")


# ---------- Security ----------
@router.get("/security/settings")
def security_get_settings(db: Session = Depends(get_db)):
    svc = SecuritySettingsService(db)
    return svc.as_dict()


@router.put("/security/settings")
def security_update_settings(
    payload: dict,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    svc = SecuritySettingsService(db)
    result = svc.update(payload)
    _admin_audit(db, current_user, "update", "security_settings", None, {"section": "security"})
    return result


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
def security_ban_user(
    user_id: str,
    payload: dict | None = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    user.is_banned = True
    user.ban_reason = (payload or {}).get("reason") if payload else None
    user.banned_at = datetime.now(timezone.utc)
    db.add(user)
    db.commit()
    _admin_audit(db, current_user, "user_banned", "user", user_id, {"reason": (payload or {}).get("reason")})
    return {"ok": True}


@router.post("/security/users/{user_id}/unban")
def security_unban_user(
    user_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    user.is_banned = False
    user.ban_reason = None
    user.banned_at = None
    user.banned_by = None
    # Разбан должен полностью восстанавливать доступ: снимаем и возможную временную приостановку.
    user.is_suspended = False
    user.suspended_until = None
    user.suspend_reason = None
    db.add(user)
    db.commit()
    _admin_audit(db, current_user, "user_unbanned", "user", user_id, {})
    return {"ok": True}


@router.post("/security/users/{user_id}/suspend")
def security_suspend_user(
    user_id: str,
    payload: dict,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    hours = int(payload.get("hours", 24))
    user.is_suspended = True
    user.suspended_until = datetime.now(timezone.utc) + timedelta(hours=hours)
    user.suspend_reason = payload.get("reason")
    db.add(user)
    db.commit()
    _admin_audit(db, current_user, "user_suspended", "user", user_id, {"hours": hours, "reason": payload.get("reason")})
    return {"ok": True}


@router.post("/security/users/{user_id}/resume")
def security_resume_user(
    user_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    user.is_suspended = False
    user.suspended_until = None
    user.suspend_reason = None
    db.add(user)
    db.commit()
    _admin_audit(db, current_user, "user_resumed", "user", user_id, {})
    return {"ok": True}


@router.post("/security/users/{user_id}/rate-limit")
def security_set_rate_limit(
    user_id: str,
    payload: dict,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    limit = payload.get("limit")
    user.rate_limit_per_hour = int(limit) if limit is not None and limit != "" else None
    db.add(user)
    db.commit()
    _admin_audit(db, current_user, "rate_limit_set", "user", user_id, {"limit": user.rate_limit_per_hour})
    return {"ok": True}


@router.post("/security/users/{user_id}/moderator")
def security_set_moderator(
    user_id: str,
    payload: dict,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    user.is_moderator = bool(payload.get("is_moderator", False))
    db.add(user)
    db.commit()
    _admin_audit(db, current_user, "moderator", "user", user_id, {"is_moderator": user.is_moderator})
    return {"ok": True}


@router.post("/security/users/{user_id}/hard-delete")
def security_hard_delete_user(
    user_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Permanently delete a user and all directly related records.
    This action is irreversible and intended for admin-only data purge.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")

    # Local imports keep this endpoint isolated from module import side effects.
    from app.models.favorite import Favorite
    from app.models.session import Session as SessionModel
    from app.models.take import Take as TakeModel
    from app.models.job import Job
    from app.models.payment import Payment
    from app.models.photo_merge_job import PhotoMergeJob
    from app.models.compensation import CompensationLog
    from app.models.token_ledger import TokenLedger
    from app.models.product_event import ProductEvent
    from app.models.referral_bonus import ReferralBonus
    from app.models.referral_trial_reward import ReferralTrialReward
    from app.models.trial_v2_progress import TrialV2Progress
    from app.models.trial_v2_selection import TrialV2Selection
    from app.models.trial_v2_trend_slot import TrialV2TrendSlot
    from app.models.pack_order import PackOrder
    from app.models.unlock_order import UnlockOrder
    from app.models.trial_bundle_order import TrialBundleOrder
    from app.models.bank_transfer_receipt_log import BankTransferReceiptLog

    telegram_id = str(user.telegram_id or "")
    deleted: dict[str, int] = {}

    def _del(model, *conditions, label: str):
        q = db.query(model)
        for cond in conditions:
            q = q.filter(cond)
        count = q.delete(synchronize_session=False)
        deleted[label] = int(count or 0)

    try:
        # Rows linked by internal user.id
        # Keep dependency order: children first (payments can reference sessions/takes).
        _del(Payment, Payment.user_id == user.id, label="payments")
        _del(Favorite, Favorite.user_id == user.id, label="favorites")
        _del(TakeModel, TakeModel.user_id == user.id, label="takes")
        _del(SessionModel, SessionModel.user_id == user.id, label="sessions")
        _del(Job, Job.user_id == user.id, label="jobs")
        _del(PhotoMergeJob, PhotoMergeJob.user_id == user.id, label="photo_merge_jobs")
        _del(CompensationLog, CompensationLog.user_id == user.id, label="compensation_log")
        _del(TokenLedger, TokenLedger.user_id == user.id, label="token_ledger")
        _del(ProductEvent, ProductEvent.user_id == user.id, label="product_events")
        _del(TrialV2Progress, TrialV2Progress.user_id == user.id, label="trial_v2_progress")
        _del(TrialV2Selection, TrialV2Selection.user_id == user.id, label="trial_v2_selections")
        _del(TrialV2TrendSlot, TrialV2TrendSlot.user_id == user.id, label="trial_v2_trend_slots")

        # Referral entities where user may appear in either role
        _del(
            ReferralBonus,
            or_(ReferralBonus.referrer_user_id == user.id, ReferralBonus.referral_user_id == user.id),
            label="referral_bonuses",
        )
        _del(
            ReferralTrialReward,
            or_(ReferralTrialReward.referrer_user_id == user.id, ReferralTrialReward.referral_user_id == user.id),
            label="referral_trial_rewards",
        )

        # Rows linked by telegram_id (external checkout/order tables)
        if telegram_id:
            _del(PackOrder, PackOrder.telegram_user_id == telegram_id, label="pack_orders")
            _del(UnlockOrder, UnlockOrder.telegram_user_id == telegram_id, label="unlock_orders")
            _del(TrialBundleOrder, TrialBundleOrder.telegram_user_id == telegram_id, label="trial_bundle_orders")
            _del(
                BankTransferReceiptLog,
                or_(BankTransferReceiptLog.telegram_user_id == telegram_id, BankTransferReceiptLog.user_id == user.id),
                label="bank_transfer_receipt_log",
            )
        else:
            _del(BankTransferReceiptLog, BankTransferReceiptLog.user_id == user.id, label="bank_transfer_receipt_log")

        # Detach referrals in remaining users that point to the removed user.
        detached_referrals = (
            db.query(User)
            .filter(User.referred_by_user_id == user.id)
            .update(
                {
                    User.referred_by_user_id: None,
                },
                synchronize_session=False,
            )
        )
        deleted["users_detached_referrals"] = int(detached_referrals or 0)

        # Delete the user itself last.
        db.delete(user)
        deleted["users"] = 1
        db.commit()
    except Exception:
        db.rollback()
        raise

    _admin_audit(
        db,
        current_user,
        "user_hard_deleted",
        "user",
        user_id,
        {"telegram_id": telegram_id, "deleted": deleted},
    )
    return {"ok": True, "deleted": deleted}


@router.post("/security/reset-limits")
def security_reset_limits(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    from app.services.users.service import UserService
    count = UserService(db).reset_all_limits()
    db.commit()
    _admin_audit(db, current_user, "reset_limits", "user", None, {"users_updated": count})
    return {"users_updated": count}


# ---------- Transfer policy (оба набора: global, trends) ----------
@router.get("/settings/transfer-policy")
def transfer_policy_get(db: Session = Depends(get_db)):
    return transfer_get_all(db)


@router.put("/settings/transfer-policy")
def transfer_policy_put(
    payload: dict,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    result = transfer_update_both(db, payload)
    _admin_audit(db, current_user, "update", "settings", None, {"section": "transfer_policy"})
    return result


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
        app_dict.get("watermark_text") or getattr(app_settings, "watermark_text", "@ai_nanobananastudio_bot")
    )
    result["watermark_opacity"] = app_dict.get("watermark_opacity", 60)
    result["watermark_tile_spacing"] = app_dict.get("watermark_tile_spacing", 200)
    result["take_preview_max_dim"] = app_dict.get("take_preview_max_dim", 800)
    return result


@router.get("/settings/preview-policy")
def preview_policy_get(db: Session = Depends(get_db)):
    """Единый раздел настроек превью и вотермарка (для страницы «Политика превью»)."""
    app_svc = AppSettingsService(db)
    app_dict = app_svc.as_dict()
    return {
        "preview_format": app_dict.get("preview_format", "webp"),
        "preview_quality": app_dict.get("preview_quality", 85),
        "take_preview_max_dim": app_dict.get("take_preview_max_dim", 800),
        "job_preview_max_dim": app_dict.get("job_preview_max_dim", 800),
        "watermark_text": app_dict.get("watermark_text"),
        "watermark_text_effective": (
            app_dict.get("watermark_text") or getattr(app_settings, "watermark_text", "@ai_nanobananastudio_bot")
        ),
        "watermark_opacity": app_dict.get("watermark_opacity", 60),
        "watermark_tile_spacing": app_dict.get("watermark_tile_spacing", 200),
        "watermark_use_contrast": app_dict.get("watermark_use_contrast", True),
        "updated_at": app_dict.get("updated_at"),
    }


@router.put("/settings/preview-policy")
def preview_policy_put(
    payload: dict,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    app_svc = AppSettingsService(db)
    allowed = {
        "preview_format", "preview_quality", "take_preview_max_dim", "job_preview_max_dim",
        "watermark_text", "watermark_opacity", "watermark_tile_spacing", "watermark_use_contrast",
    }
    data = {k: v for k, v in payload.items() if k in allowed}
    if data:
        try:
            app_svc.update(data)
        except ValueError as e:
            raise HTTPException(400, str(e))
    _admin_audit(db, current_user, "update", "settings", None, {"section": "preview_policy"})
    return preview_policy_get(db)


@router.put("/settings/master-prompt")
def master_prompt_put(
    payload: dict,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    svc = GenerationPromptSettingsService(db)
    app_svc = AppSettingsService(db)
    app_keys = {"use_nano_banana_pro", "watermark_text", "watermark_opacity", "watermark_tile_spacing", "take_preview_max_dim", "preview_format", "preview_quality", "job_preview_max_dim", "watermark_use_contrast"}
    app_payload = {k: v for k, v in payload.items() if k in app_keys}
    if app_payload:
        try:
            app_svc.update(app_payload)
        except ValueError as e:
            raise HTTPException(400, str(e))
    data = {k: v for k, v in payload.items() if k not in app_keys}
    if data:
        svc.update(data)
    _admin_audit(db, current_user, "update", "settings", None, {"section": "master_prompt"})
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
def settings_app_put(
    payload: dict,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    svc = AppSettingsService(db)
    result = svc.update(payload)
    _admin_audit(db, current_user, "update", "settings", None, {"section": "app"})
    return result


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


_ALLOWED_SORT = {"created_at", "token_balance", "telegram_id", "payments_count", "jobs_count"}


@router.get("/users")
def users_list(
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    search: str | None = None,
    telegram_id: str | None = None,
    subscription_active: bool | None = None,
    trial_purchased: bool | None = None,
    pack_id: str | None = None,
    payments_count_min: int | None = Query(None, ge=0),
    sort_by: str = Query("created_at", description="created_at|token_balance|telegram_id|payments_count|jobs_count"),
    sort_order: str = Query("desc", description="asc|desc"),
):
    sort_by = sort_by.strip().lower() if sort_by else "created_at"
    sort_order = sort_order.strip().lower() if sort_order else "desc"
    if sort_by not in _ALLOWED_SORT:
        sort_by = "created_at"
    if sort_order not in ("asc", "desc"):
        sort_order = "desc"
    need_pay_join = sort_by == "payments_count" or payments_count_min is not None
    need_job_join = sort_by == "jobs_count"

    q = db.query(User)
    if need_pay_join:
        pay_subq = (
            db.query(Payment.user_id, func.count(Payment.id).label("pay_count"))
            .filter(Payment.status == "completed")
            .group_by(Payment.user_id)
            .subquery()
        )
        q = q.outerjoin(pay_subq, User.id == pay_subq.c.user_id)
    if need_job_join:
        job_subq = (
            db.query(Job.user_id, func.count(Job.job_id).label("job_count"))
            .group_by(Job.user_id)
            .subquery()
        )
        q = q.outerjoin(job_subq, User.id == job_subq.c.user_id)
    if pack_id:
        pack_id = pack_id.strip()
        active_with_pack = (
            db.query(SessionModel.user_id)
            .filter(SessionModel.status == "active", SessionModel.pack_id == pack_id)
            .distinct()
            .subquery()
        )
        q = q.join(active_with_pack, User.id == active_with_pack.c.user_id)

    search_val = (search or telegram_id or "").strip()
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
    if trial_purchased is not None:
        q = q.filter(User.trial_purchased.is_(trial_purchased))
    if payments_count_min is not None and need_pay_join:
        q = q.filter(pay_subq.c.pay_count >= payments_count_min)

    total = q.count()
    order_col = None
    if sort_by == "created_at":
        order_col = User.created_at
    elif sort_by == "token_balance":
        order_col = User.token_balance
    elif sort_by == "telegram_id":
        order_col = User.telegram_id
    elif sort_by == "payments_count" and need_pay_join:
        order_col = pay_subq.c.pay_count
    elif sort_by == "jobs_count" and need_job_join:
        order_col = job_subq.c.job_count
    if order_col is None:
        order_col = User.created_at
    if sort_order == "asc":
        q = q.order_by(order_col.asc().nullslast())
    else:
        q = q.order_by(order_col.desc().nullslast())
    q = q.offset((page - 1) * page_size).limit(page_size)
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
    # Take last activity per user (max created_at) for last_active
    take_last_by_user = {}
    if user_ids:
        take_agg = (
            db.query(Take.user_id, func.max(Take.created_at).label("last_take_at"))
            .filter(Take.user_id.in_(user_ids))
            .group_by(Take.user_id)
        )
        for row in take_agg:
            if row.last_take_at:
                take_last_by_user[row.user_id] = row.last_take_at
    # Active session per user (latest by created_at) and payments count
    active_by_user = {}
    payments_count_by_user = {}
    if user_ids:
        active_sessions = (
            db.query(SessionModel)
            .filter(SessionModel.user_id.in_(user_ids), SessionModel.status == "active")
            .order_by(SessionModel.created_at.desc())
            .all()
        )
        for s in active_sessions:
            if s.user_id not in active_by_user:
                active_by_user[s.user_id] = s
        pack_ids = list({s.pack_id for s in active_by_user.values()})
        pack_map = {}
        if pack_ids:
            for p in db.query(Pack).filter(Pack.id.in_(pack_ids)).all():
                pack_map[p.id] = p
        pay_agg = (
            db.query(Payment.user_id, func.count(Payment.id).label("cnt"))
            .filter(Payment.user_id.in_(user_ids), Payment.status == "completed")
            .group_by(Payment.user_id)
        )
        for row in pay_agg:
            payments_count_by_user[row.user_id] = row.cnt or 0
    sec = SecuritySettingsService(db).get_or_create()
    free_limit = getattr(sec, "free_generations_per_user", 3)
    copy_limit = getattr(sec, "copy_generations_per_user", 1)
    items = []
    for u in users:
        stats = job_stats.get(u.id, {"jobs_count": 0, "succeeded": 0, "failed": 0, "last_active": None})
        job_last_iso = stats.get("last_active")
        take_dt = take_last_by_user.get(u.id)
        if job_last_iso and take_dt:
            try:
                job_dt = datetime.fromisoformat(job_last_iso.replace("Z", "+00:00"))
                last_active_iso = max(_as_utc(job_dt), _as_utc(take_dt)).isoformat()
            except (ValueError, TypeError):
                last_active_iso = job_last_iso
        elif take_dt:
            last_active_iso = take_dt.isoformat()
        else:
            last_active_iso = job_last_iso
        sess = active_by_user.get(u.id)
        active_session = None
        if sess:
            pack = pack_map.get(sess.pack_id)
            takes_remaining = max(0, (sess.takes_limit or 0) - (sess.takes_used or 0))
            hd_remaining = max(0, (sess.hd_limit or 0) - (sess.hd_used or 0))
            active_session = {
                "pack_id": sess.pack_id,
                "pack_name": FREE_PREVIEW_PACK_NAME if sess.pack_id == "free_preview" else (pack.name if pack else sess.pack_id),
                "takes_limit": sess.takes_limit,
                "takes_used": sess.takes_used,
                "takes_remaining": takes_remaining,
                "hd_limit": sess.hd_limit,
                "hd_used": sess.hd_used,
                "hd_remaining": hd_remaining,
            }
        items.append({
            "id": u.id,
            "telegram_id": u.telegram_id,
            "telegram_username": u.telegram_username,
            "telegram_first_name": u.telegram_first_name,
            "telegram_last_name": u.telegram_last_name,
            "token_balance": u.token_balance,
            "subscription_active": u.subscription_active,
            "free_generations_used": u.free_generations_used,
            "free_generations_limit": free_limit,
            "copy_generations_used": u.copy_generations_used,
            "copy_generations_limit": copy_limit,
            "created_at": u.created_at.isoformat() if u.created_at else None,
            "jobs_count": stats["jobs_count"],
            "succeeded": stats["succeeded"],
            "failed": stats["failed"],
            "last_active": last_active_iso,
            "trial_purchased": bool(getattr(u, "trial_purchased", False)),
            "free_takes_used": getattr(u, "free_takes_used", 0) or 0,
            "trial_v2_eligible": bool(getattr(u, "trial_v2_eligible", False)),
            "payments_count": payments_count_by_user.get(u.id, 0),
            "active_session": active_session,
        })
    return {"items": items, "total": total, "page": page, "pages": (total + page_size - 1) // page_size}


def _resolve_user_by_id_or_telegram(db: Session, user_id: str) -> User | None:
    """Resolve user by primary key (UUID) or by telegram_id."""
    u = db.query(User).filter(User.id == user_id).first()
    if u:
        return u
    return db.query(User).filter(User.telegram_id == user_id).first()


@router.get("/users/{user_id}")
def user_detail(user_id: str, db: Session = Depends(get_db)):
    user = _resolve_user_by_id_or_telegram(db, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    payment_svc = PaymentService(db)
    payments = payment_svc.get_user_payments(user.id, limit=30)
    active_session = (
        db.query(SessionModel)
        .filter(SessionModel.user_id == user.id, SessionModel.status == "active")
        .order_by(SessionModel.created_at.desc())
        .first()
    )
    sessions = (
        db.query(SessionModel)
        .filter(SessionModel.user_id == user.id)
        .order_by(SessionModel.created_at.desc())
        .limit(20)
        .all()
    )
    pack_ids = list({s.pack_id for s in sessions}) + ([active_session.pack_id] if active_session else [])
    pack_map = {}
    if pack_ids:
        for p in db.query(Pack).filter(Pack.id.in_(pack_ids)).all():
            pack_map[p.id] = p
    sec = SecuritySettingsService(db).get_or_create()
    free_limit = getattr(sec, "free_generations_per_user", 3)
    copy_limit = getattr(sec, "copy_generations_per_user", 1)
    trial_progress = (
        db.query(TrialV2Progress)
        .filter(TrialV2Progress.user_id == user.id)
        .one_or_none()
    )

    def _session_row(s: SessionModel):
        pack = pack_map.get(s.pack_id)
        pack_name = FREE_PREVIEW_PACK_NAME if s.pack_id == "free_preview" else (pack.name if pack else s.pack_id)
        return {
            "id": s.id,
            "pack_id": s.pack_id,
            "pack_name": pack_name,
            "status": s.status,
            "takes_limit": s.takes_limit,
            "takes_used": s.takes_used,
            "hd_limit": s.hd_limit,
            "hd_used": s.hd_used,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        }

    active_session_out = None
    if active_session:
        active_session_out = _session_row(active_session)
        active_session_out["takes_remaining"] = max(0, (active_session.takes_limit or 0) - (active_session.takes_used or 0))
        active_session_out["hd_remaining"] = max(0, (active_session.hd_limit or 0) - (active_session.hd_used or 0))

    job_last = db.query(func.max(Job.updated_at)).filter(Job.user_id == user.id).scalar()
    take_last = db.query(func.max(Take.created_at)).filter(Take.user_id == user.id).scalar()
    if job_last and take_last:
        last_active_iso = max(_as_utc(job_last), _as_utc(take_last)).isoformat()
    elif take_last:
        last_active_iso = take_last.isoformat()
    else:
        last_active_iso = job_last.isoformat() if job_last else None

    return {
        "id": user.id,
        "telegram_id": user.telegram_id,
        "telegram_username": user.telegram_username,
        "telegram_first_name": user.telegram_first_name,
        "telegram_last_name": user.telegram_last_name,
        "token_balance": user.token_balance,
        "subscription_active": user.subscription_active,
        "free_generations_used": user.free_generations_used,
        "free_generations_limit": free_limit,
        "copy_generations_used": user.copy_generations_used,
        "copy_generations_limit": copy_limit,
        "trial_purchased": bool(getattr(user, "trial_purchased", False)),
        "free_takes_used": getattr(user, "free_takes_used", 0) or 0,
        "hd_paid_balance": getattr(user, "hd_paid_balance", 0) or 0,
        "hd_promo_balance": getattr(user, "hd_promo_balance", 0) or 0,
        "admin_notes": user.admin_notes,
        "is_banned": user.is_banned,
        "is_suspended": user.is_suspended,
        "suspended_until": user.suspended_until.isoformat() if user.suspended_until else None,
        "rate_limit_per_hour": user.rate_limit_per_hour,
        "is_moderator": user.is_moderator,
        "trial_v2_eligible": bool(getattr(user, "trial_v2_eligible", False)),
        "trial_first_preview_completed": bool(getattr(user, "trial_first_preview_completed", False)),
        "trial_first_preview_completed_at": user.trial_first_preview_completed_at.isoformat() if getattr(user, "trial_first_preview_completed_at", None) else None,
        "trial_v2": {
            "trend_slots_used": int(getattr(trial_progress, "trend_slots_used", 0) or 0),
            "trend_slots_total": 3,
            "rerolls_used": int(getattr(trial_progress, "rerolls_used", 0) or 0),
            "rerolls_total": 3,
            "takes_used": int(getattr(trial_progress, "takes_used", 0) or 0),
            "takes_total": 6,
            "reward_earned_total": int(getattr(trial_progress, "reward_earned_total", 0) or 0),
            "reward_claimed_total": int(getattr(trial_progress, "reward_claimed_total", 0) or 0),
            "reward_available": int(getattr(trial_progress, "reward_available", 0) or 0),
            "reward_reserved": int(getattr(trial_progress, "reward_reserved", 0) or 0),
        },
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "updated_at": user.updated_at.isoformat() if user.updated_at else None,
        "last_active": last_active_iso,
        "active_session": active_session_out,
        "sessions": [_session_row(s) for s in sessions],
        "payments": [
            {
                "id": p.id,
                "pack_id": p.pack_id,
                "status": p.status,
                "stars_amount": p.stars_amount,
                "amount_kopecks": p.amount_kopecks,
                "tokens_granted": p.tokens_granted,
                "session_id": p.session_id,
                "created_at": p.created_at.isoformat() if p.created_at else None,
            }
            for p in payments
        ],
    }


class GrantPackBody(BaseModel):
    pack_id: str
    activation_message: str | None = None


@router.post("/users/{user_id}/grant-pack")
def user_grant_pack(
    request: Request,
    user_id: str,
    body: GrantPackBody,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    from uuid import uuid4

    idempotency_key = (request.headers.get("Idempotency-Key") or "").strip() or None
    if idempotency_key:
        cached = get_admin_grant_response(idempotency_key)
        if cached is not None:
            admin_grant_pack_total.labels(status="idempotent_replay").inc()
            logger.info(
                "admin_grant_pack_idempotent_replay",
                extra={"request_id": getattr(request.state, "request_id", None), "user_id": user_id, "pack_id": body.pack_id},
            )
            return cached

    user = _resolve_user_by_id_or_telegram(db, user_id)
    if not user:
        admin_grant_pack_total.labels(status="failure").inc()
        raise HTTPException(404, "User not found")
    payment_svc = PaymentService(db)
    pack = payment_svc.get_pack(body.pack_id)
    if not pack:
        admin_grant_pack_total.labels(status="failure").inc()
        raise HTTPException(400, "Pack not found")
    if not pack.enabled:
        admin_grant_pack_total.labels(status="failure").inc()
        raise HTTPException(400, "Pack is disabled")

    reference = idempotency_key if idempotency_key else str(uuid4())
    session_id = None
    payment_id = None
    try:
        if pack.id in PRODUCT_LADDER_IDS:
            try:
                payment, session, trial_error = payment_svc.grant_session_pack_admin(
                    user.telegram_id, body.pack_id, reference, allow_trial_regrant=True
                )
            except ValueError as e:
                admin_grant_pack_total.labels(status="failure").inc()
                raise HTTPException(400, str(e))
            if trial_error == "trial_already_used":
                admin_grant_pack_total.labels(status="failure").inc()
                raise HTTPException(400, "Пробный тариф уже использован")
            if not payment:
                admin_grant_pack_total.labels(status="failure").inc()
                raise HTTPException(400, "Failed to grant session pack")
            session_id = session.id if session else None
            payment_id = payment.id
        else:
            payment = payment_svc.credit_tokens(
                telegram_user_id=user.telegram_id,
                telegram_payment_charge_id=f"admin_manual:{reference}",
                provider_payment_charge_id=None,
                pack_id=body.pack_id,
                stars_amount=0,
                tokens_granted=pack.tokens or 0,
                payload=f"admin_manual:{reference}",
            )
            if not payment:
                admin_grant_pack_total.labels(status="failure").inc()
                raise HTTPException(400, "Failed to grant tokens")
            payment_id = payment.id
        db.commit()
    except HTTPException:
        raise
    except Exception as e:
        admin_grant_pack_total.labels(status="failure").inc()
        logger.exception(
            "admin_grant_pack_error",
            extra={"request_id": getattr(request.state, "request_id", None), "user_id": user_id, "pack_id": body.pack_id, "error": str(e)},
        )
        raise

    if body.activation_message and body.activation_message.strip():
        try:
            send_telegram_to_user.delay(user.telegram_id, body.activation_message.strip())
        except Exception as e:
            logger.warning(
                "admin_grant_pack_telegram_enqueue_failed",
                extra={
                    "request_id": getattr(request.state, "request_id", None),
                    "user_id": user.id,
                    "telegram_id": user.telegram_id,
                    "error": str(e),
                },
            )
            # Не возвращаем 5xx: выдача уже выполнена, уведомление — best-effort

    response = {
        "ok": True,
        "message": "Пакет выдан",
        "session_id": session_id,
        "payment_id": payment_id,
    }
    _admin_audit(
        db,
        current_user,
        "grant_pack",
        "user",
        user.id,
        {"pack_id": body.pack_id, "payment_id": payment_id, "session_id": session_id},
    )
    admin_grant_pack_total.labels(status="success").inc()
    logger.info(
        "admin_grant_pack_success",
        extra={
            "request_id": getattr(request.state, "request_id", None),
            "user_id": user.id,
            "pack_id": body.pack_id,
            "payment_id": payment_id,
        },
    )
    if idempotency_key:
        set_admin_grant_response(idempotency_key, response)
    return response


@router.post("/users/{user_id}/reset-limits")
def user_reset_limits(
    request: Request,
    user_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    from app.services.users.service import UserService

    user = _resolve_user_by_id_or_telegram(db, user_id)
    if not user:
        admin_reset_limits_total.labels(status="failure").inc()
        raise HTTPException(404, "User not found")
    updated = UserService(db).reset_user_limits(user)
    if not updated:
        db.commit()
        _admin_audit(db, current_user, "reset_limits", "user", user_id, {"updated": False})
        admin_reset_limits_total.labels(status="no_change").inc()
        logger.info(
            "admin_reset_limits_no_change",
            extra={"request_id": getattr(request.state, "request_id", None), "user_id": user_id},
        )
        return {"ok": True, "updated": False}
    db.commit()
    _admin_audit(db, current_user, "reset_limits", "user", user_id, {"updated": True})
    admin_reset_limits_total.labels(status="success").inc()
    logger.info(
        "admin_reset_limits_success",
        extra={"request_id": getattr(request.state, "request_id", None), "user_id": user.id},
    )
    return {"ok": True, "updated": True}


# ---------- Telegram messages ----------
@router.get("/telegram-messages")
def telegram_messages_list(db: Session = Depends(get_db)):
    svc = TelegramMessageTemplateService(db)
    return {"items": svc.list_templates()}


class TelegramBulkItem(BaseModel):
    key: str
    value: str


@router.post("/telegram-messages/bulk")
def telegram_messages_bulk(
    payload: dict,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    items = payload.get("items", [])
    svc = TelegramMessageTemplateService(db)
    result = svc.bulk_upsert(items, updated_by="admin")
    _admin_audit(db, current_user, "bulk_action", "telegram_messages", None, {"updated": result["updated"]})
    return {"updated": result["updated"]}


@router.post("/telegram-messages/reset")
def telegram_messages_reset(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    svc = TelegramMessageTemplateService(db)
    result = svc.reset_defaults(updated_by="admin")
    _admin_audit(db, current_user, "update", "telegram_messages", None, {"reset": result.get("reset", 0)})
    return {"reset": result.get("reset", 0)}


# ---------- Telemetry (dashboard from Job / User / Trend) ----------
def _telemetry_since(db: Session, since: datetime) -> tuple[int, dict[str, int]]:
    """Jobs in window: total and by_status."""
    q = db.query(Job.status, func.count(Job.job_id)).filter(Job.created_at >= since).group_by(Job.status)
    by_status = {row[0]: row[1] for row in q}
    total = sum(by_status.values())
    return total, by_status


def _utc_date_job():
    """Expression: date(Job.created_at) in UTC for grouping (supports .label())."""
    return literal_column("(jobs.created_at AT TIME ZONE 'UTC')::date")


def _utc_date_take():
    """Expression: date(Take.created_at) in UTC for grouping (supports .label())."""
    return literal_column("(takes.created_at AT TIME ZONE 'UTC')::date")


@router.get("/telemetry")
def telemetry_dashboard(db: Session = Depends(get_db), window_hours: int = Query(24, ge=1, le=720)):
    since = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    users_total = db.query(func.count(User.id)).scalar() or 0
    users_subscribed = db.query(func.count(User.id)).filter(User.subscription_active.is_(True)).scalar() or 0
    jobs_total = db.query(func.count(Job.job_id)).scalar() or 0
    jobs_window, jobs_by_status = _telemetry_since(db, since)
    takes_window = (
        db.query(func.count(Take.id)).filter(Take.created_at >= since).scalar() or 0
    )
    succeeded = (
        db.query(func.count(Job.job_id))
        .filter(Job.status == "SUCCEEDED", Job.created_at >= since)
        .scalar()
        or 0
    )
    queue_length = (
        db.query(func.count(Job.job_id))
        .filter(Job.status.in_(["CREATED", "RUNNING"]), Job.created_at >= since)
        .scalar()
        or 0
    )
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
    # Глобальные счётчики Take за окно (включая снимки без trend_id)
    takes_succeeded = (
        db.query(func.count(Take.id))
        .filter(
            Take.created_at >= since,
            Take.status.in_(["ready", "partial_fail"]),
        )
        .scalar()
        or 0
    )
    takes_failed = (
        db.query(func.count(Take.id))
        .filter(Take.created_at >= since, Take.status == "failed")
        .scalar()
        or 0
    )
    # Среднее время генерации 3 снимков (одно значение на Take — по первому событию take_previews_ready)
    take_avg_generation_sec = None
    take_avg_q = (
        db.query(AuditLog.entity_id, AuditLog.created_at, Take.created_at)
        .join(Take, AuditLog.entity_id == Take.id)
        .filter(
            AuditLog.action == "take_previews_ready",
            AuditLog.entity_type == "take",
            AuditLog.created_at >= since,
        )
        .order_by(AuditLog.entity_id, AuditLog.created_at)
        .all()
    )
    if take_avg_q:
        utc = timezone.utc
        # Один срок на take (первое событие по entity_id), отрицательные длительности не учитываем
        seen_take_ids = set()
        diffs = []
        for entity_id, al_created, take_created in take_avg_q:
            if entity_id in seen_take_ids:
                continue
            seen_take_ids.add(entity_id)
            a = al_created.replace(tzinfo=utc) if al_created.tzinfo is None else al_created
            t = take_created.replace(tzinfo=utc) if take_created.tzinfo is None else take_created
            sec = (a - t).total_seconds()
            if sec >= 0:
                diffs.append(sec)
        if diffs:
            take_avg_generation_sec = round(sum(diffs) / len(diffs), 1)
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
        .filter(Job.status.in_(["FAILED", "ERROR"]), Job.created_at >= since)
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
        "takes_succeeded": takes_succeeded,
        "takes_failed": takes_failed,
        "take_avg_generation_sec": take_avg_generation_sec,
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
        .filter(Job.status.in_(["FAILED", "ERROR"]), Job.created_at >= since)
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

    # Распределение ошибок по датам за окно (UTC)
    day_j = _utc_date_job()
    day_t = _utc_date_take()
    jobs_by_day = (
        db.query(day_j.label("date"), func.count(Job.job_id).label("cnt"))
        .filter(Job.status.in_(["FAILED", "ERROR"]), Job.created_at >= since)
        .group_by(day_j)
        .all()
    )
    takes_by_day = (
        db.query(day_t.label("date"), func.count(Take.id).label("cnt"))
        .filter(Take.status == "failed", Take.created_at >= since)
        .group_by(day_t)
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
def telemetry_history(db: Session = Depends(get_db), window_days: int = Query(7, ge=1, le=90)):
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=window_days)
    day_j = _utc_date_job()
    q_jobs = (
        db.query(
            day_j.label("date"),
            func.count(Job.job_id).label("jobs_total"),
            func.sum(case((Job.status == "SUCCEEDED", 1), else_=0)).label("jobs_succeeded"),
            func.sum(case((Job.status.in_(["FAILED", "ERROR"]), 1), else_=0)).label("jobs_failed"),
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
        db.query(_utc_date_job().label("date"), Job.user_id)
        .filter(Job.created_at >= since, Job.user_id.isnot(None))
        .distinct()
        .all()
    )
    take_user_pairs = (
        db.query(_utc_date_take().label("date"), Take.user_id)
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
    day_t = _utc_date_take()
    takes_by_date = (
        db.query(day_t.label("date"), func.count(Take.id).label("cnt"))
        .filter(Take.created_at >= since)
        .group_by(day_t)
        .all()
    )
    takes_by_date_map = {str(r.date): r.cnt for r in takes_by_date}
    # Среднее время генерации 3 снимков по дням (Take created -> take_previews_ready)
    take_avg_rows = (
        db.query(Take.id, Take.created_at, AuditLog.created_at)
        .select_from(Take)
        .join(
            AuditLog,
            and_(
                AuditLog.entity_id == Take.id,
                AuditLog.entity_type == "take",
                AuditLog.action == "take_previews_ready",
            ),
        )
        .filter(Take.created_at >= since, AuditLog.created_at >= since)
        .order_by(Take.id, AuditLog.created_at)
        .all()
    )
    utc = timezone.utc
    take_diffs_by_date: dict[str, list[float]] = {}
    seen_per_date: dict[str, set[str]] = {}
    for take_id, take_created, audit_created in take_avg_rows:
        t = take_created.replace(tzinfo=utc) if take_created and take_created.tzinfo is None else take_created
        a = audit_created.replace(tzinfo=utc) if audit_created and audit_created.tzinfo is None else audit_created
        if t is None or a is None:
            continue
        date_key = str(t.date())
        if date_key not in seen_per_date:
            seen_per_date[date_key] = set()
        if take_id in seen_per_date[date_key]:
            continue
        seen_per_date[date_key].add(take_id)
        sec = (a - t).total_seconds()
        if sec >= 0:
            take_diffs_by_date.setdefault(date_key, []).append(sec)
    take_avg_by_date = {
        k: round(sum(v) / len(v), 1) for k, v in take_diffs_by_date.items() if v
    }
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
            "take_avg_generation_sec": take_avg_by_date.get(key),
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
def telemetry_product_metrics(db: Session = Depends(get_db), window_days: int = Query(7, ge=1, le=90)):
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


# ---------- Product analytics (from audit_logs — single event log) ----------
FUNNEL_EVENT_NAMES = list(TRACKED_FUNNEL_EVENT_NAMES)


def _audit_user_id_expr():
    """Expression: user identifier for funnel/metrics (user_id or entity_id when entity_type=user)."""
    return func.coalesce(
        AuditLog.user_id,
        case((AuditLog.entity_type == "user", AuditLog.entity_id), else_=None),
    )


def _utc_date_audit_log():
    """Expression: date(audit_logs.created_at) in UTC for grouping.
    Assumes created_at is stored as UTC (default in app is datetime.now(timezone.utc)).
    """
    return literal_column("(audit_logs.created_at AT TIME ZONE 'UTC')::date")


@router.get("/telemetry/product-funnel")
def telemetry_product_funnel(
    db: Session = Depends(get_db),
    window_days: int = Query(7, ge=1, le=90),
):
    """Funnel from audit_logs. Keeps legacy counts and adds session-only shadow + quality block."""
    since = datetime.now(timezone.utc) - timedelta(days=window_days)
    user_expr = _audit_user_id_expr()
    legacy_rows = (
        db.query(AuditLog.action, func.count(func.distinct(user_expr)).label("users"))
        .filter(AuditLog.created_at >= since, AuditLog.action.in_(FUNNEL_EVENT_NAMES))
        .group_by(AuditLog.action)
        .all()
    )
    shadow_rows = (
        db.query(AuditLog.action, func.count(func.distinct(user_expr)).label("users"))
        .filter(
            AuditLog.created_at >= since,
            AuditLog.action.in_(FUNNEL_EVENT_NAMES),
            AuditLog.session_id.isnot(None),
        )
        .group_by(AuditLog.action)
        .all()
    )
    event_rows = (
        db.query(AuditLog.action, AuditLog.session_id)
        .filter(AuditLog.created_at >= since, AuditLog.action.in_(FUNNEL_EVENT_NAMES))
        .all()
    )
    funnel_counts = {name: 0 for name in FUNNEL_EVENT_NAMES}
    shadow_funnel_counts = {name: 0 for name in FUNNEL_EVENT_NAMES}
    missing_session_events_by_step = {name: 0 for name in FUNNEL_EVENT_NAMES}
    for name, cnt in legacy_rows:
        funnel_counts[name] = cnt
    for name, cnt in shadow_rows:
        shadow_funnel_counts[name] = cnt
    total_funnel_events = 0
    missing_session_events = 0
    for action_name, session_id in event_rows:
        total_funnel_events += 1
        if not session_id:
            missing_session_events += 1
            if action_name in missing_session_events_by_step:
                missing_session_events_by_step[action_name] += 1
    session_coverage_pct = round(
        ((total_funnel_events - missing_session_events) / total_funnel_events * 100), 1
    ) if total_funnel_events else 100.0
    diff_funnel_counts = {
        name: int(shadow_funnel_counts.get(name, 0) - funnel_counts.get(name, 0))
        for name in FUNNEL_EVENT_NAMES
    }
    quality_warnings = []
    if missing_session_events > 0:
        quality_warnings.append(
            "Часть funnel-событий без session_id. Path/shadow-метрики могут быть ниже legacy."
        )
    return {
        "window_days": window_days,
        "funnel_counts": funnel_counts,
        "shadow_funnel_counts": shadow_funnel_counts,
        "diff_funnel_counts": diff_funnel_counts,
        "data_quality": {
            "required_session_id": True,
            "total_funnel_events": total_funnel_events,
            "missing_session_events": missing_session_events,
            "funnel_session_coverage_pct": session_coverage_pct,
            "missing_session_events_by_step": missing_session_events_by_step,
        },
        "quality_warnings": quality_warnings,
    }


@router.get("/telemetry/product-funnel-diff")
def telemetry_product_funnel_diff(
    db: Session = Depends(get_db),
    window_days: int = Query(7, ge=1, le=90),
):
    """Compatibility endpoint for explicit legacy-vs-shadow funnel comparison."""
    result = telemetry_product_funnel(db=db, window_days=window_days)
    return {
        "window_days": result["window_days"],
        "legacy_funnel_counts": result["funnel_counts"],
        "shadow_funnel_counts": result["shadow_funnel_counts"],
        "diff_funnel_counts": result["diff_funnel_counts"],
        "data_quality": result["data_quality"],
        "quality_warnings": result["quality_warnings"],
    }


@router.get("/telemetry/product-funnel-history")
def telemetry_product_funnel_history(
    db: Session = Depends(get_db),
    window_days: int = Query(30, ge=1, le=90),
):
    """Funnel event counts per day (from audit_logs) for historical chart."""
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=window_days)
    day_al = _utc_date_audit_log()
    user_expr = _audit_user_id_expr()
    rows = (
        db.query(
            day_al.label("date"),
            AuditLog.action,
            func.count(func.distinct(user_expr)).label("cnt"),
        )
        .filter(
            AuditLog.created_at >= since,
            AuditLog.action.in_(FUNNEL_EVENT_NAMES),
        )
        .group_by(day_al, AuditLog.action)
        .all()
    )
    by_date: dict[str, dict[str, int]] = {}
    for date_val, action_name, cnt in rows:
        key = str(date_val)
        if key not in by_date:
            by_date[key] = {name: 0 for name in FUNNEL_EVENT_NAMES}
        by_date[key][action_name] = cnt
    history = []
    for i in range(window_days + 1):
        d = (now - timedelta(days=window_days - i)).date()
        key = str(d)
        history.append({
            "date": key,
            **{name: by_date.get(key, {}).get(name, 0) for name in FUNNEL_EVENT_NAMES},
        })
    total_funnel_events = (
        db.query(func.count(AuditLog.id))
        .filter(AuditLog.created_at >= since, AuditLog.action.in_(FUNNEL_EVENT_NAMES))
        .scalar()
        or 0
    )
    missing_session_events = (
        db.query(func.count(AuditLog.id))
        .filter(
            AuditLog.created_at >= since,
            AuditLog.action.in_(FUNNEL_EVENT_NAMES),
            AuditLog.session_id.is_(None),
        )
        .scalar()
        or 0
    )
    session_coverage_pct = round(
        ((total_funnel_events - missing_session_events) / total_funnel_events * 100), 1
    ) if total_funnel_events else 100.0
    quality_warnings = []
    if missing_session_events > 0:
        quality_warnings.append("История включает funnel-события без session_id (legacy период).")
    return {
        "window_days": window_days,
        "history": history,
        "data_quality": {
            "total_funnel_events": total_funnel_events,
            "missing_session_events": missing_session_events,
            "funnel_session_coverage_pct": session_coverage_pct,
        },
        "quality_warnings": quality_warnings,
    }


# Max rows for path aggregation to avoid OOM/timeout on huge audit_logs (e.g. 90d × high traffic).
_PATH_QUERY_ROW_LIMIT = 500_000


def _load_path_rows(db: Session, since: datetime) -> tuple[list[Any], bool]:
    user_expr = _audit_user_id_expr()
    q = (
        db.query(
            AuditLog.session_id,
            user_expr.label("uid"),
            AuditLog.created_at,
            AuditLog.action,
        )
        .filter(
            AuditLog.created_at >= since,
            AuditLog.action.in_(FUNNEL_EVENT_NAMES),
        )
        .order_by(AuditLog.session_id.nulls_last(), user_expr, AuditLog.created_at, AuditLog.action)
    )
    rows = q.limit(_PATH_QUERY_ROW_LIMIT + 1).all()
    truncated = len(rows) > _PATH_QUERY_ROW_LIMIT
    if truncated:
        rows = rows[:_PATH_QUERY_ROW_LIMIT]
    return rows, truncated


def _path_transitions_and_sequences(
    db: Session,
    since: datetime,
    window_days: int,
    path_limit: int = 20,
    require_session: bool = False,
    rows: list[Any] | None = None,
    preloaded_truncated: bool | None = None,
) -> tuple[list[dict], list[dict], list[dict], bool, int]:
    """Load funnel events from audit_logs, return transitions/drop-off/paths plus truncated and excluded count."""
    if rows is None:
        rows, truncated = _load_path_rows(db, since)
    else:
        truncated = bool(preloaded_truncated)
    # Group by session (legacy fallback: by user when session missing).
    sessions: dict[str, list[tuple[datetime, str]]] = {}
    excluded_without_session = 0
    for r in rows:
        if require_session:
            if not r.session_id:
                excluded_without_session += 1
                continue
            key = r.session_id
        elif r.session_id:
            key = r.session_id
        elif r.uid:
            key = f"u:{r.uid}"
        else:
            continue
        ts = _as_utc(r.created_at) or r.created_at
        if key not in sessions:
            sessions[key] = []
        sessions[key].append((ts, r.action))
    # Sort each session by (created_at, action) for deterministic order when timestamps tie.
    for key in sessions:
        sessions[key].sort(key=lambda x: (x[0], x[1]))

    transitions_agg: dict[tuple[str, str], list[float]] = {}
    drop_off_agg: dict[str, int] = {}
    path_counts: dict[str, list[tuple[float | None, float]]] = {}

    for _key, events in sessions.items():
        if not events:
            continue
        # Transitions and drop-off
        for i in range(len(events) - 1):
            from_act, to_act = events[i][1], events[i + 1][1]
            delta_min = (events[i + 1][0] - events[i][0]).total_seconds() / 60.0
            if delta_min < 0:
                continue
            k = (from_act, to_act)
            transitions_agg.setdefault(k, []).append(delta_min)
        last_action = events[-1][1]
        if last_action not in ("pay_success", "hd_delivered"):
            drop_off_agg[last_action] = drop_off_agg.get(last_action, 0) + 1

        # Path sequence: time to pay_success (if any), time to last step
        path_steps = [e[1] for e in events]
        path_str = "|".join(path_steps)
        first_ts = events[0][0]
        time_to_pay: float | None = None
        for j, (ts, act) in enumerate(events):
            if act == "pay_success":
                time_to_pay = (ts - first_ts).total_seconds() / 60.0
                break
        time_to_last = (events[-1][0] - first_ts).total_seconds() / 60.0
        if path_str not in path_counts:
            path_counts[path_str] = []
        path_counts[path_str].append((time_to_pay, time_to_last))

    def _median(values: list[float]) -> float | None:
        if not values:
            return None
        s = sorted(values)
        n = len(s)
        return (s[(n - 1) // 2] + s[n // 2]) / 2.0 if n % 2 == 0 else s[n // 2]

    transitions = [
        {
            "from": from_act,
            "to": to_act,
            "sessions": len(deltas),
            "median_minutes": round(_median(deltas), 1) if _median(deltas) is not None else None,
            "avg_minutes": round(sum(deltas) / len(deltas), 1) if deltas else None,
        }
        for (from_act, to_act), deltas in transitions_agg.items()
    ]
    drop_off = [
        {"from": act, "to": None, "sessions": cnt}
        for act, cnt in sorted(drop_off_agg.items(), key=lambda x: -x[1])
    ]
    paths_list: list[dict] = []
    for path_str, pairs in path_counts.items():
        steps = path_str.split("|")
        to_pay = [p[0] for p in pairs if p[0] is not None]
        to_last = [p[1] for p in pairs]
        reached_pay = len(to_pay)
        paths_list.append({
            "steps": steps,
            "sessions": len(pairs),
            "median_minutes_to_pay": round(_median(to_pay), 1) if to_pay and _median(to_pay) is not None else None,
            "median_minutes_to_last": round(_median(to_last), 1) if to_last and _median(to_last) is not None else None,
            "pct_reached_pay": round(100.0 * reached_pay / len(pairs), 1) if pairs else 0,
        })
    paths_list.sort(key=lambda x: -x["sessions"])
    path_sequences = paths_list[:path_limit]
    return transitions, drop_off, path_sequences, truncated, excluded_without_session


@router.get("/telemetry/path-transitions")
def telemetry_path_transitions(
    db: Session = Depends(get_db),
    window_days: int = Query(7, ge=1, le=90),
):
    """Transitions between funnel steps with session counts and median/avg time in minutes. Source: audit_logs."""
    try:
        since = datetime.now(timezone.utc) - timedelta(days=window_days)
        transitions, drop_off, _, truncated, _ = _path_transitions_and_sequences(db, since, window_days)
        shadow_transitions, shadow_drop_off, _, shadow_truncated, excluded = _path_transitions_and_sequences(
            db, since, window_days, require_session=True
        )
        return {
            "window_days": window_days,
            "transitions": transitions,
            "drop_off": drop_off,
            "truncated": truncated,
            "shadow": {
                "transitions": shadow_transitions,
                "drop_off": shadow_drop_off,
                "truncated": shadow_truncated,
            },
            "data_quality": {
                "excluded_without_session_events": excluded,
                "required_session_id_for_shadow": True,
            },
        }
    except Exception as e:
        logger.exception("telemetry path-transitions failed: window_days=%s", window_days)
        raise HTTPException(status_code=503, detail="Path aggregation failed; try a smaller window.") from e


@router.get("/telemetry/path-sequences")
def telemetry_path_sequences(
    db: Session = Depends(get_db),
    window_days: int = Query(7, ge=1, le=90),
    limit: int = Query(20, ge=1, le=50),
):
    """Top path sequences with session count, median time to pay/last, pct reached pay. Source: audit_logs."""
    try:
        since = datetime.now(timezone.utc) - timedelta(days=window_days)
        _, _, path_sequences, truncated, _ = _path_transitions_and_sequences(
            db, since, window_days, path_limit=limit
        )
        _, _, shadow_paths, shadow_truncated, excluded = _path_transitions_and_sequences(
            db, since, window_days, path_limit=limit, require_session=True
        )
        return {
            "window_days": window_days,
            "paths": path_sequences,
            "truncated": truncated,
            "shadow_paths": shadow_paths,
            "shadow_truncated": shadow_truncated,
            "data_quality": {
                "excluded_without_session_events": excluded,
                "required_session_id_for_shadow": True,
            },
        }
    except Exception as e:
        logger.exception("telemetry path-sequences failed: window_days=%s", window_days)
        raise HTTPException(status_code=503, detail="Path aggregation failed; try a smaller window.") from e


@router.get("/telemetry/path")
def telemetry_path(
    db: Session = Depends(get_db),
    window_days: int = Query(7, ge=1, le=90),
    limit: int = Query(20, ge=1, le=50),
):
    """Single call returning both path-transitions and path-sequences to avoid double heavy aggregation."""
    try:
        since = datetime.now(timezone.utc) - timedelta(days=window_days)
        rows, truncated = _load_path_rows(db, since)
        transitions, drop_off, path_sequences, truncated, _ = _path_transitions_and_sequences(
            db, since, window_days, path_limit=limit, rows=rows, preloaded_truncated=truncated
        )
        shadow_transitions, shadow_drop_off, shadow_paths, shadow_truncated, excluded = _path_transitions_and_sequences(
            db,
            since,
            window_days,
            path_limit=limit,
            require_session=True,
            rows=rows,
            preloaded_truncated=truncated,
        )
        return {
            "window_days": window_days,
            "transitions": transitions,
            "drop_off": drop_off,
            "paths": path_sequences,
            "truncated": truncated,
            "shadow": {
                "transitions": shadow_transitions,
                "drop_off": shadow_drop_off,
                "paths": shadow_paths,
                "truncated": shadow_truncated,
            },
            "data_quality": {
                "excluded_without_session_events": excluded,
                "required_session_id_for_shadow": True,
            },
        }
    except Exception as e:
        logger.exception("telemetry path failed: window_days=%s", window_days)
        raise HTTPException(status_code=503, detail="Path aggregation failed; try a smaller window.") from e


@router.get("/telemetry/button-clicks")
def telemetry_button_clicks(
    db: Session = Depends(get_db),
    window_days: int = Query(7, ge=1, le=90),
):
    """Count of button_click events per button_id (from audit_logs.payload) in window."""
    since = datetime.now(timezone.utc) - timedelta(days=window_days)
    button_col = func.coalesce(AuditLog.payload["button_id"].astext, "")
    rows = (
        db.query(button_col.label("button_id"), func.count(AuditLog.id).label("count"))
        .filter(
            AuditLog.action == "button_click",
            AuditLog.created_at >= since,
        )
        .group_by(button_col)
        .all()
    )
    by_button_id = {r.button_id: r.count for r in rows if r.button_id}
    total_button_events = int(sum(int(r.count or 0) for r in rows))
    missing_button_id_events = int(sum(int(r.count or 0) for r in rows if not r.button_id))
    unknown_by_button_id = {
        bid: int(cnt)
        for bid, cnt in by_button_id.items()
        if not is_known_button_id(bid)
    }
    unknown_button_id_events = int(sum(unknown_by_button_id.values()))
    known_button_id_events = max(0, total_button_events - missing_button_id_events - unknown_button_id_events)
    coverage_pct = round((known_button_id_events / total_button_events * 100), 1) if total_button_events else 100.0
    quality_warnings: list[str] = []
    if missing_button_id_events > 0:
        quality_warnings.append("Есть button_click без button_id.")
    if unknown_button_id_events > 0:
        quality_warnings.append("Есть button_click с неизвестными button_id (не в registry).")
    return {
        "window_days": window_days,
        "by_button_id": by_button_id,
        "unknown_by_button_id": unknown_by_button_id,
        "data_quality": {
            "total_button_click_events": total_button_events,
            "missing_button_id_events": missing_button_id_events,
            "unknown_button_id_events": unknown_button_id_events,
            "button_id_coverage_pct": coverage_pct,
        },
        "quality_warnings": quality_warnings,
    }


def _safe_price_from_payload(props: dict | None) -> int:
    rate = max(float(getattr(app_settings, "star_to_rub", 1.3) or 1.3), 0.01)
    stars, _rub, _valid = _extract_payment_amounts(props, rate)
    return stars


def _extract_payment_amounts(props: dict | None, star_to_rub: float) -> tuple[int, float, bool]:
    p = props if isinstance(props, dict) else {}

    def _to_float(value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    stars = 0.0
    for key in ("price", "price_stars", "stars"):
        v = _to_float(p.get(key))
        if v > 0:
            stars = v
            break
    rub = 0.0
    for key in ("price_rub", "amount_rub"):
        v = _to_float(p.get(key))
        if v > 0:
            rub = v
            break
    if rub <= 0:
        amount_kopecks = _to_float(p.get("amount_kopecks"))
        if amount_kopecks > 0:
            rub = amount_kopecks / 100.0
    if stars <= 0 and rub > 0:
        stars = rub / star_to_rub
    if rub <= 0 and stars > 0:
        rub = stars * star_to_rub
    valid = stars > 0 or rub > 0
    return int(round(stars)) if stars > 0 else 0, round(rub, 2), valid


@router.get("/telemetry/health")
def telemetry_health(
    db: Session = Depends(get_db),
    window_days: int = Query(7, ge=1, le=90),
):
    """Telemetry collection health for product loops (coverage + schema quality)."""
    since = datetime.now(timezone.utc) - timedelta(days=window_days)
    total_events = (
        db.query(func.count(AuditLog.id))
        .filter(AuditLog.actor_type == "user", AuditLog.created_at >= since)
        .scalar()
        or 0
    )
    funnel_events = (
        db.query(func.count(AuditLog.id))
        .filter(
            AuditLog.actor_type == "user",
            AuditLog.created_at >= since,
            AuditLog.action.in_(FUNNEL_EVENT_NAMES),
        )
        .scalar()
        or 0
    )
    funnel_missing_session = (
        db.query(func.count(AuditLog.id))
        .filter(
            AuditLog.actor_type == "user",
            AuditLog.created_at >= since,
            AuditLog.action.in_(FUNNEL_EVENT_NAMES),
            AuditLog.session_id.is_(None),
        )
        .scalar()
        or 0
    )
    funnel_session_coverage_pct = round(
        ((funnel_events - funnel_missing_session) / funnel_events * 100), 1
    ) if funnel_events else 100.0

    button_col = func.coalesce(AuditLog.payload["button_id"].astext, "")
    button_rows = (
        db.query(button_col.label("button_id"), func.count(AuditLog.id).label("count"))
        .filter(
            AuditLog.actor_type == "user",
            AuditLog.action == "button_click",
            AuditLog.created_at >= since,
        )
        .group_by(button_col)
        .all()
    )
    button_events = int(sum(int(r.count or 0) for r in button_rows))
    button_missing_id = int(sum(int(r.count or 0) for r in button_rows if not r.button_id))
    button_unknown_id = int(
        sum(int(r.count or 0) for r in button_rows if r.button_id and not is_known_button_id(r.button_id))
    )
    known_button_events = max(0, button_events - button_missing_id - button_unknown_id)
    button_id_coverage_pct = round((known_button_events / button_events * 100), 1) if button_events else 100.0

    rate = max(float(getattr(app_settings, "star_to_rub", 1.3) or 1.3), 0.01)
    pay_success_rows = (
        db.query(AuditLog.payload)
        .filter(
            AuditLog.actor_type == "user",
            AuditLog.action == "pay_success",
            AuditLog.created_at >= since,
        )
        .all()
    )
    pay_success_valid_price = 0
    for (props,) in pay_success_rows:
        _stars, _rub, valid = _extract_payment_amounts(props, rate)
        if valid:
            pay_success_valid_price += 1
    pay_success_events = len(pay_success_rows)
    pay_success_valid_price_pct = round(
        (pay_success_valid_price / pay_success_events * 100), 1
    ) if pay_success_events else 100.0

    deprecated_schema_events = 0
    unknown_events = 0
    schema_col = func.coalesce(AuditLog.payload["schema_version"].astext, "").label("schema_version")
    schema_rows = (
        db.query(
            AuditLog.action.label("action"),
            schema_col,
            func.count(AuditLog.id).label("count"),
        )
        .filter(AuditLog.actor_type == "user", AuditLog.created_at >= since)
        .group_by(AuditLog.action, schema_col)
        .all()
    )
    for r in schema_rows:
        schema_raw = r.schema_version
        try:
            schema_version = int(schema_raw)
        except (TypeError, ValueError):
            schema_version = 0
        if schema_version < PRODUCT_ANALYTICS_SCHEMA_VERSION:
            deprecated_schema_events += int(r.count or 0)
        if schema_version >= PRODUCT_ANALYTICS_SCHEMA_VERSION and not is_known_product_event(r.action):
            unknown_events += int(r.count or 0)
    deprecated_schema_pct = round(
        (deprecated_schema_events / total_events * 100), 1
    ) if total_events else 0.0
    unknown_events_pct = round((unknown_events / total_events * 100), 1) if total_events else 0.0

    quality_warnings: list[str] = []
    if funnel_session_coverage_pct < 95:
        quality_warnings.append("Низкая полнота session_id в funnel-событиях (<95%).")
    if button_id_coverage_pct < 98:
        quality_warnings.append("Есть заметные потери button_id в button_click (<98%).")
    if pay_success_valid_price_pct < 98:
        quality_warnings.append("Есть pay_success без валидной цены (<98%).")
    if unknown_events_pct > 1:
        quality_warnings.append("Есть события с неизвестными event_name в новой схеме (>1%).")
    if deprecated_schema_pct > 25:
        quality_warnings.append("Высокая доля legacy-событий без schema_version (forward-only период).")
    status = "ok" if not quality_warnings else "degraded"

    data_quality = {
        "total_events": total_events,
        "funnel_events": funnel_events,
        "funnel_missing_session_events": funnel_missing_session,
        "funnel_session_coverage_pct": funnel_session_coverage_pct,
        "button_click_events": button_events,
        "button_missing_id_events": button_missing_id,
        "button_unknown_id_events": button_unknown_id,
        "button_id_coverage_pct": button_id_coverage_pct,
        "pay_success_events": pay_success_events,
        "pay_success_valid_price_events": pay_success_valid_price,
        "pay_success_valid_price_pct": pay_success_valid_price_pct,
        "unknown_events": unknown_events,
        "unknown_events_pct": unknown_events_pct,
        "deprecated_schema_events": deprecated_schema_events,
        "deprecated_schema_pct": deprecated_schema_pct,
    }
    return {
        "window_days": window_days,
        "status": status,
        "data_quality": data_quality,
        "metrics": data_quality,
        "quality_warnings": quality_warnings,
    }


@router.get("/telemetry/overview-v3")
def telemetry_overview_v3(
    db: Session = Depends(get_db),
    window: str = Query("7d", description="24h|7d|30d|90d"),
    source: str | None = Query(None),
    campaign: str | None = Query(None),
    entry_type: str | None = Query(None),
    flow_mode: str = Query("canonical_only", description="canonical_only|all_flows"),
    trust_mode: str = Query("trusted_only", description="trusted_only|all_data"),
):
    if window not in {"24h", "7d", "30d", "90d"}:
        raise HTTPException(400, "window must be one of: 24h, 7d, 30d, 90d")
    if flow_mode not in {"canonical_only", "all_flows"}:
        raise HTTPException(400, "flow_mode must be canonical_only|all_flows")
    if trust_mode not in {"trusted_only", "all_data"}:
        raise HTTPException(400, "trust_mode must be trusted_only|all_data")
    try:
        return build_overview_v3(
            db=db,
            window=window,  # type: ignore[arg-type]
            source=source,
            campaign=campaign,
            entry_type=entry_type,
            flow_mode=flow_mode,  # type: ignore[arg-type]
            trust_mode=trust_mode,  # type: ignore[arg-type]
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:
        logger.exception("telemetry overview-v3 failed")
        raise HTTPException(status_code=503, detail="overview-v3 aggregation failed; try a smaller window or fewer filters.") from e


@router.get("/telemetry/product-metrics-v2")
def telemetry_product_metrics_v2(
    db: Session = Depends(get_db),
    window_days: int = Query(7, ge=1, le=90),
):
    """Calculated product metrics from audit_logs: preview_to_pay, hit_rate, AOV, etc."""
    since = datetime.now(timezone.utc) - timedelta(days=window_days)
    user_expr = _audit_user_id_expr()
    # Counts
    take_preview = (
        db.query(func.count(AuditLog.id))
        .filter(AuditLog.action == "take_preview_ready", AuditLog.created_at >= since)
        .scalar()
        or 0
    )
    pay_success_count = (
        db.query(func.count(AuditLog.id))
        .filter(AuditLog.action == "pay_success", AuditLog.created_at >= since)
        .scalar()
        or 0
    )
    preview_to_pay = round((pay_success_count / take_preview * 100), 1) if take_preview else 0.0
    sessions_with_preview = (
        db.query(func.count(func.distinct(AuditLog.session_id)))
        .filter(
            AuditLog.action == "take_preview_ready",
            AuditLog.created_at >= since,
            AuditLog.session_id.isnot(None),
        )
        .scalar()
        or 0
    )
    sessions_with_favorite = (
        db.query(func.count(func.distinct(AuditLog.session_id)))
        .filter(
            AuditLog.action == "favorite_selected",
            AuditLog.created_at >= since,
            AuditLog.session_id.isnot(None),
        )
        .scalar()
        or 0
    )
    hit_rate = round((sessions_with_favorite / sessions_with_preview * 100), 1) if sessions_with_preview else 0.0
    pay_events = (
        db.query(AuditLog.payload)
        .filter(AuditLog.action == "pay_success", AuditLog.created_at >= since)
        .all()
    )
    rate = max(float(getattr(app_settings, "star_to_rub", 1.3) or 1.3), 0.01)
    pay_amounts = [_extract_payment_amounts(p[0], rate) for p in pay_events]
    total_stars = sum(a[0] for a in pay_amounts)
    valid_price_events = sum(1 for a in pay_amounts if a[2])
    aov_stars = round(total_stars / pay_success_count, 1) if pay_success_count else 0.0
    likeness_events = (
        db.query(AuditLog.payload)
        .filter(
            AuditLog.action == "generation_likeness_feedback",
            AuditLog.created_at >= since,
        )
        .all()
    )
    total_likeness = len(likeness_events)
    likeness_yes = sum(
        1
        for p in likeness_events
        if isinstance(p[0], dict) and p[0].get("likeness") == "yes"
    )
    likeness_score = round((likeness_yes / total_likeness * 100), 1) if total_likeness else 0.0
    pay_per_user = (
        db.query(user_expr, func.count(AuditLog.id))
        .filter(AuditLog.action == "pay_success", AuditLog.created_at >= since)
        .group_by(user_expr)
        .all()
    )
    paying_users = len(pay_per_user)
    users_2plus = sum(1 for _u, c in pay_per_user if c >= 2)
    repeat_purchase_rate = round((users_2plus / paying_users * 100), 1) if paying_users else 0.0
    users_started = (
        db.query(func.count(func.distinct(user_expr)))
        .filter(AuditLog.action == "bot_started", AuditLog.created_at >= since)
        .scalar()
        or 0
    )
    avg_time_start_to_result_sec = None
    avg_steps_start_to_result = None
    start_result_rows = (
        db.query(user_expr.label("uid"), AuditLog.action, AuditLog.created_at)
        .filter(
            AuditLog.action.in_(["bot_started", "favorite_selected"]),
            AuditLog.created_at >= since,
        )
        .all()
    )
    by_user: dict[str, dict[str, Any]] = {}
    for row in start_result_rows:
        uid, action_name, ts = row.uid, row.action, row.created_at
        if uid not in by_user:
            by_user[uid] = {"start_ts": None, "result_ts": None}
        if action_name == "bot_started" and (by_user[uid]["start_ts"] is None or ts < by_user[uid]["start_ts"]):
            by_user[uid]["start_ts"] = ts
        if action_name == "favorite_selected" and (by_user[uid]["result_ts"] is None or ts < by_user[uid]["result_ts"]):
            by_user[uid]["result_ts"] = ts
    valid_users = [
        (uid, data["start_ts"], data["result_ts"])
        for uid, data in by_user.items()
        if uid is not None
        and data["start_ts"] is not None
        and data["result_ts"] is not None
        and data["result_ts"] >= data["start_ts"]
    ]
    _max_users_start_to_result = 2000
    if len(valid_users) > _max_users_start_to_result:
        valid_users = sorted(valid_users, key=lambda u: u[2], reverse=True)[:_max_users_start_to_result]
    if valid_users:
        # Normalize to str so IN clause and dict keys match regardless of DB type (UUID vs text)
        user_ids = [str(u[0]) for u in valid_users]
        all_events_in_window = (
            db.query(user_expr.label("uid"), AuditLog.created_at)
            .filter(user_expr.in_(user_ids), AuditLog.created_at >= since)
            .all()
        )
        events_by_user: dict[str, list[datetime]] = {uid: [] for uid in user_ids}
        for row in all_events_in_window:
            events_by_user.setdefault(str(row.uid), []).append(row.created_at)
        durations = []
        steps_list = []
        for uid, start_ts, result_ts in valid_users:
            durations.append((result_ts - start_ts).total_seconds())
            steps_list.append(sum(1 for t in events_by_user.get(str(uid), []) if start_ts <= t <= result_ts))
        avg_time_start_to_result_sec = round(sum(durations) / len(durations), 1)
        avg_steps_start_to_result = round(sum(steps_list) / len(steps_list), 1)
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
        "avg_time_start_to_result_sec": avg_time_start_to_result_sec,
        "avg_steps_start_to_result": avg_steps_start_to_result,
        "data_quality": {
            "pay_success_valid_price_events": valid_price_events,
            "pay_success_events": pay_success_count,
            "pay_success_valid_price_pct": round((valid_price_events / pay_success_count * 100), 1) if pay_success_count else 100.0,
        },
    }


@router.get("/telemetry/revenue")
def telemetry_revenue(
    db: Session = Depends(get_db),
    window_days: int = Query(30, ge=1, le=90),
):
    """Revenue by pack and by source from audit_logs pay_success (payload.pack_id, payload.source, payload.price)."""
    since = datetime.now(timezone.utc) - timedelta(days=window_days)
    events = (
        db.query(AuditLog.payload)
        .filter(AuditLog.action == "pay_success", AuditLog.created_at >= since)
        .all()
    )
    by_pack: dict[str, int] = {}
    by_source: dict[str, int] = {}
    total_stars = 0
    total_rub = 0.0
    valid_price_events = 0
    invalid_price_events = 0
    rate = max(float(getattr(app_settings, "star_to_rub", 1.3) or 1.3), 0.01)
    for (props,) in events:
        p = props if isinstance(props, dict) else {}
        stars, rub, valid = _extract_payment_amounts(props, rate)
        total_stars += stars
        total_rub += rub
        if valid:
            valid_price_events += 1
        else:
            invalid_price_events += 1
        pack_key = p.get("pack_id") or "unknown"
        by_pack[pack_key] = by_pack.get(pack_key, 0) + stars
        src_key = p.get("source") or "organic"
        by_source[src_key] = by_source.get(src_key, 0) + stars
    quality_warnings = []
    if invalid_price_events > 0:
        quality_warnings.append("Часть pay_success без валидной цены. Revenue может быть занижен.")
    return {
        "window_days": window_days,
        "total_stars": total_stars,
        "revenue_rub_approx": round(total_rub if total_rub > 0 else total_stars * rate, 2),
        "by_pack": by_pack,
        "by_source": by_source,
        "data_quality": {
            "pay_success_events": len(events),
            "valid_price_events": valid_price_events,
            "invalid_price_events": invalid_price_events,
            "valid_price_pct": round((valid_price_events / len(events) * 100), 1) if events else 100.0,
        },
        "quality_warnings": quality_warnings,
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
def bank_transfer_settings_put(
    payload: dict,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    svc = BankTransferSettingsService(db)
    result = svc.update(payload)
    _admin_audit(db, current_user, "update", "settings", None, {"section": "bank_transfer"})
    return result


@router.get("/bank-transfer/pay-initiated")
def bank_transfer_pay_initiated(
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    date_from: date | None = Query(None, description="Start date (UTC, inclusive)"),
    date_to: date | None = Query(None, description="End date (UTC, inclusive)"),
    price_rub: float | None = Query(None, description="Filter by expected amount in RUB, e.g. 99 or 199"),
    telegram_user_id: str | None = Query(None, description="Filter by Telegram user ID"),
):
    """List pay_initiated events for bank_transfer (from audit_logs). Used to find who initiated a transfer by date/sum."""
    if date_from is not None and date_to is not None and date_to < date_from:
        raise HTTPException(400, "date_to must be >= date_from")
    if telegram_user_id is not None:
        telegram_user_id = telegram_user_id.strip() or None

    q = (
        db.query(AuditLog, User.telegram_id, User.telegram_username)
        .outerjoin(User, AuditLog.user_id == User.id)
        .filter(
            AuditLog.action == "pay_initiated",
            AuditLog.payload["method"].astext == "bank_transfer",
        )
    )
    if date_from is not None:
        ts_from = datetime.combine(date_from, datetime.min.time()).replace(tzinfo=timezone.utc)
        q = q.filter(AuditLog.created_at >= ts_from)
    if date_to is not None:
        ts_to = datetime.combine(date_to, datetime.max.time()).replace(tzinfo=timezone.utc)
        q = q.filter(AuditLog.created_at <= ts_to)
    if price_rub is not None:
        # payload.price_rub may be stored as JSON number or string; COALESCE both for filter
        price_rub_expr = literal_column(
            "(COALESCE((audit_logs.payload->>'price_rub'), (audit_logs.payload->'price_rub')::text))::numeric(12,2)"
        )
        q = q.filter(price_rub_expr == price_rub)
    if telegram_user_id:
        q = q.filter(User.telegram_id == telegram_user_id)
    total = q.count()
    q = q.order_by(AuditLog.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    rows = q.all()
    items = []
    for al, tg_id, tg_username in rows:
        props = al.payload or {}
        price_rub_val = props.get("price_rub")
        if price_rub_val is not None and not isinstance(price_rub_val, (int, float)):
            try:
                price_rub_val = float(price_rub_val)
            except (TypeError, ValueError):
                price_rub_val = None
        items.append({
            "id": al.id,
            "user_id": al.user_id,
            "telegram_id": tg_id,
            "telegram_username": tg_username,
            "timestamp": al.created_at.isoformat() if al.created_at else None,
            "pack_id": props.get("pack_id"),
            "price_rub": price_rub_val,
        })
    return {"items": items, "total": total, "page": page, "pages": (total + page_size - 1) // page_size}


@router.get("/bank-transfer/receipt-logs")
def bank_transfer_receipt_logs(
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    match_success: bool | None = None,
    telegram_user_id: str | None = None,
    expected_rub: float | None = Query(None, description="Filter by expected amount in RUB, e.g. 99 or 199"),
    date_from: date | None = Query(None, description="Start date (UTC, inclusive)"),
    date_to: date | None = Query(None, description="End date (UTC, inclusive)"),
):
    if date_from is not None and date_to is not None and date_to < date_from:
        raise HTTPException(400, "date_to must be >= date_from")
    if telegram_user_id is not None:
        telegram_user_id = telegram_user_id.strip() or None

    q = db.query(BankTransferReceiptLog)
    if match_success is not None:
        q = q.filter(BankTransferReceiptLog.match_success == match_success)
    if telegram_user_id:
        q = q.filter(BankTransferReceiptLog.telegram_user_id == telegram_user_id)
    if expected_rub is not None:
        q = q.filter(BankTransferReceiptLog.expected_rub == expected_rub)
    if date_from is not None:
        ts_from = datetime.combine(date_from, datetime.min.time()).replace(tzinfo=timezone.utc)
        q = q.filter(BankTransferReceiptLog.created_at >= ts_from)
    if date_to is not None:
        ts_to = datetime.combine(date_to, datetime.max.time()).replace(tzinfo=timezone.utc)
        q = q.filter(BankTransferReceiptLog.created_at <= ts_to)
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
            "card_match_success": r.card_match_success,
            "extracted_card_first4": r.extracted_card_first4,
            "extracted_card_last4": r.extracted_card_last4,
            "extracted_receipt_dt": r.extracted_receipt_dt.isoformat() if r.extracted_receipt_dt else None,
            "extracted_comment": r.extracted_comment,
            "comment_match_success": r.comment_match_success,
        })
    return {"items": items, "total": total, "page": page, "pages": (total + page_size - 1) // page_size}


def _receipt_file_path_safe(row_file_path: str) -> str:
    """Resolve receipt file path and ensure it is under storage_base_path (prevent path traversal)."""
    base = getattr(app_settings, "storage_base_path", "") or ""
    if not base:
        raise HTTPException(404, "Storage not configured")
    if os.path.isabs(row_file_path):
        path = row_file_path
    else:
        path = os.path.join(base, row_file_path)
    real_path = os.path.realpath(path)
    real_base = os.path.realpath(base)
    if not real_path.startswith(real_base + os.sep) and real_path != real_base:
        raise HTTPException(404, "File not found")
    return real_path


@router.get("/bank-transfer/receipt-logs/{log_id}/file")
def bank_transfer_receipt_log_file(log_id: str, db: Session = Depends(get_db)):
    row = db.query(BankTransferReceiptLog).filter(BankTransferReceiptLog.id == log_id).first()
    if not row or not row.file_path:
        raise HTTPException(404, "Log or file not found")
    base = getattr(app_settings, "storage_base_path", "") or ""
    if not base:
        raise HTTPException(404, "Storage not configured")
    real_base = os.path.realpath(base)
    path = None
    try:
        candidate = _receipt_file_path_safe(row.file_path)
        if os.path.isfile(candidate):
            path = candidate
    except HTTPException:
        pass
    if not path and not os.path.isabs(row.file_path):
        fallback = os.path.join(base, "receipts", os.path.basename(row.file_path))
        real_fallback = os.path.realpath(fallback)
        if real_fallback.startswith(real_base + os.sep) and os.path.isfile(fallback):
            path = fallback
    if not path or not os.path.isfile(path):
        raise HTTPException(404, "File not found")
    return FileResponse(path, filename=os.path.basename(path))


# ---------- Payments ----------
def _payment_method_from_row(p: Payment) -> str:
    """Определить способ оплаты по записи Payment (stars / yoomoney / bank_transfer / yookassa_link / yookassa_unlock)."""
    if p.payload and p.payload.startswith("bank_transfer:"):
        return "bank_transfer"
    if p.telegram_payment_charge_id and p.telegram_payment_charge_id.startswith("yoomoney:"):
        return "yoomoney"
    if p.telegram_payment_charge_id and p.telegram_payment_charge_id.startswith("yookassa_unlock:"):
        return "yookassa_unlock"
    if p.telegram_payment_charge_id and p.telegram_payment_charge_id.startswith("yookassa_link:"):
        return "yookassa_link"
    return "stars"


@router.get("/payments")
def payments_list(
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    payment_method: str | None = None,
    date_from: date | None = Query(None, description="Start date (UTC, inclusive)"),
    date_to: date | None = Query(None, description="End date (UTC, inclusive)"),
):
    if date_from is not None and date_to is not None and date_to < date_from:
        raise HTTPException(400, "date_to must be >= date_from")
    q = db.query(Payment)
    if payment_method:
        if payment_method == "stars":
            q = q.filter(
                Payment.telegram_payment_charge_id.isnot(None),
                ~Payment.telegram_payment_charge_id.like("yoomoney:%"),
                ~Payment.telegram_payment_charge_id.like("yookassa_link:%"),
                ~Payment.telegram_payment_charge_id.like("yookassa_unlock:%"),
                ~Payment.payload.like("bank_transfer:%"),
            )
        elif payment_method == "yoomoney":
            q = q.filter(Payment.telegram_payment_charge_id.like("yoomoney:%"))
        elif payment_method == "bank_transfer":
            q = q.filter(Payment.payload.like("bank_transfer:%"))
        elif payment_method == "yookassa_link":
            q = q.filter(Payment.telegram_payment_charge_id.like("yookassa_link:%"))
        elif payment_method == "yookassa_unlock":
            q = q.filter(Payment.telegram_payment_charge_id.like("yookassa_unlock:%"))
    if date_from is not None:
        ts_from = datetime.combine(date_from, datetime.min.time()).replace(tzinfo=timezone.utc)
        q = q.filter(Payment.created_at >= ts_from)
    if date_to is not None:
        ts_to = datetime.combine(date_to, datetime.max.time()).replace(tzinfo=timezone.utc)
        q = q.filter(Payment.created_at <= ts_to)
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
            "amount_kopecks": p.amount_kopecks,
            "tokens_granted": p.tokens_granted,
            "status": p.status,
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "payment_method": _payment_method_from_row(p),
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
        Payment.status == "completed",
        Payment.created_at >= since,
        ~Payment.telegram_payment_charge_id.like("yoomoney:%"),
        ~Payment.telegram_payment_charge_id.like("yookassa_link:%"),
        ~Payment.telegram_payment_charge_id.like("yookassa_unlock:%"),
        ~Payment.payload.like("bank_transfer:%"),
    ).scalar() or 0
    total_rub_yoomoney = db.query(func.coalesce(func.sum(Payment.amount_kopecks), 0)).filter(
        Payment.status == "completed",
        Payment.created_at >= since,
        Payment.telegram_payment_charge_id.like("yoomoney:%"),
    ).scalar() or 0
    total_rub_yoomoney_rub = int(total_rub_yoomoney) / 100.0
    total_rub_all_kopecks = db.query(func.coalesce(func.sum(Payment.amount_kopecks), 0)).filter(
        Payment.status == "completed",
        Payment.created_at >= since,
    ).scalar() or 0
    total_rub_all_rub = int(total_rub_all_kopecks) / 100.0
    refunded = db.query(func.count(Payment.id)).filter(
        Payment.status == "refunded", Payment.created_at >= since
    ).scalar() or 0
    unique_buyers = db.query(func.count(func.distinct(Payment.user_id))).filter(
        Payment.status == "completed", Payment.created_at >= since
    ).scalar() or 0
    revenue_usd = float(total_stars) * STAR_USD_RATE
    revenue_rub_stars = float(total_stars) * STAR_RUB_RATE
    revenue_rub_total = revenue_rub_stars + total_rub_all_rub
    by_pack_rows = (
        db.query(Payment.pack_id, func.count(Payment.id).label("cnt"), func.coalesce(func.sum(Payment.stars_amount), 0).label("stars"), func.coalesce(func.sum(Payment.amount_kopecks), 0).label("rub_kopecks"))
        .filter(Payment.status == "completed", Payment.created_at >= since)
        .group_by(Payment.pack_id)
    )
    by_pack = [
        {"pack_id": r.pack_id, "count": r.cnt, "stars": int(r.stars), "rub": int(r.rub_kopecks or 0) / 100.0}
        for r in by_pack_rows
    ]
    return {
        "days": days,
        "total_stars": int(total_stars),
        "total_rub_yoomoney": round(total_rub_yoomoney_rub, 2),
        "total_payments": total_payments,
        "refunds": refunded,
        "unique_buyers": unique_buyers,
        "revenue_usd_approx": round(revenue_usd, 2),
        "revenue_rub_approx": round(revenue_rub_total, 0),
        "revenue_rub_stars": round(revenue_rub_stars, 0),
        "star_to_rub": STAR_RUB_RATE,
        "by_pack": by_pack,
        "conversion_rate_pct": 0,
    }


@router.get("/payments/history")
def payments_history(
    db: Session = Depends(get_db),
    date_from: date | None = Query(None, description="Start date (UTC, inclusive)"),
    date_to: date | None = Query(None, description="End date (UTC, inclusive)"),
    granularity: str = Query("day", description="day | week"),
    pack_id: str | None = Query(None, description="Filter by pack_id"),
):
    """Исторические ряды по дням/неделям: выручка, транзакции, покупатели. Для графиков на странице Платежи."""
    if date_from is not None and date_to is not None and date_to < date_from:
        raise HTTPException(400, "date_to must be >= date_from")
    q = db.query(Payment).filter(Payment.status == "completed")
    if pack_id:
        q = q.filter(Payment.pack_id == pack_id)
    if date_from is not None:
        ts_from = datetime.combine(date_from, datetime.min.time()).replace(tzinfo=timezone.utc)
        q = q.filter(Payment.created_at >= ts_from)
    if date_to is not None:
        ts_to = datetime.combine(date_to, datetime.max.time()).replace(tzinfo=timezone.utc)
        q = q.filter(Payment.created_at <= ts_to)
    if granularity == "week":
        date_expr = func.date_trunc("week", Payment.created_at)
    else:
        date_expr = func.date(Payment.created_at)
    revenue_rub_expr = (
        func.coalesce(func.sum(Payment.amount_kopecks), 0) / 100.0
        + func.coalesce(func.sum(Payment.stars_amount), 0) * STAR_RUB_RATE
    )
    rows = (
        q.with_entities(
            date_expr.label("dt"),
            revenue_rub_expr.label("revenue_rub"),
            func.coalesce(func.sum(Payment.stars_amount), 0).label("revenue_stars"),
            func.count(Payment.id).label("transactions_count"),
            func.count(distinct(Payment.user_id)).label("unique_buyers"),
        )
        .group_by(date_expr)
        .order_by(date_expr)
        .all()
    )
    pack_revenue_expr = (
        func.coalesce(func.sum(Payment.amount_kopecks), 0) / 100.0
        + func.coalesce(func.sum(Payment.stars_amount), 0) * STAR_RUB_RATE
    )
    pack_rows = (
        q.with_entities(
            date_expr.label("dt"),
            Payment.pack_id.label("pack_id"),
            func.count(Payment.id).label("cnt"),
            pack_revenue_expr.label("revenue_rub"),
        )
        .group_by(date_expr, Payment.pack_id)
        .all()
    )
    date_to_pack: dict[str, list[dict[str, Any]]] = {}
    for pr in pack_rows:
        dt = pr.dt
        if hasattr(dt, "date"):
            dt = dt.date()
        if hasattr(dt, "isoformat"):
            date_str = dt.isoformat()
        else:
            date_str = str(dt)[:10]
        if date_str not in date_to_pack:
            date_to_pack[date_str] = []
        date_to_pack[date_str].append({
            "pack_id": pr.pack_id,
            "count": pr.cnt,
            "revenue_rub": round(float(pr.revenue_rub or 0), 2),
        })
    out = []
    for r in rows:
        dt = r.dt
        if hasattr(dt, "date"):
            dt = dt.date()
        if hasattr(dt, "isoformat"):
            date_str = dt.isoformat()
        else:
            date_str = str(dt)[:10]
        out.append({
            "date": date_str,
            "revenue_rub": round(float(r.revenue_rub or 0), 2),
            "revenue_stars": int(r.revenue_stars or 0),
            "transactions_count": r.transactions_count or 0,
            "unique_buyers": r.unique_buyers or 0,
            "by_pack": date_to_pack.get(date_str, []),
        })
    return {"series": out}


@router.post("/payments/{payment_id}/refund")
def payments_refund(
    payment_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    payment = db.query(Payment).filter(Payment.id == payment_id).one_or_none()
    if not payment:
        raise HTTPException(404, "Платёж не найден")
    if payment.payload and payment.payload.startswith("bank_transfer:"):
        raise HTTPException(400, "Возврат возможен только для платежей Stars. Для перевода на карту — вручную.")
    if payment.telegram_payment_charge_id and payment.telegram_payment_charge_id.startswith("yoomoney:"):
        raise HTTPException(400, "Возврат возможен только для платежей Stars. Для ЮMoney — через ЮKassa.")
    if payment.telegram_payment_charge_id and payment.telegram_payment_charge_id.startswith("yookassa_link:"):
        raise HTTPException(400, "Возврат возможен только для платежей Stars. Для ЮKassa (пакеты) — через ЮKassa.")
    if payment.telegram_payment_charge_id and payment.telegram_payment_charge_id.startswith("yookassa_unlock:"):
        raise HTTPException(400, "Возврат возможен только для платежей Stars. Для ЮKassa (unlock) — через ЮKassa.")
    svc = PaymentService(db)
    ok, msg, _ = svc.process_refund(payment_id)
    if not ok:
        raise HTTPException(400, msg)
    db.commit()
    _admin_audit(db, current_user, "refund", "payment", payment_id, {"user_id": payment.user_id})
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
def packs_update(
    pack_id: str,
    payload: dict,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
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
    _admin_audit(db, current_user, "update", "pack", pack_id, {})
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
def packs_create(
    payload: dict,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
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
    _admin_audit(db, current_user, "create", "pack", pack.id, {"name": pack.name})
    return {
        "id": pack.id, "name": pack.name, "emoji": pack.emoji,
        "tokens": pack.tokens, "stars_price": pack.stars_price,
        "enabled": pack.enabled, "pack_subtype": pack.pack_subtype,
    }


@router.delete("/packs/{pack_id}")
def packs_delete(
    pack_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    pack = db.query(Pack).filter(Pack.id == pack_id).first()
    if not pack:
        raise HTTPException(404, "Pack not found")
    pack_name = pack.name
    db.delete(pack)
    db.commit()
    _admin_audit(db, current_user, "delete", "pack", pack_id, {"name": pack_name})
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


def _theme_to_item(theme: Theme, bot_username: str | None = None) -> dict:
    audiences = getattr(theme, "target_audiences", None)
    out = {
        "id": theme.id,
        "name": theme.name,
        "emoji": theme.emoji or "",
        "order_index": theme.order_index,
        "enabled": theme.enabled,
        "target_audiences": normalize_target_audiences(audiences),
    }
    if bot_username:
        out["deeplink"] = f"https://t.me/{bot_username}?start=theme_{theme.id}"
    else:
        out["deeplink"] = None
    return out


def _get_bot_username_for_deeplink(db: Session) -> str:
    """Username бота без @ для диплинков (сначала из PosterSettings, иначе из env)."""
    ps = db.query(PosterSettings).filter(PosterSettings.id == 1).one_or_none()
    db_bot = (getattr(ps, "poster_bot_username", None) or "").strip() if ps else ""
    env_bot = (getattr(app_settings, "telegram_bot_username", None) or "").strip()
    return (db_bot or env_bot).lstrip("@")


@router.get("/themes")
def admin_themes_list(db: Session = Depends(get_db)):
    svc = ThemeService(db)
    themes = svc.list_all()
    bot_username = _get_bot_username_for_deeplink(db)
    return [_theme_to_item(t, bot_username) for t in themes]


@router.get("/themes/{theme_id}")
def admin_themes_get(theme_id: str, db: Session = Depends(get_db)):
    svc = ThemeService(db)
    theme = svc.get(theme_id)
    if not theme:
        raise HTTPException(404, "Theme not found")
    bot_username = _get_bot_username_for_deeplink(db)
    return _theme_to_item(theme, bot_username)


def _normalize_theme_target_audiences(value) -> list:
    """Валидация: только women, men, couples; минимум один."""
    normalized = normalize_target_audiences(value)
    allowed = [x for x in normalized if x in AUDIENCE_CHOICES]
    return allowed if allowed else ["women"]


@router.post("/themes")
def admin_themes_post(
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
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
    _admin_audit(db, current_user, "create", "theme", theme.id, {"name": theme.name})
    bot_username = _get_bot_username_for_deeplink(db)
    return _theme_to_item(theme, bot_username)


@router.put("/themes/{theme_id}")
def admin_themes_put(
    theme_id: str,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    svc = ThemeService(db)
    theme = svc.get(theme_id)
    if not theme:
        raise HTTPException(404, "Theme not found")
    data = {k: v for k, v in payload.items() if k in THEME_EDIT_FIELDS}
    if "target_audiences" in data:
        data["target_audiences"] = _normalize_theme_target_audiences(data["target_audiences"])
    bot_username = _get_bot_username_for_deeplink(db)
    if not data:
        return _theme_to_item(theme, bot_username)
    svc.update(theme, data)
    _admin_audit(db, current_user, "update", "theme", theme_id, {})
    return _theme_to_item(theme, bot_username)


@router.patch("/themes/{theme_id}/order")
def admin_themes_patch_order(
    theme_id: str,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    direction = payload.get("direction")
    if direction not in ("up", "down"):
        raise HTTPException(400, "direction must be 'up' or 'down'")
    svc = ThemeService(db)
    theme = svc.patch_order(theme_id, direction)
    if not theme:
        raise HTTPException(404, "Theme not found")
    _admin_audit(db, current_user, "update", "theme", theme_id, {"order": direction})
    bot_username = _get_bot_username_for_deeplink(db)
    return _theme_to_item(theme, bot_username)


@router.delete("/themes/{theme_id}")
def admin_themes_delete(
    theme_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    svc = ThemeService(db)
    theme = svc.get(theme_id)
    if not theme:
        raise HTTPException(404, "Theme not found")
    theme_name = theme.name
    svc.delete(theme)
    _admin_audit(db, current_user, "delete", "theme", theme_id, {"name": theme_name})
    return {"ok": True}


# ---------- Trends ----------
# Allowed fields for trend create/update (subset of Trend model)
TREND_EDIT_FIELDS = {
    "name", "emoji", "description", "system_prompt", "scene_prompt", "subject_prompt",
    "negative_prompt", "negative_scene", "composition_prompt", "subject_mode", "framing_hint", "style_preset",
    "max_images", "enabled", "order_index", "theme_id", "target_audiences",
    "prompt_sections", "prompt_model", "prompt_size", "prompt_format", "prompt_aspect_ratio",
    "prompt_temperature", "prompt_seed", "prompt_image_size_tier",
    "prompt_top_p", "prompt_candidate_count", "prompt_media_resolution", "prompt_thinking_config",
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
        "prompt_aspect_ratio": getattr(t, "prompt_aspect_ratio", None),
        "prompt_temperature": t.prompt_temperature,
        "prompt_seed": t.prompt_seed,
        "prompt_image_size_tier": getattr(t, "prompt_image_size_tier", None),
        "prompt_top_p": getattr(t, "prompt_top_p", None),
        "prompt_candidate_count": getattr(t, "prompt_candidate_count", None),
        "prompt_media_resolution": getattr(t, "prompt_media_resolution", None),
        "prompt_thinking_config": getattr(t, "prompt_thinking_config", None),
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
    window_days: int = Query(30, ge=0, le=365),
):
    """Аналитика по всем трендам: сколько успешно сгенерировано, сколько с ошибкой/не доставлено. window_days=0 — всё время."""
    since = (datetime.now(timezone.utc) - timedelta(days=window_days)) if window_days else None
    svc = TrendService(db)
    all_trends = svc.list_all()
    trend_ids = [t.id for t in all_trends]
    if not trend_ids:
        return {"window_days": window_days if window_days else None, "items": []}
    job_q = (
        db.query(
            Job.trend_id,
            func.count(Job.job_id).label("total"),
            func.sum(case((Job.status == "SUCCEEDED", 1), else_=0)).label("succeeded"),
            func.sum(case((Job.status.in_(["FAILED", "ERROR"]), 1), else_=0)).label("failed"),
        )
        .filter(Job.trend_id.in_(trend_ids))
    )
    if since is not None:
        job_q = job_q.filter(Job.created_at >= since)
    job_stats = job_q.group_by(Job.trend_id).all()
    job_by_trend = {
        r.trend_id: {"total": r.total or 0, "succeeded": r.succeeded or 0, "failed": r.failed or 0}
        for r in job_stats
    }
    take_q = (
        db.query(
            Take.trend_id,
            func.count(Take.id).label("total"),
            func.sum(case((Take.status.in_(["ready", "partial_fail"]), 1), else_=0)).label("succeeded"),
            func.sum(case((Take.status == "failed", 1), else_=0)).label("failed"),
        )
        .filter(Take.trend_id.in_(trend_ids))
    )
    if since is not None:
        take_q = take_q.filter(Take.created_at >= since)
    take_stats = take_q.group_by(Take.trend_id).all()
    take_by_trend = {
        r.trend_id: {"total": r.total or 0, "succeeded": r.succeeded or 0, "failed": r.failed or 0}
        for r in take_stats
    }
    chosen_actions = ("choose_best_variant", "favorites_auto_add")
    chosen_q = (
        db.query(
            func.coalesce(AuditLog.payload["trend_id"].astext, "").label("trend_id"),
            func.count(AuditLog.id).label("cnt"),
        )
        .filter(AuditLog.action.in_(chosen_actions))
        .group_by(func.coalesce(AuditLog.payload["trend_id"].astext, ""))
    )
    if since is not None:
        chosen_q = chosen_q.filter(AuditLog.created_at >= since)
    chosen_by_trend = {
        r.trend_id: r.cnt for r in chosen_q.all()
        if r.trend_id and str(r.trend_id).strip()
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
            "chosen_total": chosen_by_trend.get(t.id, 0),
        })
    return {"window_days": window_days if window_days else None, "items": items}


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
def admin_trends_put(
    trend_id: str,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    svc = TrendService(db)
    trend = svc.get(trend_id)
    if not trend:
        raise HTTPException(404, "Trend not found")
    data = {k: v for k, v in payload.items() if k in TREND_EDIT_FIELDS}
    data = _normalize_trend_payload(data)
    if not data:
        return _trend_to_detail(trend)
    svc.update(trend, data)
    _admin_audit(db, current_user, "update", "trend", trend_id, {})
    return _trend_to_detail(trend)


@router.post("/trends")
def admin_trends_post(
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
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
    _admin_audit(db, current_user, "create", "trend", trend.id, {"name": trend.name or trend.id})
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
def admin_trends_post_example(
    trend_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    svc = TrendService(db)
    trend = svc.get(trend_id)
    if not trend:
        raise HTTPException(404, "Trend not found")
    path = _save_trend_file(trend_id, file, "_example")
    svc.update(trend, {"example_image_path": path})
    _admin_audit(db, current_user, "update", "trend", trend_id, {"example_uploaded": True})
    return _trend_to_detail(trend)


@router.delete("/trends/{trend_id}/example")
def admin_trends_delete_example(
    trend_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
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
    _admin_audit(db, current_user, "delete", "trend_example", trend_id, {})
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
def admin_trends_patch_order(
    trend_id: str,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
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
    _admin_audit(db, current_user, "update", "trend", trend_id, {"order": direction})
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
    current_user: dict = Depends(get_current_user),
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
    _admin_audit(db, current_user, "create", "trend_post", post.id, {"trend_id": trend_id})
    return {
        "id": post.id,
        "trend_id": post.trend_id,
        "status": post.status,
        "telegram_message_id": post.telegram_message_id,
        "sent_at": post.sent_at.isoformat() if post.sent_at else None,
    }


@router.delete("/trend-posts/{post_id}")
def trend_posts_delete(
    post_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
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
    _admin_audit(db, current_user, "delete", "trend_post", post_id, {"trend_id": post.trend_id})
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
    current_user: dict = Depends(get_current_user),
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
    _admin_audit(db, current_user, "update", "settings", None, {"section": "trend_posts"})
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
_AUDIT_FILTERS_CACHE: dict[int, tuple[dict[str, Any], float]] = {}
_AUDIT_FILTERS_CACHE_TTL_SEC = 300
_AUDIT_FILTERS_SAMPLE_LIMIT = 500_000


def _parse_audit_date(value: str) -> datetime:
    """Parse ISO date string; raise ValueError if invalid. Used to return 400 instead of ignoring."""
    if not value or not value.strip():
        raise ValueError("empty date")
    s = value.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


@router.get("/audit/filters")
def audit_filters(
    db: Session = Depends(get_db),
    window_days: int = Query(90, ge=1, le=365),
):
    """Distinct action and entity_type from audit_logs for the last window_days. Cached 5 min, sample limited to 500k rows."""
    now = time.time()
    if window_days in _AUDIT_FILTERS_CACHE:
        cached, expiry = _AUDIT_FILTERS_CACHE[window_days]
        if now <= expiry:
            return cached
    since = datetime.now(timezone.utc) - timedelta(days=window_days)
    limited = (
        db.query(AuditLog.action, AuditLog.entity_type)
        .filter(AuditLog.created_at >= since)
        .order_by(AuditLog.created_at.desc())
        .limit(_AUDIT_FILTERS_SAMPLE_LIMIT)
        .all()
    )
    actions = sorted({r[0] for r in limited if r[0]})
    entity_types = sorted({r[1] for r in limited if r[1]})
    result = {"actions": actions, "entity_types": entity_types, "window_days": window_days}
    _AUDIT_FILTERS_CACHE[window_days] = (result, now + _AUDIT_FILTERS_CACHE_TTL_SEC)
    return result


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
    user_id: str | None = None,
    session_id: str | None = None,
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
    if user_id and user_id.strip():
        q = q.filter(AuditLog.user_id == user_id.strip())
    if session_id and session_id.strip():
        q = q.filter(AuditLog.session_id == session_id.strip())
    if date_from:
        try:
            since = _parse_audit_date(date_from)
            q = q.filter(AuditLog.created_at >= since)
        except (ValueError, TypeError) as e:
            raise HTTPException(400, detail=f"invalid date_from: {e!s}") from e
    if date_to:
        try:
            until = _parse_audit_date(date_to)
            q = q.filter(AuditLog.created_at <= until)
        except (ValueError, TypeError) as e:
            raise HTTPException(400, detail=f"invalid date_to: {e!s}") from e
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
            "user_id": r.user_id,
            "session_id": r.session_id,
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
    user_id: str | None = None,
    session_id: str | None = None,
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
    if user_id and user_id.strip():
        q = q.filter(AuditLog.user_id == user_id.strip())
    if session_id and session_id.strip():
        q = q.filter(AuditLog.session_id == session_id.strip())
    since: datetime | None = None
    until: datetime | None = None
    if date_from:
        try:
            since = _parse_audit_date(date_from)
            q = q.filter(AuditLog.created_at >= since)
        except (ValueError, TypeError) as e:
            raise HTTPException(400, detail=f"invalid date_from: {e!s}") from e
    if date_to:
        try:
            until = _parse_audit_date(date_to)
            q = q.filter(AuditLog.created_at <= until)
        except (ValueError, TypeError) as e:
            raise HTTPException(400, detail=f"invalid date_to: {e!s}") from e

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
def broadcast_send(
    payload: dict,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    message = (payload.get("message") or "").strip()
    include_blocked = bool(payload.get("include_blocked", False))
    if not message:
        raise HTTPException(400, "message is required")
    result = broadcast_message.delay(message, include_blocked=include_blocked)
    _admin_audit(db, current_user, "broadcast", "broadcast", result.id, {"include_blocked": include_blocked})
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


def _job_to_item(j: Job, users: dict, trends: dict) -> dict:
    u = users.get(j.user_id)
    t = trends.get(j.trend_id)
    user_display_name = None
    if u:
        if u.telegram_username:
            user_display_name = f"@{u.telegram_username}"
        else:
            name = f"{u.telegram_first_name or ''} {u.telegram_last_name or ''}".strip()
            user_display_name = name or u.telegram_id
    return {
        "job_id": j.job_id,
        "task_type": "job",
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
    }


def _take_status_display(take_status: str) -> str:
    """Привести статус Take к отображаемому (близко к Job)."""
    if take_status in ("ready", "partial_fail"):
        return "SUCCEEDED"
    if take_status == "failed":
        return "FAILED"
    if take_status == "generating":
        return "RUNNING"
    return take_status.upper() if take_status else "CREATED"


@router.get("/jobs")
def jobs_list(
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    status: str | None = None,
    telegram_id: str | None = None,
    trend_id: str | None = None,
    hours: int | None = Query(None, ge=1, le=720),
    include_takes: bool = Query(True, description="Включить снимки (Take) в журнал"),
):
    user_id_filter = None
    if telegram_id:
        u = db.query(User).filter(User.telegram_id == telegram_id).first()
        user_id_filter = u.id if u else ""

    since = None
    if hours is not None:
        since = datetime.now(timezone.utc) - timedelta(hours=hours)

    if not include_takes:
        q = db.query(Job)
        if status:
            q = q.filter(Job.status == status)
        if user_id_filter is not None:
            q = q.filter(Job.user_id == user_id_filter)
        if trend_id:
            q = q.filter(Job.trend_id == trend_id)
        if since is not None:
            q = q.filter(Job.created_at >= since)
        total = q.count()
        q = q.order_by(Job.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        jobs = q.all()
        user_ids = [j.user_id for j in jobs]
        trend_ids = list({j.trend_id for j in jobs})
        users = {u.id: u for u in db.query(User).filter(User.id.in_(user_ids)).all()} if user_ids else {}
        trends = {t.id: t for t in db.query(Trend).filter(Trend.id.in_(trend_ids)).all()} if trend_ids else {}
        items = [_job_to_item(j, users, trends) for j in jobs]
        return {"items": items, "total": total, "page": page, "pages": (total + page_size - 1) // page_size}

    # Объединённый список Job + Take: собираем id и created_at, сортируем, пагинируем, потом догружаем сущности
    cap = 5000
    q_j = db.query(Job.job_id, Job.created_at).order_by(Job.created_at.desc())
    if status:
        q_j = q_j.filter(Job.status == status)
    if user_id_filter is not None:
        q_j = q_j.filter(Job.user_id == user_id_filter)
    if trend_id:
        q_j = q_j.filter(Job.trend_id == trend_id)
    if since is not None:
        q_j = q_j.filter(Job.created_at >= since)
    job_rows = q_j.limit(cap).all()

    take_status_filter = None
    if status:
        if status == "SUCCEEDED":
            take_status_filter = ["ready", "partial_fail"]
        elif status in ("FAILED", "ERROR"):
            take_status_filter = ["failed"]
        elif status in ("CREATED", "RUNNING"):
            take_status_filter = ["generating"]
        else:
            take_status_filter = [status.lower()] if status else None
    q_t = db.query(Take.id, Take.created_at).order_by(Take.created_at.desc())
    if take_status_filter is not None:
        q_t = q_t.filter(Take.status.in_(take_status_filter))
    if user_id_filter is not None:
        q_t = q_t.filter(Take.user_id == user_id_filter)
    if trend_id:
        q_t = q_t.filter(Take.trend_id == trend_id)
    if since is not None:
        q_t = q_t.filter(Take.created_at >= since)
    take_rows = q_t.limit(cap).all()

    merged = [(r.created_at, "job", r.job_id) for r in job_rows]
    merged += [(r.created_at, "take", str(r.id)) for r in take_rows]
    merged.sort(key=lambda x: x[0], reverse=True)
    total = len(merged)
    # total ограничен 2*cap (10000): при большем числе задач пагинация показывает первые 10k
    start = (page - 1) * page_size
    page_slice = merged[start : start + page_size]

    job_ids = [tid for _, t, tid in page_slice if t == "job"]
    take_ids = [tid for _, t, tid in page_slice if t == "take"]
    jobs = {j.job_id: j for j in db.query(Job).filter(Job.job_id.in_(job_ids)).all()} if job_ids else {}
    takes = {t.id: t for t in db.query(Take).filter(Take.id.in_(take_ids)).all()} if take_ids else {}

    user_ids = [jobs[jid].user_id for jid in job_ids if jid in jobs]
    user_ids += [takes[tid].user_id for tid in take_ids if tid in takes]
    trend_ids = list({jobs[jid].trend_id for jid in job_ids if jid in jobs} | {takes[tid].trend_id for tid in take_ids if tid in takes} - {None})
    users = {u.id: u for u in db.query(User).filter(User.id.in_(user_ids)).all()} if user_ids else {}
    trends = {t.id: t for t in db.query(Trend).filter(Trend.id.in_(trend_ids)).all()} if trend_ids else {}

    items = []
    for created_at, task_type, task_id in page_slice:
        if task_type == "job":
            j = jobs.get(task_id)
            if j:
                items.append(_job_to_item(j, users, trends))
        else:
            t = takes.get(task_id)
            if t:
                u = users.get(t.user_id)
                tr = trends.get(t.trend_id)
                user_display_name = None
                if u:
                    user_display_name = f"@{u.telegram_username}" if u.telegram_username else (f"{u.telegram_first_name or ''} {u.telegram_last_name or ''}".strip() or u.telegram_id)
                items.append({
                    "job_id": task_id,
                    "task_type": "take",
                    "user_id": t.user_id,
                    "telegram_id": u.telegram_id if u else None,
                    "user_display_name": user_display_name,
                    "trend_id": t.trend_id,
                    "trend_name": tr.name if tr else None,
                    "trend_emoji": tr.emoji if tr else None,
                    "status": _take_status_display(t.status),
                    "is_preview": False,
                    "reserved_tokens": 0,
                    "error_code": t.error_code,
                    "created_at": t.created_at.isoformat() if t.created_at else None,
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
def copy_style_put(
    payload: dict,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    svc = CopyStyleSettingsService(db)
    result = svc.update(payload)
    _admin_audit(db, current_user, "update", "settings", None, {"section": "copy_style"})
    return result


# ---------- Cleanup ----------
@router.get("/cleanup/preview")
def cleanup_preview(db: Session = Depends(get_db), older_than_hours: int = Query(24, ge=1)):
    svc = CleanupService(db)
    return svc.preview_temp_cleanup(older_than_hours)


@router.post("/cleanup/run")
def cleanup_run(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    older_than_hours: int = Query(24, ge=1),
):
    svc = CleanupService(db)
    result = svc.cleanup_temp_files(older_than_hours)
    _admin_audit(
        db,
        current_user,
        "cleanup",
        "temp_files",
        None,
        {"cleaned_jobs": result.get("cleaned_jobs", 0), "older_than_hours": older_than_hours},
    )
    return result


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
def referrals_bonus_freeze(
    bonus_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Freeze a bonus for manual review."""
    ref_svc = ReferralService(db)
    ok = ref_svc.freeze_bonus(bonus_id)
    if not ok:
        raise HTTPException(400, "Cannot freeze this bonus (already spent/revoked or not found)")
    db.commit()
    _admin_audit(db, current_user, "update", "referral_bonus", bonus_id, {"action": "freeze"})
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
def traffic_sources_create(
    body: TrafficSourceCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
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
    _admin_audit(db, current_user, "create", "traffic_source", source.id, {"slug": source.slug})
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
def traffic_sources_update(
    source_id: str,
    body: TrafficSourceUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
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
    _admin_audit(db, current_user, "update", "traffic_source", source_id, {})
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
def traffic_sources_delete(
    source_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Soft-delete: set is_active=False."""
    source = db.query(TrafficSource).filter(TrafficSource.id == source_id).first()
    if not source:
        raise HTTPException(404, "Traffic source not found")
    source.is_active = False
    db.commit()
    _admin_audit(db, current_user, "update", "traffic_source", source_id, {"is_active": False})
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
def ad_campaigns_create(
    body: AdCampaignCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
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
    _admin_audit(db, current_user, "create", "ad_campaign", campaign.id, {"name": campaign.name})
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
def ad_campaigns_update(
    campaign_id: str,
    body: AdCampaignUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
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
    _admin_audit(db, current_user, "update", "ad_campaign", campaign_id, {})
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
def photo_merge_settings_put(
    payload: dict,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Обновить настройки сервиса склейки."""
    svc = PhotoMergeSettingsService(db)
    result = svc.update(payload)
    _admin_audit(db, current_user, "update", "settings", None, {"section": "photo_merge"})
    return result
