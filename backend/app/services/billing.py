from __future__ import annotations

import hashlib
import json
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger
from app.models import Payment, WebhookEvent

logger = get_logger("oficinaflow.billing")


def create_pix_charge(*, amount_cents: int, description: str) -> tuple[str, str]:
    _ = description
    settings = get_settings()
    ref = f"of-{uuid4().hex[:16]}"
    if not settings.mp_access_token:
        copy = (
            f"00020126580014BR.GOV.BCB.PIX0136{ref}52040000530398654"
            f"{amount_cents:06d}5802BR5925OFICINAFLOW DEMO6009SAO PAULO62070503***6304ABCD"
        )
        return ref, copy
    copy = f"MP-SANDBOX-{ref}-{amount_cents}"
    return ref, copy


def build_event_key(*, payment_id: UUID, action: str) -> str:
    return f"pix:{payment_id}:{action}"


def payload_hash(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def enqueue_billing_job(event_id: UUID) -> None:
    from redis import Redis
    from rq import Queue

    settings = get_settings()
    conn = Redis.from_url(
        settings.redis_url,
        socket_connect_timeout=1,
        socket_timeout=2,
    )
    q = Queue(
        "oficinaflow-billing",
        connection=conn,
        is_async=settings.rq_async,
        default_timeout=60,
    )
    kwargs = {}
    if settings.rq_async:
        from app.queue.jobs import on_billing_job_failure

        kwargs["failure_callback"] = on_billing_job_failure
    q.enqueue(
        "app.queue.jobs.process_billing_webhook",
        str(event_id),
        job_id=f"billing-{event_id}",
        **kwargs,
    )


def accept_pix_webhook(db: Session, payload: dict) -> dict:
    settings = get_settings()
    secret = str(payload.get("secret") or "")
    if secret != settings.webhook_demo_secret:
        raise HTTPException(status_code=401, detail="Webhook não autorizado")

    payment_id_raw = payload.get("payment_id")
    action = str(payload.get("action") or "approved")
    if not payment_id_raw:
        raise HTTPException(status_code=400, detail="payment_id obrigatório")

    payment_id = UUID(str(payment_id_raw))
    payment = db.get(Payment, payment_id)
    if not payment or payment.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Payment não encontrado")

    event_key = build_event_key(payment_id=payment_id, action=action)
    existing = db.query(WebhookEvent).filter(WebhookEvent.event_key == event_key).first()
    if existing:
        logger.info(
            "webhook_duplicate",
            extra={"event_key": event_key, "event_id": str(existing.id), "result": "duplicate"},
        )
        return {
            "duplicate": True,
            "event_id": str(existing.id),
            "status": existing.status,
        }

    event = WebhookEvent(
        event_key=event_key,
        payment_id=payment_id,
        payload=json.dumps(payload, default=str),
        payload_hash=payload_hash(payload),
        status="recebido",
        attempts=0,
        last_error="",
    )
    db.add(event)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.query(WebhookEvent).filter(WebhookEvent.event_key == event_key).first()
        if existing:
            return {
                "duplicate": True,
                "event_id": str(existing.id),
                "status": existing.status,
            }
        raise
    db.refresh(event)

    logger.info(
        "webhook_accepted",
        extra={
            "event_id": str(event.id),
            "event_key": event_key,
            "payment_id": str(payment_id),
            "tenant_id": str(payment.tenant_id),
            "result": "recebido",
        },
    )

    try:
        enqueue_billing_job(event.id)
    except Exception as exc:  # noqa: BLE001
        logger.info(
            "webhook_enqueue_failed",
            extra={
                "event_id": str(event.id),
                "event_key": event_key,
                "result": "enqueue_failed",
            },
        )
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Fila indisponível — evento persistido como recebido",
                "event_id": str(event.id),
                "status": "recebido",
                "note": str(exc)[:120],
            },
        ) from exc

    db.refresh(event)
    return {
        "accepted": True,
        "event_id": str(event.id),
        "status": event.status,
        "queued": settings.rq_async,
    }
