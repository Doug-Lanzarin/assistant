import { useState, type FormEvent } from "react";
import { PendingActions } from "../components/PendingActions";
import { useToast } from "../components/Toasts";
import { Card, Empty, fmtDate, Pill } from "../components/ui";
import { useApi, useEvents } from "../hooks/useApi";
import { api } from "../services/api";
import type { Action, Pending } from "../types/api";

interface WaStatus { mode: string; can_read: boolean; can_send: boolean; detail: string; unread: number; stored_messages: number }
interface WaMessage { id: number; source: string; sender: string; chat: string; text: string; received_at: string; is_read: number }
interface Contact { id: number; name: string; phone: string | null; aliases: string }
interface Outbox { id: number; channel: string; to_name: string; text: string; status: string; error: string | null; created_at: string; sent_at: string | null }

export function WhatsApp({ go }: { go: (p: string) => void }) {
  const toast = useToast();
  const status = useApi<WaStatus>("/api/whatsapp/status");
  const msgs = useApi<WaMessage[]>("/api/whatsapp/messages?limit=100");
  const contacts = useApi<Contact[]>("/api/whatsapp/contacts");
  const outbox = useApi<Outbox[]>("/api/whatsapp/outbox");
  const [to, setTo] = useState("");
  const [text, setText] = useState("");
  const [pending, setPending] = useState<Pending[]>([]);
  const [cName, setCName] = useState("");
  const [cPhone, setCPhone] = useState("");
  useEvents(() => { void msgs.reload(); void status.reload(); }, ["whatsapp_message"]);

  async function prepare(e: FormEvent) {
    e.preventDefault();
    try {
      const out = await api.post<Action>("/api/whatsapp/send", { to, text });
      if (out.status === "needs_confirmation" && out.pending_id) {
        setPending([{ id: out.pending_id, conversation_id: null, tool: out.tool, summary: out.message, risk: out.risk, created_at: "", expires_at: new Date(Date.now() + 300000).toISOString() }]);
      } else {
        toast(out.message, "error");
      }
    } catch (err) { toast((err as Error).message, "error"); }
  }
  async function addContact(e: FormEvent) {
    e.preventDefault();
    try {
      await api.post("/api/whatsapp/contacts", { name: cName, phone: cPhone || null });
      setCName(""); setCPhone("");
      void contacts.reload();
    } catch (err) { toast((err as Error).message, "error"); }
  }

  const st = status.data;
  return (
    <div className="stack" style={{ gap: 16 }}>
      <div className="page-head">
        <h1>WhatsApp</h1>
        <div className="row">
          <button className="btn" onClick={async () => { await api.get("/api/whatsapp/messages?refresh=true&only_unread=true"); void msgs.reload(); }}>Atualizar</button>
          <button className="btn" onClick={() => go("settings")}>Configurar</button>
        </div>
      </div>
      {st && (
        <div className="row">
          <Pill kind={st.mode === "disabled" ? "" : "info"}>modo: {st.mode}</Pill>
          <Pill kind={st.can_read ? "ok" : "warn"}>leitura {st.can_read ? "disponível" : "indisponível"}</Pill>
          <Pill kind={st.can_send ? "ok" : "warn"}>envio {st.can_send ? "disponível" : "indisponível"}</Pill>
          <span className="muted small">{st.detail}</span>
        </div>
      )}
      <div className="banner info small">
        O JARVIS só vê mensagens que chegam por notificação, pelo WhatsApp Web autenticado por você, ou pela Cloud API do número empresarial. Não há acesso ao histórico completo da conta pessoal. Todo envio pede confirmação.
      </div>
      <div className="grid cols-2">
        <Card title={`Mensagens recebidas (${msgs.data?.length ?? 0})`} actions={<button className="btn small" onClick={async () => { await api.post("/api/whatsapp/messages/read-all"); void msgs.reload(); }}>Marcar como lidas</button>}>
          <ul className="list" style={{ maxHeight: 480, overflowY: "auto" }}>
            {(msgs.data ?? []).map((m) => (
              <li key={m.id} style={{ borderColor: m.is_read ? undefined : "var(--blue-dim)" }}>
                <div className="row between small"><strong>{m.sender}</strong><span className="muted">{fmtDate(m.received_at)} · {m.source}</span></div>
                <div className="small" style={{ whiteSpace: "pre-wrap" }}>{m.text}</div>
                <button className="btn ghost small" onClick={() => setTo(m.sender)}>Responder</button>
              </li>
            ))}
          </ul>
          {msgs.data && !msgs.data.length && <Empty>Nenhuma mensagem recebida ainda.</Empty>}
        </Card>
        <div className="stack">
          <Card title="Nova mensagem">
            <form className="stack" onSubmit={prepare}>
              <label>Para<input value={to} onChange={(e) => setTo(e.target.value)} required list="wa-contacts" /></label>
              <datalist id="wa-contacts">{(contacts.data ?? []).map((c) => <option key={c.id} value={c.name} />)}</datalist>
              <label>Mensagem<textarea rows={3} value={text} onChange={(e) => setText(e.target.value)} required /></label>
              <button className="btn primary" disabled={!st?.can_send}>Preparar envio</button>
            </form>
            <div style={{ marginTop: 10 }}>
              <PendingActions items={pending} onDone={() => { setPending([]); setText(""); void outbox.reload(); }} />
            </div>
          </Card>
          <Card title="Contatos">
            <form className="row" onSubmit={addContact}>
              <input aria-label="Nome do contato" placeholder="Nome" value={cName} onChange={(e) => setCName(e.target.value)} required style={{ flex: 1 }} />
              <input aria-label="Telefone internacional" placeholder="5511999998888 (Cloud API)" value={cPhone} onChange={(e) => setCPhone(e.target.value)} style={{ flex: 1 }} />
              <button className="btn">Adicionar</button>
            </form>
            <ul className="list small" style={{ marginTop: 8 }}>
              {(contacts.data ?? []).map((c) => (
                <li key={c.id} className="row between">
                  <span>{c.name} <span className="muted">{c.phone ?? ""}</span></span>
                  <button className="btn ghost small" aria-label={`Remover ${c.name}`} onClick={async () => { await api.del(`/api/whatsapp/contacts/${c.id}`); void contacts.reload(); }}>✕</button>
                </li>
              ))}
            </ul>
          </Card>
          <Card title="Envios">
            <ul className="list small">
              {(outbox.data ?? []).slice(0, 15).map((o) => (
                <li key={o.id}>
                  <div className="row between"><span>{o.to_name}: “{o.text}”</span><Pill kind={o.status === "sent" || o.status === "delivered" || o.status === "read" ? "ok" : o.status === "failed" ? "bad" : "warn"}>{o.status}</Pill></div>
                  <div className="muted">{fmtDate(o.created_at)} · {o.channel}{o.error ? ` · ${o.error}` : ""}</div>
                </li>
              ))}
            </ul>
            {outbox.data && !outbox.data.length && <Empty>Nenhum envio.</Empty>}
          </Card>
        </div>
      </div>
    </div>
  );
}
