const API = "/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const detail = body.detail;
    const msg = Array.isArray(detail)
      ? detail.map((d: { msg?: string }) => d.msg).join(", ")
      : detail || res.statusText || "Erro";
    throw new Error(msg);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

export type Me = {
  user: { id: string; email: string; full_name: string; is_platform_admin: boolean };
  tenant: { id: string; slug: string; name: string; status: string } | null;
  role: string | null;
  is_platform_admin: boolean;
};

export const api = {
  login: (email: string, password: string, tenant_slug?: string) =>
    request<Me>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password, tenant_slug: tenant_slug || null }),
    }),
  logout: () => request("/auth/logout", { method: "POST" }),
  me: () => request<Me>("/auth/me"),
  customers: () => request<any[]>("/customers"),
  createCustomer: (data: object) =>
    request("/customers", { method: "POST", body: JSON.stringify(data) }),
  services: () => request<any[]>("/services"),
  createService: (data: object) =>
    request("/services", { method: "POST", body: JSON.stringify(data) }),
  appointments: () => request<any[]>("/appointments"),
  createAppointment: (data: object) =>
    request("/appointments", { method: "POST", body: JSON.stringify(data) }),
  transitionAppointment: (id: string, status: string) =>
    request(`/appointments/${id}/transition`, {
      method: "POST",
      body: JSON.stringify({ status }),
    }),
  workOrders: () => request<any[]>("/work-orders"),
  createWorkOrder: (data: object) =>
    request("/work-orders", { method: "POST", body: JSON.stringify(data) }),
  transitionWorkOrder: (id: string, status: string) =>
    request(`/work-orders/${id}/transition`, {
      method: "POST",
      body: JSON.stringify({ status }),
    }),
  subscription: () => request<any>("/billing/subscription"),
  checkout: (plan_code: string) =>
    request<any>("/billing/checkout", {
      method: "POST",
      body: JSON.stringify({ plan_code }),
    }),
  simulateWebhook: (payment_id: string) =>
    request<{ accepted?: boolean; duplicate?: boolean; status?: string; event_id?: string }>(
      "/webhooks/pix",
      {
        method: "POST",
        body: JSON.stringify({
          payment_id,
          action: "approved",
          secret: "demo-webhook-secret",
        }),
      }
    ),
  platformTenants: () => request<any[]>("/platform/tenants"),
  platformWebhookEvents: (status?: string) =>
    request<any[]>(
      status ? `/platform/webhook-events?status=${encodeURIComponent(status)}` : "/platform/webhook-events"
    ),
  platformWebhookStats: () => request<any>("/platform/webhook-events/stats"),
  memberships: () => request<any[]>("/memberships"),
  createMembership: (data: object) =>
    request("/memberships", { method: "POST", body: JSON.stringify(data) }),
  deleteMembership: (id: string) =>
    request(`/memberships/${id}`, { method: "DELETE" }),
  deleteCustomer: (id: string) =>
    request(`/customers/${id}`, { method: "DELETE" }),
  deleteService: (id: string) =>
    request(`/services/${id}`, { method: "DELETE" }),
  patchTenant: (data: object) =>
    request("/tenant", { method: "PATCH", body: JSON.stringify(data) }),
  payments: () => request<any[]>("/billing/payments"),
  webhookEvents: () => request<any[]>("/billing/webhook-events"),
};

export function formatBRL(cents: number) {
  return (cents / 100).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

export function formatDateBR(iso: string) {
  return new Date(iso).toLocaleString("pt-BR", { timeZone: "America/Sao_Paulo" });
}
