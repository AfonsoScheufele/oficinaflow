from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://oficinaflow:oficinaflow@localhost:5436/oficinaflow",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6383/0")
os.environ.setdefault("JWT_SECRET", "test-secret-oficinaflow-32chars-min")
os.environ.setdefault("WEBHOOK_DEMO_SECRET", "demo-webhook-secret")

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.session import get_db
from app.main import app
from app.models import Membership, Tenant, User, WorkOrder, Customer, Subscription, Plan
from datetime import date, timedelta
from uuid import uuid4


def _db_ready() -> bool:
    try:
        engine = create_engine(get_settings().database_url)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _db_ready(), reason="Postgres oficinaflow não disponível")


@pytest.fixture()
def client():
    get_settings.cache_clear()
    engine = create_engine(get_settings().database_url)
    TestingSession = sessionmaker(bind=engine)

    with engine.begin() as conn:
        conn.execute(text("SET LOCAL lock_timeout = '3s'"))
        for table in (
            "audit_logs",
            "webhook_events",
            "payments",
            "work_orders",
            "appointments",
            "services",
            "customers",
            "memberships",
            "subscriptions",
            "tenants",
            "users",
            "plans",
        ):
            conn.execute(text(f"TRUNCATE {table} CASCADE"))

    db = TestingSession()
    db.add_all(
        [
            Plan(code="free", name="Free", price_cents=0, max_staff=5, max_work_orders_month=100),
            Plan(code="pro", name="Pro", price_cents=9900, max_staff=20, max_work_orders_month=10000),
        ]
    )
    t_a = Tenant(id=uuid4(), slug="t-alfa", name="Alfa", status="active")
    t_b = Tenant(id=uuid4(), slug="t-beta", name="Beta", status="active")
    db.add_all([t_a, t_b])
    db.flush()
    u_a = User(
        id=uuid4(),
        email="staff-a@test.com",
        full_name="Staff A",
        password_hash=hash_password("senha123"),
    )
    u_b = User(
        id=uuid4(),
        email="staff-b@test.com",
        full_name="Staff B",
        password_hash=hash_password("senha123"),
    )
    db.add_all([u_a, u_b])
    db.flush()
    db.add_all(
        [
            Membership(tenant_id=t_a.id, user_id=u_a.id, role="STAFF"),
            Membership(tenant_id=t_b.id, user_id=u_b.id, role="STAFF"),
            Subscription(
                tenant_id=t_a.id,
                plan_code="free",
                status="active",
                current_period_end=date.today() + timedelta(days=30),
            ),
            Subscription(
                tenant_id=t_b.id,
                plan_code="free",
                status="active",
                current_period_end=date.today() + timedelta(days=30),
            ),
        ]
    )
    c_a = Customer(tenant_id=t_a.id, name="Cliente A", phone="", document="", notes="")
    c_b = Customer(tenant_id=t_b.id, name="Cliente B", phone="", document="", notes="")
    db.add_all([c_a, c_b])
    db.flush()
    wo_b = WorkOrder(
        tenant_id=t_b.id,
        customer_id=c_b.id,
        number="OS-TEST-BETA",
        title="OS do Beta",
        description="",
        total_cents=1000,
        status="open",
    )
    db.add(wo_b)
    db.commit()
    wo_b_id = wo_b.id
    db.close()

    def override_get_db():
        s = TestingSession()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c, wo_b_id
    app.dependency_overrides.clear()
    from app.seed import run as seed_run

    seed_run()


def test_tenant_a_cannot_read_tenant_b_work_order(client):
    c, wo_b_id = client
    login = c.post(
        "/api/auth/login",
        json={"email": "staff-a@test.com", "password": "senha123", "tenant_slug": "t-alfa"},
    )
    assert login.status_code == 200
    resp = c.get(f"/api/work-orders/{wo_b_id}")
    assert resp.status_code == 404


def test_billing_gating_blocks_create_when_expired(client):
    c, _ = client
    get_settings.cache_clear()
    engine = create_engine(get_settings().database_url)
    Session = sessionmaker(bind=engine)
    db = Session()
    sub = db.query(Subscription).filter(Subscription.tenant_id.isnot(None)).first()
    tenant = db.query(Tenant).filter(Tenant.slug == "t-alfa").first()
    sub = db.query(Subscription).filter(Subscription.tenant_id == tenant.id).first()
    sub.status = "past_due"
    sub.current_period_end = date.today() - timedelta(days=1)
    db.commit()
    cust = db.query(Customer).filter(Customer.tenant_id == tenant.id).first()
    cust_id = str(cust.id)
    db.close()

    login = c.post(
        "/api/auth/login",
        json={"email": "staff-a@test.com", "password": "senha123", "tenant_slug": "t-alfa"},
    )
    assert login.status_code == 200
    resp = c.post(
        "/api/work-orders",
        json={"customer_id": cust_id, "title": "Nova OS", "description": "", "total_cents": 100},
    )
    assert resp.status_code == 402
