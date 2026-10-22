import { useApi, useEvents, useInterval } from "../hooks/useApi";
import { api } from "../services/api";
import type { Status } from "../types/api";
import { Card, Empty, ErrorBox, fmtDate, Pill } from "../components/ui";
import { useToast } from "../components/Toasts";

export function Dashboard({ go }: { go: (page: string) => void }) {
  const { data: st, error, reload } = useApi<Status>("/api/status");
  const toast = useToast();
  useInterval(() => void reload(), 15000);
  useEvents(() => void reload(), ["agent", "kill_switch", "reminder", "tool_finished", "whatsapp_message"]);

  async function emergency() {
    const out = await api.post<{ message: string }>(st?.kill_switch ? "/api/emergency/resume" : "/api/emergency/stop");
    toast(out.message, "info");
    void reload();
  }

  if (error) return <ErrorBox error={error} onRetry={reload} />;
  if (!st) return <p className="muted">Carregando…</p>;
  const sys = st.system;
  const remote = st.ai.providers.find((p) => p.remote);
  const local = st.ai.providers.find((p) => !p.remote);

  return (
    <div className="stack" style={{ gap: 16 }}>
      <div className="page-head">
        <h1>Painel</h1>
        <button className={`btn ${st.kill_switch ? "success" : "danger"}`} onClick={emergency}>
          {st.kill_switch ? "Retomar operações" : "Parada de emergência"}
        </button>
      </div>
      {st.kill_switch && (
        <div className="banner danger" role="alert">
          Modo de emergência ativo: ferramentas de ação estão desativadas.
        </div>
      )}
      {st.pending_actions > 0 && (
        <div className="banner warn">
          {st.pending_actions} ação(ões) aguardando sua confirmação.
          <button className="btn small" onClick={() => go("chat")}>
            Ver na conversa
          </button>
        </div>
      )}

      <div className="grid cols-4">
        <Card title="JARVIS">
          <div className="stack">
            <Pill kind="ok">Backend v{st.version}</Pill>
            <Pill kind={st.agent.connected ? "ok" : "warn"} title="Clipboard, apps, voz e notificações dependem do agente">
              Agente local {st.agent.connected ? "conectado" : "desconectado"}
            </Pill>
            <Pill kind={sys.internet ? "ok" : "warn"}>Internet {sys.internet ? "ok" : "offline"}</Pill>
          </div>
        </Card>
        <Card title="IA">
          <div className="stack">
            <span className="muted small">modo: {st.ai.mode}</span>
            {remote && <Pill kind={remote.available ? "ok" : "warn"} title={remote.detail}>Nuvem: {remote.available ? remote.model : "não configurada"}</Pill>}
            {local && <Pill kind={local.available ? "ok" : ""} title={local.detail}>Local: {local.available ? local.model : "indisponível"}</Pill>}
            <span className="muted small">hoje: {st.ai.usage.tokens_today ?? 0} tokens · mês: US$ {Number(st.ai.usage.cost_month_usd ?? 0).toFixed(2)}</span>
          </div>
        </Card>
        <Card title="Voz">
          <div className="stack">
            <Pill kind={st.voice.enabled ? "ok" : ""}>Voz {st.voice.enabled ? "ativa" : "desativada"}</Pill>
            <Pill kind={st.voice.wake_word_enabled ? "info" : ""}>Ativação "{st.voice.wake_word}" {st.voice.wake_word_enabled ? "escutando" : "desligada"}</Pill>
            <Pill kind={st.voice.agent_voice ? "ok" : "warn"}>Microfone do agente {st.voice.agent_voice ? "pronto" : "indisponível"}</Pill>
          </div>
        </Card>
        <Card title="Computador">
          <div className="stack small">
            <span>CPU {Number(sys.cpu_percent).toFixed(0)}% · RAM {Number(sys.ram_used_percent).toFixed(0)}%</span>
            <span>{String(sys.ram_available_gb)} GB livres de {String(sys.ram_total_gb)} GB</span>
            <span>Disco livre: {String(sys.disk_free_gb)} GB</span>
            <span className="muted">JARVIS usando {String(sys.jarvis_rss_mb)} MB</span>
          </div>
        </Card>
      </div>

      <div className="grid cols-3">
        <Card title="Casa" actions={<button className="btn small" onClick={() => go("home")}>Abrir</button>}>
          {st.home.configured ? <p>{st.home.devices} dispositivo(s) conhecidos.</p> : <Empty>Home Assistant não configurado.</Empty>}
        </Card>
        <Card title="WhatsApp" actions={<button className="btn small" onClick={() => go("whatsapp")}>Abrir</button>}>
          <p className="small">modo: {st.whatsapp.mode}</p>
          <p className="small muted">{st.whatsapp.detail}</p>
          {st.whatsapp.unread > 0 && <Pill kind="info">{st.whatsapp.unread} não lida(s)</Pill>}
        </Card>
        <Card title="Pendências" actions={<button className="btn small" onClick={() => go("brain")}>Abrir</button>}>
          <p>{st.tasks_pending} tarefa(s) pendente(s)</p>
          {st.reminders.length ? (
            <ul className="list small">
              {st.reminders.map((r) => (
                <li key={r.id}>
                  {r.text} — {fmtDate(r.due_at)}
                </li>
              ))}
            </ul>
          ) : (
            <Empty>Nenhum lembrete agendado.</Empty>
          )}
        </Card>
      </div>

      <Card title="Atividades recentes">
        {st.recent_activity.length ? (
          <table>
            <thead>
              <tr>
                <th>Quando</th>
                <th>Ferramenta</th>
                <th>Resultado</th>
                <th>Resumo</th>
              </tr>
            </thead>
            <tbody>
              {st.recent_activity.map((a, i) => (
                <tr key={i}>
                  <td className="small">{fmtDate(a.ts)}</td>
                  <td><code>{a.tool}</code></td>
                  <td>
                    <Pill kind={a.status === "ok" ? "ok" : a.status === "needs_confirmation" ? "warn" : "bad"}>{a.status}</Pill>
                  </td>
                  <td className="small">{a.result_summary?.slice(0, 140)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty>Nenhuma atividade ainda. Comece pela Conversa.</Empty>
        )}
      </Card>
    </div>
  );
}
