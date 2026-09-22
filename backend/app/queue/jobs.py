from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.session import SessionLocal
from app.models import Payment, Subscription, WebhookEvent

logger = get_logger("oficinaflow.queue")


def mark_billing_failed(event_id: str, error_message: str) -> None:
    db = SessionLocal()
    try:
        event = db.get(WebhookEvent, UUID(event_id))
        if not event:
            return
        if event.status == "processado":
            return
        event.status = "falhou"
        event.last_error = error_message[:500]
        db.commit()
        logger.info(
            "webhook_job_failed_final",
            extra={
                "event_id": event_id,
                "event_key": event.event_key,
                "attempt": event.attempts,
                "result": "falhou",
            },
        )
    finally:
        db.close()


def on_billing_job_failure(job, connection, type, value, traceback):  # noqa: A002, ARG001
    event_id = job.args[0] if job.args else None
    if not event_id:
        return
    mark_billing_failed(str(event_id), f"{type.__name__}: {value}" if type else str(value))


def apply_billing_event(db: Session, event: WebhookEvent) -> dict:
    if not event.payment_id:
        raise ValueError("payment_id ausente no evento")

    payment = db.get(Payment, event.payment_id)
    if not payment or payment.deleted_at is not None:
        raise ValueError("payment não encontrado")

    if payment.status == "paid":
        return {"ok": True, "already_paid": True, "payment_id": str(payment.id)}

    try:
        import json

        raw = json.loads(event.payload or "{}")
        if raw.get("force_fail"):
            raise RuntimeError("force_fail: simulação de falha parcial")
    except json.JSONDecodeError:
        pass

    payment.status = "paid"
    sub = db.get(Subscription, payment.subscription_id)
    if sub:
        sub.plan_code = payment.plan_code
        sub.status = "active"
        sub.current_period_end = date.today() + timedelta(days=30)

    return {
        "ok": True,
        "payment_id": str(payment.id),
        "tenant_id": str(payment.tenant_id),
        "plan_code": payment.plan_code,
    }


def process_billing_webhook(event_id: str) -> dict:
    settings = get_settings()
    max_attempts = settings.webhook_max_retries + 1
    db: Session = SessionLocal()
    try:
        event = db.get(WebhookEvent, UUID(event_id))
        if not event or event.deleted_at is not None:
            logger.info("webhook_job_missing", extra={"event_id": event_id, "result": "missing"})
            return {"ok": False, "reason": "missing"}

        if event.status == "processado":
            logger.info(
                "webhook_job_already_done",
                extra={"event_id": event_id, "event_key": event.event_key, "result": "already_processado"},
            )
            return {"ok": True, "duplicate": True}

        event.status = "processando"
        event.attempts = (event.attempts or 0) + 1
        event.last_error = ""
        db.commit()

        attempt = event.attempts
        event_key = event.event_key
        logger.info(
            "webhook_job_start",
            extra={
                "event_id": event_id,
                "event_key": event_key,
                "attempt": attempt,
                "result": "processando",
            },
        )

        try:
            result = apply_billing_event(db, event)
            event.status = "processado"
            event.processed_at = datetime.now(timezone.utc)
            event.last_error = ""
            db.commit()
            logger.info(
                "webhook_job_done",
                extra={
                    "event_id": event_id,
                    "event_key": event_key,
                    "attempt": attempt,
                    "payment_id": result.get("payment_id"),
                    "result": "processado",
                },
            )
            return result
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            event = db.get(WebhookEvent, UUID(event_id))
            if event:
                event.last_error = str(exc)[:500]
                if event.attempts >= max_attempts:
                    event.status = "falhou"
                else:
                    event.status = "recebido"
                db.commit()
                final_status = event.status
            else:
                final_status = "falhou"
            logger.info(
                "webhook_job_error",
                extra={
                    "event_id": event_id,
                    "event_key": event_key,
                    "attempt": attempt,
                    "result": "falhou" if attempt >= max_attempts else "retry",
                },
            )
            if settings.rq_async:
                raise
            return {"ok": False, "error": str(exc)[:200], "status": final_status}
    finally:
        db.close()
