from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models import Membership, Subscription, User


class AuthContext:
    def __init__(
        self,
        *,
        user: User,
        tenant_id: UUID | None,
        role: str | None,
        is_platform_admin: bool,
    ) -> None:
        self.user = user
        self.tenant_id = tenant_id
        self.role = role
        self.is_platform_admin = is_platform_admin


def get_current_auth(request: Request, db: Session = Depends(get_db)) -> AuthContext:
    settings = get_settings()
    token = request.cookies.get(settings.cookie_name)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Não autenticado")
    try:
        payload = decode_access_token(token)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    user_id = UUID(payload["sub"])
    user = db.get(User, user_id)
    if not user or user.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuário inválido")

    is_platform_admin = bool(payload.get("is_platform_admin"))
    tenant_raw = payload.get("tenant_id")
    tenant_id = UUID(tenant_raw) if tenant_raw else None
    role = payload.get("role")

    if tenant_id and not is_platform_admin:
        membership = (
            db.query(Membership)
            .filter(
                Membership.tenant_id == tenant_id,
                Membership.user_id == user.id,
                Membership.deleted_at.is_(None),
            )
            .first()
        )
        if not membership:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sem membership no tenant")
        role = membership.role

    return AuthContext(
        user=user,
        tenant_id=tenant_id,
        role=role,
        is_platform_admin=is_platform_admin,
    )


def require_platform_admin(auth: AuthContext = Depends(get_current_auth)) -> AuthContext:
    if not auth.is_platform_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Só platform admin")
    return auth


def require_tenant(auth: AuthContext = Depends(get_current_auth)) -> AuthContext:
    if not auth.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant obrigatório")
    return auth


def require_tenant_admin(auth: AuthContext = Depends(require_tenant)) -> AuthContext:
    if auth.role != "TENANT_ADMIN":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Só tenant admin")
    return auth


def require_staff_or_admin(auth: AuthContext = Depends(require_tenant)) -> AuthContext:
    if auth.role not in ("TENANT_ADMIN", "STAFF"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Papel insuficiente")
    return auth


def assert_subscription_writable(db: Session, tenant_id: UUID) -> None:
    sub = (
        db.query(Subscription)
        .filter(Subscription.tenant_id == tenant_id, Subscription.deleted_at.is_(None))
        .first()
    )
    if not sub:
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail="Sem assinatura")
    today = date.today()
    if sub.status in ("past_due", "canceled") or sub.current_period_end < today:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Assinatura vencida ou bloqueada. Só leitura.",
        )
