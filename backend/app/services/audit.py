from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models import AuditLog

logger = get_logger("oficinaflow.audit")


def write_audit(
    db: Session,
    *,
    action: str,
    actor_user_id: UUID | None,
    tenant_id: UUID | None = None,
    entity_type: str = "",
    entity_id: str = "",
    detail: str = "",
) -> None:
    db.add(
        AuditLog(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            detail=detail[:2000],
        )
    )
    logger.info(
        "audit",
        extra={
            "action": action,
            "actor_id": str(actor_user_id) if actor_user_id else None,
            "tenant_id": str(tenant_id) if tenant_id else None,
            "result": "recorded",
        },
    )
