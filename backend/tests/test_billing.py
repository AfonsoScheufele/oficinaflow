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
os.environ.setdefault("RQ_ASYNC", "false")

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.session import get_db
from app.main import app
from app.models import Membership, Payment, Plan, Subscription, Tenant, User, WebhookEvent
from app.seed import run as seed_run


def _db_ready() -> bool:
    try:
        engine = create_engine(get_settings().database_url)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _db_ready(), reason="Postgres oficinaflow não disponível")


def _make_pending_payment(Session):
    db = Session()
    if not db.query(Plan).filter(Plan.code == "pro").first():
        db.add(Plan(code="pro", name="Pro", price_cents=9900, max_staff=20, max_work_orders_month=10000))
        db.add(Plan(code="free", name="Free", price_cents=0, max_staff=3, max_work_orders_month=20))
        db.commit()

    tenant = Tenant(id=uuid4(), slug=f"t-bill-{uuid4().hex[:6]}", name="Bill Co", status="active")
    user = User(
        id=uuid4(),
        email=f"admin-{uuid4().hex[:6]}@test.com",
        full_name="Admin",
        password_hash=hash_password("senha123"),
    )
    db.add_all([tenant, user])
    db.flush()
    sub = Subscription(
        tenant_id=tenant.id,
        plan_code="free",
        status="active",
        current_period_end=date.today() + timedelta(days=7),
    )
    db.add(sub)
    db.flush()
    payment = Payment(
        tenant_id=tenant.id,
        subscription_id=sub.id,
        amount_cents=9900,
        status="pending",
        provider_ref="ref-test",
        pix_copy_paste="pix",
        plan_code="pro",
    )
    db.add(Membership(tenant_id=tenant.id, user_id=user.id, role="TENANT_ADMIN"))
    db.add(payment)
    db.commit()
    payment_id = payment.id
    sub_id = sub.id
    db.close()
    return payment_id, sub_id


def test_webhook_idempotent():
    get_settings.cache_clear()
    engine = create_engine(get_settings().database_url)
    Session = sessionmaker(bind=engine)
    payment_uuid, sub_id = _make_pending_payment(Session)
    payment_id = str(payment_uuid)

    def override():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override
    with TestClient(app) as c:
        body = {"payment_id": payment_id, "action": "approved", "secret": "demo-webhook-secret"}
        r1 = c.post("/api/webhooks/pix", json=body)
        r2 = c.post("/api/webhooks/pix", json=body)
        assert r1.status_code == 200
        assert r1.json().get("status") == "processado"
        assert r2.status_code == 200
        assert r2.json().get("duplicate") is True

        db2 = Session()
        p = db2.get(Payment, payment_uuid)
        assert p is not None and p.status == "paid"
        s = db2.get(Subscription, sub_id)
        assert s is not None and s.plan_code == "pro" and s.status == "active"
        db2.close()

    app.dependency_overrides.clear()
    seed_run()


def test_webhook_unauthorized():
    get_settings.cache_clear()
    engine = create_engine(get_settings().database_url)
    Session = sessionmaker(bind=engine)
    payment_uuid, _ = _make_pending_payment(Session)

    def override():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override
    with TestClient(app) as c:
        r = c.post(
            "/api/webhooks/pix",
            json={"payment_id": str(payment_uuid), "action": "approved", "secret": "wrong"},
        )
        assert r.status_code == 401
    app.dependency_overrides.clear()


def test_webhook_partial_failure_visible():
    get_settings.cache_clear()
    engine = create_engine(get_settings().database_url)
    Session = sessionmaker(bind=engine)
    payment_uuid, _ = _make_pending_payment(Session)

    def override():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override
    with TestClient(app) as c:
        body = {
            "payment_id": str(payment_uuid),
            "action": "approved",
            "secret": "demo-webhook-secret",
            "force_fail": True,
        }
        r = c.post("/api/webhooks/pix", json=body)
        assert r.status_code == 200
        data = r.json()
        assert data.get("accepted") is True
        assert data.get("status") in ("recebido", "falhou")

        db2 = Session()
        p = db2.get(Payment, payment_uuid)
        assert p is not None and p.status == "pending"
        ev = db2.get(WebhookEvent, data["event_id"])
        assert ev is not None
        assert ev.last_error
        assert "force_fail" in ev.last_error
        assert ev.attempts >= 1
        db2.close()

    app.dependency_overrides.clear()
