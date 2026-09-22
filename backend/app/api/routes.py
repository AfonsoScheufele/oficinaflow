from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import extract, func, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.deps import (
    AuthContext,
    assert_subscription_writable,
    get_current_auth,
    require_platform_admin,
    require_staff_or_admin,
    require_tenant,
    require_tenant_admin,
)
from app.core.security import create_access_token, hash_password, verify_password
from app.db.session import get_db
from app.models import (
    Appointment,
    Customer,
    Membership,
    Payment,
    Plan,
    ServiceCatalog,
    Subscription,
    Tenant,
    User,
    WebhookEvent,
    WorkOrder,
)
from app.schemas import (
    AppointmentIn,
    AppointmentOut,
    CheckoutIn,
    CheckoutOut,
    CustomerIn,
    CustomerOut,
    LoginRequest,
    MeResponse,
    MembershipCreate,
    MembershipOut,
    PaymentOut,
    PlatformTenantCreate,
    ServiceIn,
    ServiceOut,
    SubscriptionOut,
    TenantOut,
    TenantPatch,
    TransitionIn,
    UserOut,
    WebhookEventOut,
    WorkOrderIn,
    WorkOrderOut,
)
from app.services.audit import write_audit
from app.services.billing import accept_pix_webhook, create_pix_charge
from app.services.fsm import APPOINTMENT_TRANSITIONS, WORK_ORDER_TRANSITIONS, IllegalTransitionError, transition
from app.services.rate_limit import allow_request

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "oficinaflow"}


@router.get("/health/ready")
def health_ready(db: Session = Depends(get_db)) -> dict:
    checks: dict[str, str] = {}
    try:
        db.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail={"postgres": "fail", "error": str(exc)[:80]}) from exc

    try:
        from redis import Redis

        settings = get_settings()
        r = Redis.from_url(settings.redis_url, socket_connect_timeout=1, socket_timeout=1)
        r.ping()
        checks["redis"] = "ok"
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503,
            detail={"postgres": "ok", "redis": "fail", "error": str(exc)[:80]},
        ) from exc

    return {"status": "ready", "checks": checks}




@router.post("/auth/login", response_model=MeResponse)
def login(body: LoginRequest, response: Response, db: Session = Depends(get_db)) -> MeResponse:
    settings = get_settings()
    user = db.query(User).filter(User.email == body.email.lower(), User.deleted_at.is_(None)).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Credenciais inválidas")

    tenant: Tenant | None = None
    role: str | None = None

    if user.is_platform_admin and not body.tenant_slug:
        token = create_access_token(
            subject=user.id, tenant_id=None, role=None, is_platform_admin=True
        )
    else:
        if not body.tenant_slug:
            memberships = (
                db.query(Membership)
                .filter(Membership.user_id == user.id, Membership.deleted_at.is_(None))
                .all()
            )
            if len(memberships) == 1:
                m = memberships[0]
                tenant = db.get(Tenant, m.tenant_id)
                role = m.role
            else:
                raise HTTPException(status_code=400, detail="Informe tenant_slug")
        else:
            tenant = (
                db.query(Tenant)
                .filter(Tenant.slug == body.tenant_slug, Tenant.deleted_at.is_(None))
                .first()
            )
            if not tenant:
                raise HTTPException(status_code=404, detail="Tenant não encontrado")
            m = (
                db.query(Membership)
                .filter(
                    Membership.tenant_id == tenant.id,
                    Membership.user_id == user.id,
                    Membership.deleted_at.is_(None),
                )
                .first()
            )
            if not m and not user.is_platform_admin:
                raise HTTPException(status_code=403, detail="Sem acesso a este tenant")
            role = m.role if m else "TENANT_ADMIN"

        token = create_access_token(
            subject=user.id,
            tenant_id=tenant.id if tenant else None,
            role=role,
            is_platform_admin=user.is_platform_admin,
        )

    response.set_cookie(
        key=settings.cookie_name,
        value=token,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=settings.jwt_expire_minutes * 60,
        path="/",
    )
    return MeResponse(
        user=UserOut.model_validate(user),
        tenant=TenantOut.model_validate(tenant) if tenant else None,
        role=role,
        is_platform_admin=user.is_platform_admin,
    )


@router.post("/auth/logout")
def logout(response: Response) -> dict[str, str]:
    settings = get_settings()
    response.delete_cookie(settings.cookie_name, path="/")
    return {"ok": "true"}


@router.get("/auth/me", response_model=MeResponse)
def me(auth: AuthContext = Depends(get_current_auth), db: Session = Depends(get_db)) -> MeResponse:
    tenant = db.get(Tenant, auth.tenant_id) if auth.tenant_id else None
    return MeResponse(
        user=UserOut.model_validate(auth.user),
        tenant=TenantOut.model_validate(tenant) if tenant else None,
        role=auth.role,
        is_platform_admin=auth.is_platform_admin,
    )




@router.get("/platform/tenants", response_model=list[TenantOut])
def list_tenants(
    _: AuthContext = Depends(require_platform_admin), db: Session = Depends(get_db)
) -> list[Tenant]:
    return db.query(Tenant).filter(Tenant.deleted_at.is_(None)).order_by(Tenant.name).all()


@router.post("/platform/tenants", response_model=TenantOut, status_code=201)
def create_tenant(
    body: PlatformTenantCreate,
    _: AuthContext = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> Tenant:
    if db.query(Tenant).filter(Tenant.slug == body.slug).first():
        raise HTTPException(status_code=409, detail="Slug já existe")
    tenant = Tenant(slug=body.slug, name=body.name, status="active")
    db.add(tenant)
    db.flush()
    user = db.query(User).filter(User.email == body.admin_email.lower()).first()
    if not user:
        user = User(
            email=body.admin_email.lower(),
            full_name=body.admin_name,
            password_hash=hash_password(body.admin_password),
        )
        db.add(user)
        db.flush()
    db.add(Membership(tenant_id=tenant.id, user_id=user.id, role="TENANT_ADMIN"))
    db.add(
        Subscription(
            tenant_id=tenant.id,
            plan_code="free",
            status="trialing",
            current_period_end=date.today() + timedelta(days=14),
        )
    )
    db.commit()
    db.refresh(tenant)
    return tenant


@router.get("/platform/subscriptions", response_model=list[SubscriptionOut])
def list_subscriptions(
    _: AuthContext = Depends(require_platform_admin), db: Session = Depends(get_db)
) -> list[Subscription]:
    return db.query(Subscription).filter(Subscription.deleted_at.is_(None)).all()




@router.get("/tenant", response_model=TenantOut)
def get_tenant(auth: AuthContext = Depends(require_tenant), db: Session = Depends(get_db)) -> Tenant:
    tenant = db.get(Tenant, auth.tenant_id)
    if not tenant or tenant.deleted_at:
        raise HTTPException(status_code=404, detail="Tenant não encontrado")
    return tenant


@router.patch("/tenant", response_model=TenantOut)
def patch_tenant(
    body: TenantPatch,
    auth: AuthContext = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
) -> Tenant:
    tenant = db.get(Tenant, auth.tenant_id)
    if not tenant or tenant.deleted_at:
        raise HTTPException(status_code=404, detail="Tenant não encontrado")
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(tenant, k, v)
    db.commit()
    db.refresh(tenant)
    return tenant


@router.get("/memberships", response_model=list[MembershipOut])
def list_memberships(
    auth: AuthContext = Depends(require_tenant_admin), db: Session = Depends(get_db)
) -> list[MembershipOut]:
    rows = (
        db.query(Membership, User)
        .join(User, User.id == Membership.user_id)
        .filter(Membership.tenant_id == auth.tenant_id, Membership.deleted_at.is_(None))
        .all()
    )
    return [
        MembershipOut(id=m.id, user_id=u.id, email=u.email, full_name=u.full_name, role=m.role)
        for m, u in rows
    ]


@router.post("/memberships", response_model=MembershipOut, status_code=201)
def create_membership(
    body: MembershipCreate,
    auth: AuthContext = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
) -> MembershipOut:
    assert_subscription_writable(db, auth.tenant_id)  # type: ignore[arg-type]
    sub = db.query(Subscription).filter(Subscription.tenant_id == auth.tenant_id).first()
    plan = db.get(Plan, sub.plan_code) if sub else None
    staff_count = (
        db.query(Membership)
        .filter(Membership.tenant_id == auth.tenant_id, Membership.deleted_at.is_(None))
        .count()
    )
    if plan and staff_count >= plan.max_staff:
        raise HTTPException(status_code=400, detail="Limite de staff do plano atingido")

    user = db.query(User).filter(User.email == body.email.lower()).first()
    if not user:
        user = User(
            email=body.email.lower(),
            full_name=body.full_name,
            password_hash=hash_password(body.password),
        )
        db.add(user)
        db.flush()
    existing = (
        db.query(Membership)
        .filter(Membership.tenant_id == auth.tenant_id, Membership.user_id == user.id)
        .first()
    )
    if existing and not existing.deleted_at:
        raise HTTPException(status_code=409, detail="Usuário já é membro")
    m = Membership(tenant_id=auth.tenant_id, user_id=user.id, role=body.role)
    db.add(m)
    write_audit(
        db,
        action="membership.create",
        actor_user_id=auth.user.id,
        tenant_id=auth.tenant_id,
        entity_type="membership",
        entity_id=str(user.id),
        detail=f"role={body.role} email={user.email}",
    )
    db.commit()
    db.refresh(m)
    return MembershipOut(id=m.id, user_id=user.id, email=user.email, full_name=user.full_name, role=m.role)


@router.delete("/memberships/{membership_id}", status_code=204, response_class=Response)
def delete_membership(
    membership_id: UUID,
    auth: AuthContext = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
) -> Response:
    m = (
        db.query(Membership)
        .filter(
            Membership.id == membership_id,
            Membership.tenant_id == auth.tenant_id,
            Membership.deleted_at.is_(None),
        )
        .first()
    )
    if not m:
        raise HTTPException(status_code=404, detail="Membership não encontrado")
    if m.user_id == auth.user.id:
        raise HTTPException(status_code=400, detail="Não pode remover a si mesmo")
    m.soft_delete()
    write_audit(
        db,
        action="membership.delete",
        actor_user_id=auth.user.id,
        tenant_id=auth.tenant_id,
        entity_type="membership",
        entity_id=str(membership_id),
    )
    db.commit()
    return Response(status_code=204)




@router.get("/customers", response_model=list[CustomerOut])
def list_customers(
    auth: AuthContext = Depends(require_staff_or_admin), db: Session = Depends(get_db)
) -> list[Customer]:
    return (
        db.query(Customer)
        .filter(Customer.tenant_id == auth.tenant_id, Customer.deleted_at.is_(None))
        .order_by(Customer.name)
        .all()
    )


@router.post("/customers", response_model=CustomerOut, status_code=201)
def create_customer(
    body: CustomerIn,
    auth: AuthContext = Depends(require_staff_or_admin),
    db: Session = Depends(get_db),
) -> Customer:
    assert_subscription_writable(db, auth.tenant_id)  # type: ignore[arg-type]
    c = Customer(tenant_id=auth.tenant_id, **body.model_dump())
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


@router.delete("/customers/{customer_id}", status_code=204, response_class=Response)
def delete_customer(
    customer_id: UUID,
    auth: AuthContext = Depends(require_staff_or_admin),
    db: Session = Depends(get_db),
) -> Response:
    assert_subscription_writable(db, auth.tenant_id)  # type: ignore[arg-type]
    c = (
        db.query(Customer)
        .filter(
            Customer.id == customer_id,
            Customer.tenant_id == auth.tenant_id,
            Customer.deleted_at.is_(None),
        )
        .first()
    )
    if not c:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")
    c.soft_delete()
    write_audit(
        db,
        action="customer.delete",
        actor_user_id=auth.user.id,
        tenant_id=auth.tenant_id,
        entity_type="customer",
        entity_id=str(customer_id),
    )
    db.commit()
    return Response(status_code=204)


@router.get("/customers/{customer_id}", response_model=CustomerOut)
def get_customer(
    customer_id: UUID,
    auth: AuthContext = Depends(require_staff_or_admin),
    db: Session = Depends(get_db),
) -> Customer:
    c = (
        db.query(Customer)
        .filter(
            Customer.id == customer_id,
            Customer.tenant_id == auth.tenant_id,
            Customer.deleted_at.is_(None),
        )
        .first()
    )
    if not c:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")
    return c




@router.get("/services", response_model=list[ServiceOut])
def list_services(
    auth: AuthContext = Depends(require_staff_or_admin), db: Session = Depends(get_db)
) -> list[ServiceCatalog]:
    return (
        db.query(ServiceCatalog)
        .filter(ServiceCatalog.tenant_id == auth.tenant_id, ServiceCatalog.deleted_at.is_(None))
        .all()
    )


@router.post("/services", response_model=ServiceOut, status_code=201)
def create_service(
    body: ServiceIn,
    auth: AuthContext = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
) -> ServiceCatalog:
    assert_subscription_writable(db, auth.tenant_id)  # type: ignore[arg-type]
    s = ServiceCatalog(tenant_id=auth.tenant_id, **body.model_dump())
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


@router.delete("/services/{service_id}", status_code=204, response_class=Response)
def delete_service(
    service_id: UUID,
    auth: AuthContext = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
) -> Response:
    assert_subscription_writable(db, auth.tenant_id)  # type: ignore[arg-type]
    s = (
        db.query(ServiceCatalog)
        .filter(
            ServiceCatalog.id == service_id,
            ServiceCatalog.tenant_id == auth.tenant_id,
            ServiceCatalog.deleted_at.is_(None),
        )
        .first()
    )
    if not s:
        raise HTTPException(status_code=404, detail="Serviço não encontrado")
    s.soft_delete()
    write_audit(
        db,
        action="service.delete",
        actor_user_id=auth.user.id,
        tenant_id=auth.tenant_id,
        entity_type="service",
        entity_id=str(service_id),
    )
    db.commit()
    return Response(status_code=204)




@router.get("/appointments", response_model=list[AppointmentOut])
def list_appointments(
    auth: AuthContext = Depends(require_staff_or_admin), db: Session = Depends(get_db)
) -> list[Appointment]:
    return (
        db.query(Appointment)
        .filter(Appointment.tenant_id == auth.tenant_id, Appointment.deleted_at.is_(None))
        .order_by(Appointment.starts_at)
        .all()
    )


@router.post("/appointments", response_model=AppointmentOut, status_code=201)
def create_appointment(
    body: AppointmentIn,
    auth: AuthContext = Depends(require_staff_or_admin),
    db: Session = Depends(get_db),
) -> Appointment:
    assert_subscription_writable(db, auth.tenant_id)  # type: ignore[arg-type]
    cust = (
        db.query(Customer)
        .filter(Customer.id == body.customer_id, Customer.tenant_id == auth.tenant_id)
        .first()
    )
    if not cust:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")
    a = Appointment(
        tenant_id=auth.tenant_id,
        customer_id=body.customer_id,
        service_id=body.service_id,
        starts_at=body.starts_at,
        notes=body.notes,
        status="scheduled",
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


@router.post("/appointments/{appointment_id}/transition", response_model=AppointmentOut)
def transition_appointment(
    appointment_id: UUID,
    body: TransitionIn,
    auth: AuthContext = Depends(require_staff_or_admin),
    db: Session = Depends(get_db),
) -> Appointment:
    assert_subscription_writable(db, auth.tenant_id)  # type: ignore[arg-type]
    a = (
        db.query(Appointment)
        .filter(
            Appointment.id == appointment_id,
            Appointment.tenant_id == auth.tenant_id,
            Appointment.deleted_at.is_(None),
        )
        .first()
    )
    if not a:
        raise HTTPException(status_code=404, detail="Agendamento não encontrado")
    try:
        a.status = transition(APPOINTMENT_TRANSITIONS, a.status, body.status)
    except IllegalTransitionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    db.refresh(a)
    return a




def _next_os_number(db: Session, tenant_id: UUID) -> str:
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    prefix = f"OS-{day}-"
    count = (
        db.query(WorkOrder)
        .filter(WorkOrder.tenant_id == tenant_id, WorkOrder.number.like(f"{prefix}%"))
        .count()
    )
    return f"{prefix}{count + 1:04d}"


@router.get("/work-orders", response_model=list[WorkOrderOut])
def list_work_orders(
    auth: AuthContext = Depends(require_staff_or_admin), db: Session = Depends(get_db)
) -> list[WorkOrder]:
    return (
        db.query(WorkOrder)
        .filter(WorkOrder.tenant_id == auth.tenant_id, WorkOrder.deleted_at.is_(None))
        .order_by(WorkOrder.created_at.desc())
        .all()
    )


@router.post("/work-orders", response_model=WorkOrderOut, status_code=201)
def create_work_order(
    body: WorkOrderIn,
    auth: AuthContext = Depends(require_staff_or_admin),
    db: Session = Depends(get_db),
) -> WorkOrder:
    assert_subscription_writable(db, auth.tenant_id)  # type: ignore[arg-type]
    sub = db.query(Subscription).filter(Subscription.tenant_id == auth.tenant_id).first()
    plan = db.get(Plan, sub.plan_code) if sub else None
    if plan:
        month = datetime.now(timezone.utc).month
        year = datetime.now(timezone.utc).year
        used = (
            db.query(WorkOrder)
            .filter(
                WorkOrder.tenant_id == auth.tenant_id,
                WorkOrder.deleted_at.is_(None),
                extract("month", WorkOrder.created_at) == month,
                extract("year", WorkOrder.created_at) == year,
            )
            .count()
        )
        if used >= plan.max_work_orders_month:
            raise HTTPException(status_code=400, detail="Limite mensal de OS do plano")

    cust = (
        db.query(Customer)
        .filter(Customer.id == body.customer_id, Customer.tenant_id == auth.tenant_id)
        .first()
    )
    if not cust:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")

    wo = WorkOrder(
        tenant_id=auth.tenant_id,
        customer_id=body.customer_id,
        appointment_id=body.appointment_id,
        number=_next_os_number(db, auth.tenant_id),  # type: ignore[arg-type]
        title=body.title,
        description=body.description,
        total_cents=body.total_cents,
        status="draft",
    )
    db.add(wo)
    db.commit()
    db.refresh(wo)
    return wo


@router.get("/work-orders/{work_order_id}", response_model=WorkOrderOut)
def get_work_order(
    work_order_id: UUID,
    auth: AuthContext = Depends(require_staff_or_admin),
    db: Session = Depends(get_db),
) -> WorkOrder:
    wo = (
        db.query(WorkOrder)
        .filter(
            WorkOrder.id == work_order_id,
            WorkOrder.tenant_id == auth.tenant_id,
            WorkOrder.deleted_at.is_(None),
        )
        .first()
    )
    if not wo:
        raise HTTPException(status_code=404, detail="OS não encontrada")
    return wo


@router.post("/work-orders/{work_order_id}/transition", response_model=WorkOrderOut)
def transition_work_order(
    work_order_id: UUID,
    body: TransitionIn,
    auth: AuthContext = Depends(require_staff_or_admin),
    db: Session = Depends(get_db),
) -> WorkOrder:
    assert_subscription_writable(db, auth.tenant_id)  # type: ignore[arg-type]
    wo = (
        db.query(WorkOrder)
        .filter(
            WorkOrder.id == work_order_id,
            WorkOrder.tenant_id == auth.tenant_id,
            WorkOrder.deleted_at.is_(None),
        )
        .first()
    )
    if not wo:
        raise HTTPException(status_code=404, detail="OS não encontrada")
    try:
        wo.status = transition(WORK_ORDER_TRANSITIONS, wo.status, body.status)
    except IllegalTransitionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    db.refresh(wo)
    return wo




@router.get("/billing/subscription", response_model=SubscriptionOut)
def get_subscription(
    auth: AuthContext = Depends(require_tenant_admin), db: Session = Depends(get_db)
) -> Subscription:
    sub = (
        db.query(Subscription)
        .filter(Subscription.tenant_id == auth.tenant_id, Subscription.deleted_at.is_(None))
        .first()
    )
    if not sub:
        raise HTTPException(status_code=404, detail="Sem assinatura")
    return sub


@router.post("/billing/checkout", response_model=CheckoutOut)
def checkout(
    body: CheckoutIn,
    auth: AuthContext = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
) -> CheckoutOut:
    settings = get_settings()
    plan = db.get(Plan, body.plan_code)
    if not plan:
        raise HTTPException(status_code=404, detail="Plano inválido")
    sub = db.query(Subscription).filter(Subscription.tenant_id == auth.tenant_id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Sem assinatura")

    amount = 0 if body.plan_code == "free" else settings.pro_price_cents
    if amount == 0:
        sub.plan_code = "free"
        sub.status = "active"
        sub.current_period_end = date.today() + timedelta(days=30)
        db.commit()
        return CheckoutOut(
            payment_id=sub.id,
            amount_cents=0,
            pix_copy_paste="",
            provider_ref="free",
            status="paid",
        )

    ref, copy = create_pix_charge(amount_cents=amount, description=f"OficinaFlow {body.plan_code}")
    payment = Payment(
        tenant_id=auth.tenant_id,
        subscription_id=sub.id,
        amount_cents=amount,
        status="pending",
        provider_ref=ref,
        pix_copy_paste=copy,
        plan_code=body.plan_code,
    )
    db.add(payment)
    write_audit(
        db,
        action="billing.checkout",
        actor_user_id=auth.user.id,
        tenant_id=auth.tenant_id,
        entity_type="payment",
        entity_id="pending",
        detail=f"plan={body.plan_code} amount={amount}",
    )
    db.commit()
    db.refresh(payment)
    return CheckoutOut(
        payment_id=payment.id,
        amount_cents=payment.amount_cents,
        pix_copy_paste=payment.pix_copy_paste,
        provider_ref=payment.provider_ref,
        status=payment.status,
    )


@router.get("/billing/payments", response_model=list[PaymentOut])
def list_payments(
    auth: AuthContext = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
) -> list[Payment]:
    return (
        db.query(Payment)
        .filter(Payment.tenant_id == auth.tenant_id, Payment.deleted_at.is_(None))
        .order_by(Payment.created_at.desc())
        .limit(50)
        .all()
    )


@router.get("/billing/webhook-events", response_model=list[WebhookEventOut])
def list_tenant_webhook_events(
    auth: AuthContext = Depends(require_tenant_admin),
    db: Session = Depends(get_db),
) -> list[WebhookEvent]:
    return (
        db.query(WebhookEvent)
        .join(Payment, Payment.id == WebhookEvent.payment_id)
        .filter(
            Payment.tenant_id == auth.tenant_id,
            WebhookEvent.deleted_at.is_(None),
        )
        .order_by(WebhookEvent.created_at.desc())
        .limit(50)
        .all()
    )


@router.get("/platform/webhook-events", response_model=list[WebhookEventOut])
def platform_webhook_events(
    auth: AuthContext = Depends(require_platform_admin),
    db: Session = Depends(get_db),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[WebhookEvent]:
    _ = auth
    q = db.query(WebhookEvent).filter(WebhookEvent.deleted_at.is_(None)).order_by(WebhookEvent.created_at.desc())
    if status_filter:
        q = q.filter(WebhookEvent.status == status_filter)
    return q.limit(limit).all()


@router.get("/platform/webhook-events/stats")
def platform_webhook_stats(
    auth: AuthContext = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> dict:
    _ = auth
    statuses = ("recebido", "processando", "processado", "falhou")
    counts = {s: 0 for s in statuses}
    for status_val, n in (
        db.query(WebhookEvent.status, func.count(WebhookEvent.id)).group_by(WebhookEvent.status).all()
    ):
        counts[str(status_val)] = int(n)
    return {"by_status": counts, "failed": counts.get("falhou", 0)}


@router.post("/webhooks/pix")
def pix_webhook(
    payload: dict,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    client = request.client.host if request.client else "unknown"
    if not allow_request(f"webhook:{client}", limit=60, window=60):
        raise HTTPException(status_code=429, detail="Rate limit webhook")
    return accept_pix_webhook(db, payload)
