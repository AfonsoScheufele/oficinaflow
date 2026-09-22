from __future__ import annotations

import os
from datetime import date, timedelta
from uuid import uuid4

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
from app.models import Customer, Membership, Plan, Subscription, Tenant, User


def _db_ready() -> bool:
    try:
        engine = create_engine(get_settings().database_url)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _db_ready(), reason="Postgres oficinaflow não disponível")


def test_soft_delete_customer_hides_from_list():
    get_settings.cache_clear()
    engine = create_engine(get_settings().database_url)
    Session = sessionmaker(bind=engine)
    db = Session()

    if not db.query(Plan).filter(Plan.code == "free").first():
        db.add(Plan(code="free", name="Free", price_cents=0, max_staff=5, max_work_orders_month=100))
        db.commit()

    tenant = Tenant(id=uuid4(), slug=f"t-sd-{uuid4().hex[:6]}", name="Soft Del Co", status="active")
    user = User(
        id=uuid4(),
        email=f"admin-sd-{uuid4().hex[:6]}@test.com",
        full_name="Admin SD",
        password_hash=hash_password("senha123"),
    )
    db.add_all([tenant, user])
    db.flush()
    db.add(
        Subscription(
            tenant_id=tenant.id,
            plan_code="free",
            status="active",
            current_period_end=date.today() + timedelta(days=30),
        )
    )
    db.add(Membership(tenant_id=tenant.id, user_id=user.id, role="TENANT_ADMIN"))
    cust = Customer(tenant_id=tenant.id, name="Cliente Soft", phone="", document="", notes="")
    db.add(cust)
    db.commit()
    cust_id = str(cust.id)
    email = user.email
    slug = tenant.slug
    db.close()

    def override():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override
    with TestClient(app) as c:
        login = c.post(
            "/api/auth/login",
            json={"email": email, "password": "senha123", "tenant_slug": slug},
        )
        assert login.status_code == 200
        before = c.get("/api/customers")
        assert before.status_code == 200
        assert any(x["id"] == cust_id for x in before.json())

        deleted = c.delete(f"/api/customers/{cust_id}")
        assert deleted.status_code == 204

        after = c.get("/api/customers")
        assert after.status_code == 200
        assert not any(x["id"] == cust_id for x in after.json())

    app.dependency_overrides.clear()
