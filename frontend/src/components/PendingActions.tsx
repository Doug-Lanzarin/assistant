import { useState } from "react";
import { api } from "../services/api";
import type { Action, Pending } from "../types/api";
import { RISK_LABEL } from "./ui";
import { useToast } from "./Toasts";

export function PendingActions({ items, onDone }: { items: Pending[]; onDone: (result: Action) => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);
  if (!items.length) return null;

  async function decide(p: Pending, approve: boolean) {
    setBusy(p.id);
    try {
      const out = await api.post<Action>(`/api/actions/${p.id}/confirm`, { approve });
      toast(out.message, out.status === "ok" ? "ok" : out.status === "cancelled" ? "info" : "error");
      onDone(out);
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="stack" aria-label="Ações aguardando confirmação">
      {items.map((p) => (
        <div key={p.id} className="confirm-card" role="group" aria-label={`Confirmar ${p.tool}`}>
          <div className="row between">
            <strong>Confirmação necessária</strong>
            <span className="pill warn">risco: {RISK_LABEL[p.risk] ?? p.risk}</span>
          </div>
          <p style={{ margin: "6px 0 10px" }}>{p.summary}</p>
          <div className="row">
            <button className="btn success" disabled={busy === p.id} onClick={() => decide(p, true)}>
              Confirmar
            </button>
            <button className="btn danger" disabled={busy === p.id} onClick={() => decide(p, false)}>
              Cancelar
            </button>
            <span className="muted small">expira em {new Date(p.expires_at).toLocaleTimeString("pt-BR")}</span>
          </div>
        </div>
      ))}
    </div>
  );
}
