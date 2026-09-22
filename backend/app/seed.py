from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models import (
    Appointment,
    Customer,
    Membership,
    Plan,
    ServiceCatalog,
    Subscription,
    Tenant,
    User,
    WorkOrder,
)


def run() -> None:
    db = SessionLocal()
    try:
        if db.query(Plan).count() == 0:
            db.add_all(
                [
                    Plan(
                        code="free",
                        name="Free",
                        price_cents=0,
                        max_staff=3,
                        max_work_orders_month=20,
                    ),
                    Plan(
                        code="pro",
                        name="Pro",
                        price_cents=9900,
                        max_staff=20,
                        max_work_orders_month=10_000,
                    ),
                ]
            )

        def ensure_user(email: str, name: str, *, platform: bool = False) -> User:
            u = db.query(User).filter(User.email == email).first()
            if u:
                return u
            u = User(
                email=email,
                full_name=name,
                password_hash=hash_password("senha123"),
                is_platform_admin=platform,
            )
            db.add(u)
            db.flush()
            return u

        platform = ensure_user("platform@oficinaflow.com", "Platform Admin", platform=True)
        admin_a = ensure_user("admin@oficina-alfa.com", "Admin Oficina Alfa")
        staff_a = ensure_user("staff@oficina-alfa.com", "Staff Alfa")
        admin_b = ensure_user("admin@oficina-beta.com", "Admin Oficina Beta")

        def ensure_tenant(slug: str, name: str) -> Tenant:
            t = db.query(Tenant).filter(Tenant.slug == slug).first()
            if t:
                return t
            t = Tenant(slug=slug, name=name, status="active")
            db.add(t)
            db.flush()
            db.add(
                Subscription(
                    tenant_id=t.id,
                    plan_code="free",
                    status="active",
                    current_period_end=date.today() + timedelta(days=30),
                )
            )
            return t

        alfa = ensure_tenant("oficina-alfa", "Oficina Alfa Auto")
        beta = ensure_tenant("oficina-beta", "Oficina Beta Motos")

        def ensure_membership(tenant_id, user_id, role: str) -> None:
            m = (
                db.query(Membership)
                .filter(Membership.tenant_id == tenant_id, Membership.user_id == user_id)
                .first()
            )
            if not m:
                db.add(Membership(tenant_id=tenant_id, user_id=user_id, role=role))

        ensure_membership(alfa.id, admin_a.id, "TENANT_ADMIN")
        ensure_membership(alfa.id, staff_a.id, "STAFF")
        ensure_membership(beta.id, admin_b.id, "TENANT_ADMIN")

        def ensure_customer(tenant_id, name: str, phone: str, document: str) -> Customer:
            c = (
                db.query(Customer)
                .filter(Customer.tenant_id == tenant_id, Customer.name == name)
                .first()
            )
            if c:
                return c
            c = Customer(tenant_id=tenant_id, name=name, phone=phone, document=document)
            db.add(c)
            db.flush()
            return c

        cust_a = ensure_customer(alfa.id, "João Silva", "49999990001", "123.456.789-00")
        cust_b = ensure_customer(beta.id, "Maria Souza", "49999990002", "987.654.321-00")

        if db.query(ServiceCatalog).filter(ServiceCatalog.tenant_id == alfa.id).count() == 0:
            db.add(
                ServiceCatalog(
                    tenant_id=alfa.id,
                    name="Troca de óleo",
                    duration_min=45,
                    price_cents=15000,
                )
            )
            db.add(
                ServiceCatalog(
                    tenant_id=alfa.id,
                    name="Revisão completa",
                    duration_min=120,
                    price_cents=45000,
                )
            )

        if db.query(Appointment).filter(Appointment.tenant_id == alfa.id).count() == 0:
            db.add(
                Appointment(
                    tenant_id=alfa.id,
                    customer_id=cust_a.id,
                    status="scheduled",
                    starts_at=datetime.now(timezone.utc) + timedelta(days=1),
                    notes="Cliente pediu óleo sintético",
                )
            )

        if db.query(WorkOrder).filter(WorkOrder.tenant_id == alfa.id).count() == 0:
            day = datetime.now(timezone.utc).strftime("%Y%m%d")
            db.add_all(
                [
                    WorkOrder(
                        tenant_id=alfa.id,
                        customer_id=cust_a.id,
                        number=f"OS-{day}-0001",
                        title="Troca de óleo + filtro",
                        description="Veículo Gol 2018",
                        total_cents=18000,
                        status="open",
                    ),
                    WorkOrder(
                        tenant_id=alfa.id,
                        customer_id=cust_a.id,
                        number=f"OS-{day}-0002",
                        title="Freio dianteiro",
                        description="Pastilhas + disco",
                        total_cents=32000,
                        status="open",
                    ),
                    WorkOrder(
                        tenant_id=alfa.id,
                        customer_id=cust_a.id,
                        number=f"OS-{day}-0003",
                        title="Alinhamento",
                        description="",
                        total_cents=12000,
                        status="in_progress",
                    ),
                    WorkOrder(
                        tenant_id=alfa.id,
                        customer_id=cust_a.id,
                        number=f"OS-{day}-0004",
                        title="Diagnóstico elétrico",
                        description="Aguardando módulo",
                        total_cents=25000,
                        status="waiting_parts",
                    ),
                    WorkOrder(
                        tenant_id=alfa.id,
                        customer_id=cust_a.id,
                        number=f"OS-{day}-0005",
                        title="Revisão 10k",
                        description="",
                        total_cents=45000,
                        status="done",
                    ),
                ]
            )
            db.add(
                WorkOrder(
                    tenant_id=beta.id,
                    customer_id=cust_b.id,
                    number=f"OS-{day}-0001",
                    title="Freio dianteiro",
                    description="CG 160",
                    total_cents=32000,
                    status="open",
                )
            )

        db.commit()
        print("Seed OK")
        print("  platform@oficinaflow.com / senha123")
        print("  admin@oficina-alfa.com / senha123 (tenant: oficina-alfa)")
        print("  staff@oficina-alfa.com / senha123 (tenant: oficina-alfa)")
        print("  admin@oficina-beta.com / senha123 (tenant: oficina-beta)")
        _ = platform
    finally:
        db.close()


if __name__ == "__main__":
    run()
