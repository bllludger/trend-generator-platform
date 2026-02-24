"""Сервис политики переноса личности. Две записи: scope=global и scope=trends."""
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.transfer_policy import TransferPolicy

SCOPE_GLOBAL = "global"
SCOPE_TRENDS = "trends"


def _row_to_dict(row: TransferPolicy) -> dict[str, Any]:
    return {
        "identity_lock_level": (row.identity_lock_level or "").strip() or "strict",
        "identity_rules_text": (row.identity_rules_text or "").strip(),
        "composition_rules_text": (row.composition_rules_text or "").strip(),
        "subject_reference_name": (row.subject_reference_name or "").strip() or "IMAGE_1",
        "avoid_default_items": (row.avoid_default_items or "").strip() if getattr(row, "avoid_default_items", None) is not None else "",
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def get_effective(session: Session, scope: str = SCOPE_GLOBAL) -> dict[str, Any]:
    """Получить эффективную политику по scope (global | trends)."""
    row = session.query(TransferPolicy).filter(TransferPolicy.scope == scope).first()
    if not row:
        return _default()
    return _row_to_dict(row)


def get_all(session: Session) -> dict[str, dict[str, Any]]:
    """Оба набора: { global: {...}, trends: {...} }."""
    rows = session.query(TransferPolicy).all()
    out = {"global": _default(), "trends": _default()}
    for row in rows:
        s = (row.scope or "global").strip().lower()
        if s in out:
            out[s] = _row_to_dict(row)
    return out


def get_or_create(session: Session, scope: str = SCOPE_GLOBAL) -> TransferPolicy:
    row = session.query(TransferPolicy).filter(TransferPolicy.scope == scope).first()
    if row:
        return row
    next_id = 2 if scope == SCOPE_TRENDS else 1
    row = TransferPolicy(id=next_id, scope=scope)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def update(session: Session, data: dict[str, Any], scope: str = SCOPE_GLOBAL) -> dict[str, Any]:
    row = get_or_create(session, scope)
    row.updated_at = datetime.now(timezone.utc)
    if "identity_lock_level" in data:
        row.identity_lock_level = str(data["identity_lock_level"] or "strict").strip() or "strict"
    if "identity_rules_text" in data:
        row.identity_rules_text = "" if data["identity_rules_text"] is None else str(data["identity_rules_text"])
    if "composition_rules_text" in data:
        row.composition_rules_text = "" if data["composition_rules_text"] is None else str(data["composition_rules_text"])
    if "subject_reference_name" in data:
        row.subject_reference_name = str(data["subject_reference_name"] or "IMAGE_1").strip() or "IMAGE_1"
    if "avoid_default_items" in data:
        row.avoid_default_items = "" if data["avoid_default_items"] is None else str(data["avoid_default_items"])
    session.add(row)
    session.commit()
    session.refresh(row)
    return _row_to_dict(row)


def update_both(session: Session, payload: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Сохранить оба набора. payload = { global?: {...}, trends?: {...} }. Возвращает get_all()."""
    if "global" in payload and payload["global"]:
        update(session, payload["global"], SCOPE_GLOBAL)
    if "trends" in payload and payload["trends"]:
        update(session, payload["trends"], SCOPE_TRENDS)
    return get_all(session)


def _default() -> dict[str, Any]:
    return {
        "identity_lock_level": "strict",
        "identity_rules_text": "Preserve the face and identity from IMAGE_1 in the output. Do not alter facial features, skin tone, or distinguishing characteristics.",
        "composition_rules_text": "Place the subject from IMAGE_1 naturally in the scene. Maintain proportions and perspective.",
        "subject_reference_name": "IMAGE_1",
        "avoid_default_items": "",
    }
