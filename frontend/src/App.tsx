import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Navigate, NavLink, Outlet, Route, Routes, useNavigate } from "react-router-dom";
import { api, formatBRL, formatDateBR, type Me } from "./api";
import "./index.css";

const STATUS_LABEL: Record<string, string> = {
  scheduled: "Agendado",
  confirmed: "Confirmado",
  in_progress: "Em andamento",
  done: "Concluído",
  cancelled: "Cancelado",
  no_show: "Não compareceu",
  draft: "Rascunho",
  open: "Aberta",
  waiting_parts: "Aguardando peça",
  active: "Ativa",
  past_due: "Vencida",
  trialing: "Trial",
};

function statusLabel(s: string) {
  return STATUS_LABEL[s] || s;
}

function PageHead({
  eyebrow,
  title,
  subtitle,
}: {
  eyebrow: string;
  title: string;
  subtitle?: string;
}) {
  return (
    <header className="page-head">
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h2>{title}</h2>
        {subtitle && <p>{subtitle}</p>}
      </div>
    </header>
  );
}

function useMe() {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .me()
      .then(setMe)
      .catch(() => setMe(null))
      .finally(() => setLoading(false));
  }, []);

  return { me, setMe, loading };
}

function Login({ onLogin }: { onLogin: (m: Me) => void }) {
  const [email, setEmail] = useState("admin@oficina-alfa.com");
  const [password, setPassword] = useState("senha123");
  const [tenant, setTenant] = useState("oficina-alfa");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      const me = await api.login(email, password, tenant || undefined);
      onLogin(me);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha no login");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-page">
      <section className="login-hero" aria-hidden={false}>
        <div className="login-hero-inner">
          <p className="eyebrow">SaaS B2B · Multi-tenant</p>
          <h1 className="brand">OficinaFlow</h1>
          <p>
            Agenda e ordens de serviço para oficinas. Cada empresa no seu espaço, com papéis
            claros e assinatura da plataforma.
          </p>
        </div>
      </section>
      <section className="login-panel">
        <form className="login-box" onSubmit={submit}>
          <h2>Entrar</h2>
          <p className="lede">Use o tenant da oficina. Platform admin deixa o slug vazio.</p>
          {error && <div className="error">{error}</div>}
          <div className="field">
            <label>E-mail</label>
            <input value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" />
          </div>
          <div className="field">
            <label>Senha</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
            />
          </div>
          <div className="field">
            <label>Tenant (slug)</label>
            <input
              value={tenant}
              onChange={(e) => setTenant(e.target.value)}
              placeholder="ex.: oficina-alfa"
            />
          </div>
          <button className="btn" type="submit" disabled={busy}>
            {busy ? "Entrando…" : "Entrar na oficina"}
          </button>
          <div className="login-hint">
            Demo: admin@oficina-alfa.com · senha123 · oficina-alfa
          </div>
        </form>
      </section>
    </div>
  );
}

function Shell({ me, onLogout }: { me: Me; onLogout: () => void }) {
  const isPlatform = me.is_platform_admin && !me.tenant;
  const linkClass = ({ isActive }: { isActive: boolean }) => (isActive ? "active" : undefined);

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand-block">
          <div className="brand-mark">OF</div>
          <div>
            <h1>OficinaFlow</h1>
            <p className="tenant-chip">{me.tenant?.name || "Platform admin"}</p>
          </div>
        </div>
        <nav>
          <div className="nav-label">{isPlatform ? "Plataforma" : "Operação"}</div>
          {isPlatform ? (
            <NavLink to="/platform" className={linkClass}>
              Tenants
            </NavLink>
          ) : (
            <>
              <NavLink to="/agenda" className={linkClass}>
                Agenda
              </NavLink>
              <NavLink to="/os" className={linkClass}>
                Ordens de serviço
              </NavLink>
              <NavLink to="/clientes" className={linkClass}>
                Clientes
              </NavLink>
              {me.role === "TENANT_ADMIN" && (
                <>
                  <div className="nav-label">Gestão</div>
                  <NavLink to="/servicos" className={linkClass}>
                    Serviços
                  </NavLink>
                  <NavLink to="/equipe" className={linkClass}>
                    Equipe
                  </NavLink>
                  <NavLink to="/assinatura" className={linkClass}>
                    Assinatura
                  </NavLink>
                </>
              )}
            </>
          )}
        </nav>
        <div className="sidebar-foot">
          <button type="button" className="btn-ghost" onClick={onLogout}>
            Sair · {me.user.full_name.split(" ")[0]}
          </button>
        </div>
      </aside>
      <main className="main">
        <Outlet />
      </main>
    </div>
  );
}

function Agenda() {
  const [items, setItems] = useState<any[]>([]);
  const [customers, setCustomers] = useState<any[]>([]);
  const [customerId, setCustomerId] = useState("");
  const [startsAt, setStartsAt] = useState("");
  const [err, setErr] = useState("");

  async function load() {
    const [a, c] = await Promise.all([api.appointments(), api.customers()]);
    setItems(a);
    setCustomers(c);
    if (c[0]) setCustomerId(c[0].id);
  }

  useEffect(() => {
    load().catch((e) => setErr(String(e.message)));
  }, []);

  async function create(e: FormEvent) {
    e.preventDefault();
    try {
      await api.createAppointment({
        customer_id: customerId,
        starts_at: new Date(startsAt).toISOString(),
        notes: "",
      });
      await load();
    } catch (ex) {
      setErr(ex instanceof Error ? ex.message : "Erro");
    }
  }

  const openCount = items.filter((a) => !["done", "cancelled", "no_show"].includes(a.status)).length;

  return (
    <div className="page">
      <PageHead
        eyebrow="Dia a dia"
        title="Agenda"
        subtitle="Horários da oficina: confirme, inicie e conclua."
      />
      <div className="page-body">
        <div className="stat-row">
          <div className="stat">
            <div className="label">Agendamentos</div>
            <div className="value">{items.length}</div>
          </div>
          <div className="stat">
            <div className="label">Em aberto</div>
            <div className="value">{openCount}</div>
          </div>
          <div className="stat">
            <div className="label">Clientes</div>
            <div className="value">{customers.length}</div>
          </div>
          <div className="stat">
            <div className="label">Hoje</div>
            <div className="value" style={{ fontSize: "1.15rem" }}>
              {new Date().toLocaleDateString("pt-BR")}
            </div>
          </div>
        </div>
        {err && <div className="error">{err}</div>}
        <form onSubmit={create} className="toolbar cols-3">
          <div className="field">
            <label>Cliente</label>
            <select value={customerId} onChange={(e) => setCustomerId(e.target.value)}>
              {customers.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label>Início</label>
            <input type="datetime-local" value={startsAt} onChange={(e) => setStartsAt(e.target.value)} required />
          </div>
          <div className="field" />
          <button className="btn" type="submit">
            Agendar
          </button>
        </form>
        <div className="panel">
          <div className="panel-title">Próximos horários</div>
          <table>
            <thead>
              <tr>
                <th>Quando</th>
                <th>Status</th>
                <th>Ação</th>
              </tr>
            </thead>
            <tbody>
              {items.map((a) => (
                <tr key={a.id}>
                  <td>{formatDateBR(a.starts_at)}</td>
                  <td>
                    <span className={`badge ${a.status}`}>{statusLabel(a.status)}</span>
                  </td>
                  <td>
                    <div className="actions-row">
                      {a.status === "scheduled" && (
                        <button type="button" className="btn secondary sm" onClick={() => api.transitionAppointment(a.id, "confirmed").then(load)}>
                          Confirmar
                        </button>
                      )}
                      {a.status === "confirmed" && (
                        <button type="button" className="btn secondary sm" onClick={() => api.transitionAppointment(a.id, "in_progress").then(load)}>
                          Iniciar
                        </button>
                      )}
                      {a.status === "in_progress" && (
                        <button type="button" className="btn sm" onClick={() => api.transitionAppointment(a.id, "done").then(load)}>
                          Concluir
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function WorkOrdersPage() {
  const [items, setItems] = useState<any[]>([]);
  const [customers, setCustomers] = useState<any[]>([]);
  const [customerId, setCustomerId] = useState("");
  const [title, setTitle] = useState("");
  const [total, setTotal] = useState("");
  const [err, setErr] = useState("");

  async function load() {
    const [w, c] = await Promise.all([api.workOrders(), api.customers()]);
    setItems(w);
    setCustomers(c);
    if (c[0]) setCustomerId(c[0].id);
  }

  useEffect(() => {
    load().catch((e) => setErr(String(e.message)));
  }, []);

  const cols = [
    { id: "draft", label: "Rascunho" },
    { id: "open", label: "Aberta" },
    { id: "in_progress", label: "Em andamento" },
    { id: "waiting_parts", label: "Peça" },
    { id: "done", label: "Concluída" },
  ];

  async function create(e: FormEvent) {
    e.preventDefault();
    try {
      await api.createWorkOrder({
        customer_id: customerId,
        title,
        description: "",
        total_cents: Math.round(parseFloat(total.replace(",", ".")) * 100),
      });
      setTitle("");
      await load();
    } catch (ex) {
      setErr(ex instanceof Error ? ex.message : "Erro");
    }
  }

  return (
    <div className="page">
      <PageHead
        eyebrow="Chão da oficina"
        title="Ordens de serviço"
        subtitle="Quadro por status, do rascunho à entrega."
      />
      <div className="page-body">
        {err && <div className="error">{err}</div>}
        <form onSubmit={create} className="toolbar cols-3">
          <div className="field">
            <label>Cliente</label>
            <select value={customerId} onChange={(e) => setCustomerId(e.target.value)}>
              {customers.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label>Título</label>
            <input value={title} onChange={(e) => setTitle(e.target.value)} required placeholder="Troca de óleo" />
          </div>
          <div className="field">
            <label>Total (R$)</label>
            <input value={total} onChange={(e) => setTotal(e.target.value)} />
          </div>
          <button className="btn" type="submit">
            Nova OS
          </button>
        </form>
        <div className="board">
          {cols.map((col) => {
            const colItems = items.filter((w) => w.status === col.id);
            return (
              <div key={col.id} className="kanban-col">
                <h3>
                  {col.label}
                  <span className="count">{colItems.length}</span>
                </h3>
                <div className="kanban-col-body">
                  {colItems.map((w) => (
                    <div key={w.id} className="kanban-item">
                      <strong>{w.number}</strong>
                      <div>{w.title}</div>
                      <div className="price">{formatBRL(w.total_cents)}</div>
                      <div className="actions-row">
                        {col.id === "draft" && (
                          <button type="button" className="btn secondary sm" onClick={() => api.transitionWorkOrder(w.id, "open").then(load)}>
                            Abrir
                          </button>
                        )}
                        {col.id === "open" && (
                          <button type="button" className="btn secondary sm" onClick={() => api.transitionWorkOrder(w.id, "in_progress").then(load)}>
                            Executar
                          </button>
                        )}
                        {col.id === "in_progress" && (
                          <button type="button" className="btn sm" onClick={() => api.transitionWorkOrder(w.id, "done").then(load)}>
                            Finalizar
                          </button>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function CustomersPage() {
  const [items, setItems] = useState<any[]>([]);
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [document, setDocument] = useState("");

  async function load() {
    setItems(await api.customers());
  }
  useEffect(() => {
    load();
  }, []);

  async function create(e: FormEvent) {
    e.preventDefault();
    await api.createCustomer({ name, phone, document, notes: "" });
    setName("");
    setPhone("");
    setDocument("");
    await load();
  }

  return (
    <div className="page">
      <PageHead eyebrow="Cadastro" title="Clientes" subtitle="Base do tenant: nome, telefone e documento BR." />
      <div className="page-body">
        <form onSubmit={create} className="toolbar cols-3">
          <div className="field">
            <label>Nome</label>
            <input value={name} onChange={(e) => setName(e.target.value)} required />
          </div>
          <div className="field">
            <label>Telefone</label>
            <input value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="(49) 99999-0000" />
          </div>
          <div className="field">
            <label>CPF/CNPJ</label>
            <input value={document} onChange={(e) => setDocument(e.target.value)} />
          </div>
          <button className="btn" type="submit">
            Salvar
          </button>
        </form>
        <div className="panel">
          <div className="panel-title">Lista · {items.length}</div>
          <table>
            <thead>
            <tr>
              <th>Nome</th>
              <th>Telefone</th>
              <th>Documento</th>
              <th></th>
            </tr>
            </thead>
            <tbody>
            {items.map((c) => (
              <tr key={c.id}>
                <td>{c.name}</td>
                <td>{c.phone || "-"}</td>
                <td>{c.document || "-"}</td>
                <td>
                  <button
                    type="button"
                    className="btn secondary sm"
                    onClick={() => api.deleteCustomer(c.id).then(load)}
                  >
                    Remover
                  </button>
                </td>
              </tr>
            ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function ServicesPage() {
  const [items, setItems] = useState<any[]>([]);
  const [name, setName] = useState("");
  const [price, setPrice] = useState("150");
  const [duration, setDuration] = useState("60");

  async function load() {
    setItems(await api.services());
  }
  useEffect(() => {
    load();
  }, []);

  async function create(e: FormEvent) {
    e.preventDefault();
    await api.createService({
      name,
      duration_min: Number(duration),
      price_cents: Math.round(parseFloat(price.replace(",", ".")) * 100),
      active: true,
    });
    setName("");
    await load();
  }

  return (
    <div className="page">
      <PageHead eyebrow="Catálogo" title="Serviços" subtitle="Preço e duração usados na agenda da oficina." />
      <div className="page-body">
        <form onSubmit={create} className="toolbar cols-3">
          <div className="field">
            <label>Nome</label>
            <input value={name} onChange={(e) => setName(e.target.value)} required />
          </div>
          <div className="field">
            <label>Duração (min)</label>
            <input value={duration} onChange={(e) => setDuration(e.target.value)} />
          </div>
          <div className="field">
            <label>Preço (R$)</label>
            <input value={price} onChange={(e) => setPrice(e.target.value)} />
          </div>
          <button className="btn" type="submit">
            Adicionar
          </button>
        </form>
        <div className="panel">
          <div className="panel-title">Catálogo · {items.length}</div>
          <table>
            <thead>
            <tr>
              <th>Serviço</th>
              <th>Duração</th>
              <th>Preço</th>
              <th></th>
            </tr>
            </thead>
            <tbody>
              {items.map((s) => (
                <tr key={s.id}>
                  <td>{s.name}</td>
                  <td>{s.duration_min} min</td>
                  <td>{formatBRL(s.price_cents)}</td>
                  <td>
                    <button
                      type="button"
                      className="btn secondary sm"
                      onClick={() => api.deleteService(s.id).then(load)}
                    >
                      Remover
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function BillingPage() {
  const [sub, setSub] = useState<any>(null);
  const [checkout, setCheckout] = useState<any>(null);
  const [payments, setPayments] = useState<any[]>([]);
  const [events, setEvents] = useState<any[]>([]);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  async function load() {
    setSub(await api.subscription());
    setPayments(await api.payments());
    setEvents(await api.webhookEvents());
  }
  useEffect(() => {
    load().catch((e) => setErr(String(e.message)));
  }, []);

  async function payPro() {
    setErr("");
    const out = await api.checkout("pro");
    setCheckout(out);
    setMsg("Pix gerado. Simule o webhook abaixo.");
    await load();
  }

  async function simulate() {
    if (!checkout?.payment_id) return;
    setErr("");
    try {
      const out = await api.simulateWebhook(checkout.payment_id);
      if (out?.status === "processado") {
        setMsg("Webhook processado. Assinatura ativa.");
      } else if (out?.duplicate) {
        setMsg(`Duplicata (status ${out.status}).`);
      } else {
        setMsg(`Evento aceito com status ${out?.status ?? "?"}. Veja a tabela abaixo.`);
      }
      await load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Falha no webhook");
      await load();
    }
  }

  return (
    <div className="page">
      <PageHead
        eyebrow="Plano da plataforma"
        title="Assinatura"
        subtitle="Cobrança do SaaS (Pix demo) com webhook, ciclo de vida e falha visível."
      />
      <div className="page-body">
        {err && <div className="error">{err}</div>}
        {sub && (
          <div className="stat-row">
            <div className="stat">
              <div className="label">Plano</div>
              <div className="value" style={{ fontSize: "1.5rem" }}>
                {sub.plan_code}
              </div>
            </div>
            <div className="stat">
              <div className="label">Status</div>
              <div className="value" style={{ fontSize: "1.1rem" }}>
                <span className={`badge ${sub.status}`}>{statusLabel(sub.status)}</span>
              </div>
            </div>
            <div className="stat">
              <div className="label">Válido até</div>
              <div className="value" style={{ fontSize: "1.25rem" }}>
                {new Date(sub.current_period_end).toLocaleDateString("pt-BR")}
              </div>
            </div>
            <div className="stat">
              <div className="label">Ação</div>
              <div className="value" style={{ fontSize: "0.9rem" }}>
                <button type="button" className="btn warn sm" onClick={payPro}>
                  Pro R$ 99
                </button>
              </div>
            </div>
          </div>
        )}
        {checkout && checkout.amount_cents > 0 && (
          <div className="panel panel-pad">
            <div className="field">
              <label>Pix copia-e-cola</label>
              <textarea readOnly rows={3} value={checkout.pix_copy_paste} />
            </div>
            <button type="button" className="btn" onClick={simulate} style={{ marginTop: "0.75rem" }}>
              Simular webhook aprovado
            </button>
          </div>
        )}
        {msg && <p className="success-msg">{msg}</p>}

        <div className="panel">
          <div className="panel-title">Pagamentos · {payments.length}</div>
          <table>
            <thead>
              <tr>
                <th>Plano</th>
                <th>Valor</th>
                <th>Status</th>
                <th>Quando</th>
              </tr>
            </thead>
            <tbody>
              {payments.map((p) => (
                <tr key={p.id}>
                  <td>{p.plan_code}</td>
                  <td>{formatBRL(p.amount_cents)}</td>
                  <td>
                    <span className={`badge ${p.status}`}>{p.status}</span>
                  </td>
                  <td>{formatDateBR(p.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="panel">
          <div className="panel-title">Webhook events · {events.length}</div>
          <table>
            <thead>
              <tr>
                <th>Status</th>
                <th>Tentativas</th>
                <th>Erro</th>
                <th>Quando</th>
              </tr>
            </thead>
            <tbody>
              {events.map((e) => (
                <tr key={e.id}>
                  <td>
                    <span className={`badge ${e.status === "falhou" ? "past_due" : e.status}`}>{e.status}</span>
                  </td>
                  <td>{e.attempts}</td>
                  <td>
                    <code style={{ fontSize: "0.75rem" }}>{e.last_error || "-"}</code>
                  </td>
                  <td>{formatDateBR(e.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function TeamPage() {
  const [items, setItems] = useState<any[]>([]);
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("senha123");
  const [role, setRole] = useState("STAFF");
  const [err, setErr] = useState("");

  async function load() {
    setItems(await api.memberships());
  }
  useEffect(() => {
    load().catch((e) => setErr(String(e.message)));
  }, []);

  async function create(e: FormEvent) {
    e.preventDefault();
    setErr("");
    try {
      await api.createMembership({
        email,
        full_name: fullName,
        password,
        role,
      });
      setEmail("");
      setFullName("");
      await load();
    } catch (ex) {
      setErr(ex instanceof Error ? ex.message : "Erro");
    }
  }

  return (
    <div className="page">
      <PageHead
        eyebrow="Gestão"
        title="Equipe"
        subtitle="Memberships do tenant, com limite conforme o plano."
      />
      <div className="page-body">
        {err && <div className="error">{err}</div>}
        <form onSubmit={create} className="toolbar">
          <div className="field">
            <label>Nome</label>
            <input value={fullName} onChange={(e) => setFullName(e.target.value)} required />
          </div>
          <div className="field">
            <label>E-mail</label>
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
          </div>
          <div className="field">
            <label>Senha inicial</label>
            <input value={password} onChange={(e) => setPassword(e.target.value)} required />
          </div>
          <div className="field">
            <label>Papel</label>
            <select value={role} onChange={(e) => setRole(e.target.value)}>
              <option value="STAFF">STAFF</option>
              <option value="TENANT_ADMIN">TENANT_ADMIN</option>
            </select>
          </div>
          <button className="btn" type="submit">
            Convidar
          </button>
        </form>
        <div className="panel">
          <div className="panel-title">Membros · {items.length}</div>
          <table>
            <thead>
              <tr>
                <th>Nome</th>
                <th>E-mail</th>
                <th>Papel</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {items.map((m) => (
                <tr key={m.id}>
                  <td>{m.full_name}</td>
                  <td>{m.email}</td>
                  <td>
                    <span className="badge open">{m.role}</span>
                  </td>
                  <td>
                    <button
                      type="button"
                      className="btn secondary sm"
                      onClick={() =>
                        api
                          .deleteMembership(m.id)
                          .then(load)
                          .catch((e) => setErr(String(e.message)))
                      }
                    >
                      Remover
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function PlatformPage() {
  const [tenants, setTenants] = useState<any[]>([]);
  const [stats, setStats] = useState<any>(null);
  const [events, setEvents] = useState<any[]>([]);
  useEffect(() => {
    api.platformTenants().then(setTenants);
    api.platformWebhookStats().then(setStats).catch(() => undefined);
    api.platformWebhookEvents("falhou").then(setEvents).catch(() => undefined);
  }, []);
  return (
    <div className="page">
      <PageHead
        eyebrow="Super-admin"
        title="Tenants"
        subtitle="Oficinas + saúde dos webhooks de billing."
      />
      <div className="page-body">
        {stats && (
          <div className="stat-row">
            <div className="stat">
              <div className="label">Falhas webhook</div>
              <div className="value" style={{ fontSize: "1.5rem" }}>
                {stats.failed}
              </div>
            </div>
            {Object.entries(stats.by_status || {}).map(([k, v]) => (
              <div className="stat" key={k}>
                <div className="label">{k}</div>
                <div className="value" style={{ fontSize: "1.1rem" }}>
                  {String(v)}
                </div>
              </div>
            ))}
          </div>
        )}
        <div className="panel">
          <div className="panel-title">Lista · {tenants.length}</div>
          <table>
            <thead>
              <tr>
                <th>Slug</th>
                <th>Nome</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {tenants.map((t) => (
                <tr key={t.id}>
                  <td>
                    <code>{t.slug}</code>
                  </td>
                  <td>{t.name}</td>
                  <td>
                    <span className={`badge ${t.status === "active" ? "active" : ""}`}>{t.status}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {events.length > 0 && (
          <div className="panel">
            <div className="panel-title">Webhooks falhos · {events.length}</div>
            <table>
              <thead>
                <tr>
                  <th>event_key</th>
                  <th>Tentativas</th>
                  <th>Erro</th>
                </tr>
              </thead>
              <tbody>
                {events.map((e) => (
                  <tr key={e.id}>
                    <td>
                      <code>{e.event_key}</code>
                    </td>
                    <td>{e.attempts}</td>
                    <td>
                      <code style={{ fontSize: "0.75rem" }}>{e.last_error || "-"}</code>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

export default function App() {
  const { me, setMe, loading } = useMe();
  const navigate = useNavigate();

  if (loading) return <div className="loading-screen">OficinaFlow…</div>;

  if (!me) {
    return (
      <Login
        onLogin={(m) => {
          setMe(m);
          navigate(m.tenant ? "/agenda" : "/platform");
        }}
      />
    );
  }

  return (
    <Routes>
      <Route
        element={
          <Shell
            me={me}
            onLogout={async () => {
              await api.logout();
              setMe(null);
              navigate("/");
            }}
          />
        }
      >
        <Route path="/agenda" element={<Agenda />} />
        <Route path="/os" element={<WorkOrdersPage />} />
        <Route path="/clientes" element={<CustomersPage />} />
        <Route path="/servicos" element={<ServicesPage />} />
        <Route path="/equipe" element={<TeamPage />} />
        <Route path="/assinatura" element={<BillingPage />} />
        <Route path="/platform" element={<PlatformPage />} />
        <Route path="*" element={<Navigate to={me.tenant ? "/agenda" : "/platform"} replace />} />
      </Route>
    </Routes>
  );
}
