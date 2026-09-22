from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    tenant_slug: str | None = None


class UserOut(BaseModel):
    id: UUID
    email: EmailStr
    full_name: str
    is_platform_admin: bool

    model_config = {"from_attributes": True}


class TenantOut(BaseModel):
    id: UUID
    slug: str
    name: str
    status: str

    model_config = {"from_attributes": True}


class TenantPatch(BaseModel):
    name: str | None = None
    status: str | None = Field(default=None, pattern="^(active|inactive)$")


class MeResponse(BaseModel):
    user: UserOut
    tenant: TenantOut | None
    role: str | None
    is_platform_admin: bool


class MembershipCreate(BaseModel):
    email: EmailStr
    full_name: str
    password: str = Field(min_length=6)
    role: str = Field(pattern="^(TENANT_ADMIN|STAFF)$")


class MembershipOut(BaseModel):
    id: UUID
    user_id: UUID
    email: str
    full_name: str
    role: str

    model_config = {"from_attributes": True}


class CustomerIn(BaseModel):
    name: str
    phone: str = ""
    document: str = ""
    notes: str = ""


class CustomerOut(CustomerIn):
    id: UUID

    model_config = {"from_attributes": True}


class ServiceIn(BaseModel):
    name: str
    duration_min: int = 60
    price_cents: int = 0
    active: bool = True


class ServiceOut(ServiceIn):
    id: UUID

    model_config = {"from_attributes": True}


class AppointmentIn(BaseModel):
    customer_id: UUID
    service_id: UUID | None = None
    starts_at: datetime
    notes: str = ""


class AppointmentOut(BaseModel):
    id: UUID
    customer_id: UUID
    service_id: UUID | None
    status: str
    starts_at: datetime
    notes: str

    model_config = {"from_attributes": True}


class TransitionIn(BaseModel):
    status: str


class WorkOrderIn(BaseModel):
    customer_id: UUID
    appointment_id: UUID | None = None
    title: str
    description: str = ""
    total_cents: int = 0


class WorkOrderOut(BaseModel):
    id: UUID
    number: str
    customer_id: UUID
    appointment_id: UUID | None
    status: str
    title: str
    description: str
    total_cents: int

    model_config = {"from_attributes": True}


class SubscriptionOut(BaseModel):
    id: UUID
    plan_code: str
    status: str
    current_period_end: date

    model_config = {"from_attributes": True}


class CheckoutIn(BaseModel):
    plan_code: str = Field(pattern="^(free|pro)$")


class CheckoutOut(BaseModel):
    payment_id: UUID
    amount_cents: int
    pix_copy_paste: str
    provider_ref: str
    status: str


class PaymentOut(BaseModel):
    id: UUID
    amount_cents: int
    status: str
    plan_code: str
    provider_ref: str
    created_at: datetime

    model_config = {"from_attributes": True}


class WebhookEventOut(BaseModel):
    id: UUID
    event_key: str
    payment_id: UUID | None
    status: str
    attempts: int
    last_error: str
    processed_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class PlatformTenantCreate(BaseModel):
    slug: str
    name: str
    admin_email: EmailStr
    admin_name: str
    admin_password: str = Field(min_length=6)
