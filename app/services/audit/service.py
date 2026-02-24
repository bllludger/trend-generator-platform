from typing import Any

from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog


class AuditService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def log(
        self,
        actor_type: str,
        actor_id: str | None,
        action: str,
        entity_type: str,
        entity_id: str | None,
        payload: dict[str, Any] | None = None,
    ) -> AuditLog:
        entry = AuditLog(
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            payload=payload or {},
        )
        self.db.add(entry)
        self.db.commit()
        self.db.refresh(entry)
        return entry
