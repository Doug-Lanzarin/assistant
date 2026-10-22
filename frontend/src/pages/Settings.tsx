import { useEffect, useState, type FormEvent } from "react";
import { useToast } from "../components/Toasts";
import { Card, Empty, fmtDate, Pill, RISK_LABEL, Tabs } from "../components/ui";
import { useApi } from "../hooks/useApi";
import { api, auth } from "../services/api";
import type { Settings as SettingsT } from "../types/api";

type Tab = "ai" | "voice" | "memory" | "integrations" | "permissions" | "system";

const ENUMS: Record<string, string[]> = {
  "ai.mode": ["remote_first", "local_first", "remote_only", "local_only", "rules_only"],
  "ai.remote_provider": ["anthropic", "openai_compat"],
  "ai.remote_effort": ["low", "medium", "high", "xhigh", "max"],
  "ai.embedding_provider": ["hash", "ollama"],
  "voice.tts_engine": ["browser", "sapi", "piper"],
  "voice.stt_model": ["tiny", "base", "small"],
  "whatsapp.mode": ["disabled", "notifications", "web", "business"],
};
const LABELS: Record<string, string> = {
  "ai.mode": "Modo da IA", "ai.remote_model": "Modelo remoto", "ai.remote_effort": "Esforço (custo/qualidade)",
  "ai.local_url": "URL do Ollama", "ai.local_model": "Modelo local (Ollama)", "ai.embedding_provider": "Embeddings",
  "ai.embedding_model": "Modelo de embeddings (Ollama)", "ai.daily_token_limit": "Limite diário de tokens (nuvem)",
  "ai.monthly_budget_usd": "Orçamento mensal (US$)", "ai.send_memory_to_remote": "Enviar trechos da memória à IA na nuvem",
  "voice.wake_word_enabled": "Escutar palavra de ativação (agente)", "voice.speak_responses": "Falar respostas de comandos por voz",
  "memory.auto_consolidate": "Consolidar memórias automaticamente", "memory.save_conversations": "Guardar histórico de conversas",
  "privacy.clipboard_sensitive_to_ai": "Permitir que a IA veja conteúdo sensível do clipboard",
  "privacy.store_voice_audio": "Guardar áudios de voz (não recomendado)",
  "ai.remote_provider": "Provedor remoto", "ai.openai_base_url": "URL compatível com OpenAI", "ai.openai_model": "Modelo compatível com OpenAI",
  "ai.timeout_s": "Tempo limite (s)", "ai.max_tool_iterations": "Máx. etapas de ferramentas por pedido", "ai.history_messages": "Mensagens de contexto",
  "assistant.name": "Nome do assistente", "assistant.user_name": "Seu nome", "assistant.personality": "Personalidade", "assistant.verbosity": "Estilo de resposta",
  "voice.enabled": "Voz habilitada", "voice.wake_word": "Palavra de ativação", "voice.wake_model": "Modelo de ativação (openWakeWord)",
  "voice.wake_threshold": "Sensibilidade da ativação (0–1)", "voice.stt_model": "Modelo de transcrição", "voice.stt_language": "Idioma da transcrição",
  "voice.tts_engine": "Motor de fala", "voice.tts_voice": "Voz (nome)", "voice.rate": "Velocidade da fala", "voice.volume": "Volume",
  "memory.consolidate_interval_min": "Intervalo da consolidação (min)", "memory.rag_top_k": "Trechos recuperados por pergunta", "memory.min_score": "Relevância mínima",
  "home_assistant.url": "URL do Home Assistant", "home_assistant.verify_ssl": "Verificar certificado TLS", "home_assistant.timeout_s": "Tempo limite (s)",
  "tcl.climate_entity": "Entidade climate.* do ar TCL", "tcl.model": "Modelo do aparelho", "tcl.integration": "Integração usada no HA",
  "alexa.enabled": "Anúncios na Alexa", "alexa.notify_service": "Serviço notify.* da Alexa",
  "whatsapp.mode": "Modo", "whatsapp.phone_number_id": "Phone number ID (Cloud API)", "whatsapp.api_version": "Versão da Graph API", "whatsapp.read_aloud_new": "Ler novas mensagens em voz alta",
};

function SectionForm({ name, values, onSaved, hide = [] }: { name: string; values: Record<string, unknown>; onSaved: () => void; hide?: string[] }) {
  const toast = useToast();
  const [form, setForm] = useState(values);
  useEffect(() => setForm(values), [values]);
  async function save(e: FormEvent) {
    e.preventDefault();
    const changed = Object.fromEntries(Object.entries(form).filter(([k, v]) => JSON.stringify(v) !== JSON.stringify(values[k])));
    if (!Object.keys(changed).length) return;
    try {
      await api.patch(`/api/settings/${name}`, changed);
      toast("Configurações salvas.", "ok");
      onSaved();
    } catch (err) {
      toast((err as Error).message, "error");
    }
  }
  return (
    <form className="stack" onSubmit={save}>
      <div className="grid cols-2">
        {Object.entries(form).filter(([k, v]) => !hide.includes(k) && !Array.isArray(v) && (typeof v !== "object" || v === null)).map(([k, v]) => {
          const key = `${name}.${k}`;
          const label = LABELS[key] ?? k.replace(/_/g, " ");
          const set = (val: unknown) => setForm((f) => ({ ...f, [k]: val }));
          if (typeof v === "boolean") return <label key={k} className="inline"><input type="checkbox" checked={v} onChange={(e) => set(e.target.checked)} /> {label}</label>;
          if (ENUMS[key]) return <label key={k}>{label}<select value={String(v)} onChange={(e) => set(e.target.value)}>{ENUMS[key].map((o) => <option key={o}>{o}</option>)}</select></label>;
          if (typeof v === "number") return <label key={k}>{label}<input type="number" step="any" value={v} onChange={(e) => set(Number(e.target.value))} /></label>;
          return <label key={k}>{label}<input value={v === null ? "" : String(v)} onChange={(e) => set(e.target.value || (v === null ? null : ""))} /></label>;
        })}
      </div>
      <div><button className="btn primary">Salvar</button></div>
    </form>
  );
}

function SecretField({ name, label, configured, onChange }: { name: string; label: string; configured: boolean; onChange: () => void }) {
  const toast = useToast();
  const [value, setValue] = useState("");
  async function save(e: FormEvent) {
    e.preventDefault();
    try {
      await api.put(`/api/secrets/${name}`, { value });
      setValue("");
      toast(`${label}: salvo de forma cifrada.`, "ok");
      onChange();
    } catch (err) { toast((err as Error).message, "error"); }
  }
  return (
    <form className="row" onSubmit={save}>
      <label style={{ flex: 1 }}>{label} {configured ? <Pill kind="ok">configurado</Pill> : <Pill>não configurado</Pill>}
        <input type="password" autoComplete="off" value={value} onChange={(e) => setValue(e.target.value)} placeholder={configured ? "•••••••• (digite para substituir)" : "cole aqui"} />
      </label>
      <button className="btn" disabled={!value} style={{ alignSelf: "flex-end" }}>Salvar</button>
      {configured && <button type="button" className="btn ghost" style={{ alignSelf: "flex-end" }} onClick={async () => { await api.del(`/api/secrets/${name}`); onChange(); }}>Remover</button>}
    </form>
  );
}

export function Settings() {
  const [tab, setTab] = useState<Tab>("ai");
  const settings = useApi<SettingsT>("/api/settings");
  const secrets = useApi<{ backend: string; items: { name: string; description: string; configured: boolean }[] }>("/api/secrets");
  const s = settings.data;
  const sec = (n: string) => secrets.data?.items.find((x) => x.name === n)?.configured ?? false;
  const reloadAll = () => { void settings.reload(); void secrets.reload(); };

  return (
    <div>
      <div className="page-head"><h1>Configurações</h1>{secrets.data && <span className="muted small">segredos protegidos por: {secrets.data.backend}</span>}</div>
      <Tabs label="Seções de configuração" value={tab} onChange={setTab} tabs={[
        { id: "ai", label: "IA" }, { id: "voice", label: "Voz" }, { id: "memory", label: "Memória e privacidade" },
        { id: "integrations", label: "Integrações" }, { id: "permissions", label: "Permissões" }, { id: "system", label: "Sistema" },
      ]} />
      {!s && <p className="muted">Carregando…</p>}
      {s && tab === "ai" && (
        <div className="stack">
          <Card title="Provedor de IA"><SectionForm name="ai" values={s.ai} onSaved={reloadAll} /></Card>
          <Card title="Chaves de API">
            <SecretField name="anthropic_api_key" label="Anthropic (Claude)" configured={sec("anthropic_api_key")} onChange={reloadAll} />
            <SecretField name="openai_api_key" label="Compatível com OpenAI" configured={sec("openai_api_key")} onChange={reloadAll} />
          </Card>
          <AiStatus />
          <Card title="Assistente"><SectionForm name="assistant" values={s.assistant} onSaved={reloadAll} /></Card>
        </div>
      )}
      {s && tab === "voice" && <VoiceSettings values={s.voice} onSaved={reloadAll} />}
      {s && tab === "memory" && (
        <div className="stack">
          <Card title="Memória"><SectionForm name="memory" values={s.memory} onSaved={reloadAll} /></Card>
          <Card title="Privacidade"><SectionForm name="privacy" values={s.privacy} onSaved={reloadAll} /></Card>
          <ReindexCard />
        </div>
      )}
      {s && tab === "integrations" && (
        <div className="stack">
          <Card title="Home Assistant">
            <SectionForm name="home_assistant" values={s.home_assistant} onSaved={reloadAll} />
            <SecretField name="ha_token" label="Token de longa duração" configured={sec("ha_token")} onChange={reloadAll} />
          </Card>
          <Card title="Ar-condicionado TCL"><p className="muted small">Informe a entidade climate.* criada no Home Assistant pela integração TCL (ver docs/TCL.md).</p><SectionForm name="tcl" values={s.tcl} onSaved={reloadAll} /></Card>
          <Card title="Alexa"><p className="muted small">A Alexa controla seus dispositivos pelo Home Assistant (Nabu Casa ou skill própria). Para anúncios, informe um serviço notify.* (ex.: Alexa Media Player).</p><SectionForm name="alexa" values={s.alexa} onSaved={reloadAll} /></Card>
          <Card title="WhatsApp">
            <SectionForm name="whatsapp" values={s.whatsapp} onSaved={reloadAll} />
            <SecretField name="whatsapp_cloud_token" label="Token da Cloud API" configured={sec("whatsapp_cloud_token")} onChange={reloadAll} />
            <SecretField name="whatsapp_app_secret" label="App Secret (webhook)" configured={sec("whatsapp_app_secret")} onChange={reloadAll} />
            <SecretField name="whatsapp_verify_token" label="Verify token (webhook)" configured={sec("whatsapp_verify_token")} onChange={reloadAll} />
          </Card>
        </div>
      )}
      {s && tab === "permissions" && <Permissions policy={s.policy} onSaved={reloadAll} />}
      {tab === "system" && <SystemTab />}
    </div>
  );
}

function AiStatus() {
  const toast = useToast();
  const st = useApi<{ providers: { name: string; model: string; available: boolean; detail: string; remote: boolean }[]; usage: Record<string, number>; embedder: string }>("/api/ai/status");
  const usage = useApi<{ day: string; provider: string; model: string; input_tokens: number; output_tokens: number; cost_usd: number; calls: number; errors: number; avg_latency_ms: number }[]>("/api/ai/usage?days=14");
  const [busy, setBusy] = useState(false);
  async function test() {
    setBusy(true);
    try {
      const r = await api.post<{ provider: string; ok: boolean; reply?: string; error?: string }[]>("/api/ai/test");
      if (!r.length) toast("Nenhum provedor disponível para testar.", "error");
      r.forEach((x) => toast(`${x.provider}: ${x.ok ? `ok (“${x.reply}”)` : x.error}`, x.ok ? "ok" : "error"));
      void usage.reload();
    } finally { setBusy(false); }
  }
  return (
    <Card title="Estado e uso" actions={<button className="btn" disabled={busy} onClick={test}>{busy ? "Testando…" : "Testar conexão"}</button>}>
      <div className="row">{(st.data?.providers ?? []).map((p) => <Pill key={p.name} kind={p.available ? "ok" : "warn"} title={p.detail}>{p.name}: {p.model || "—"} ({p.detail})</Pill>)}<Pill>embeddings: {st.data?.embedder}</Pill></div>
      {usage.data?.length ? (
        <table style={{ marginTop: 10 }}>
          <thead><tr><th>Dia</th><th>Provedor</th><th>Chamadas</th><th>Tokens (entrada/saída)</th><th>Custo est.</th><th>Latência média</th></tr></thead>
          <tbody>{usage.data.map((u, i) => <tr key={i}><td>{u.day}</td><td>{u.provider} · {u.model}</td><td>{u.calls}{u.errors ? ` (${u.errors} erros)` : ""}</td><td>{u.input_tokens}/{u.output_tokens}</td><td>US$ {u.cost_usd}</td><td>{u.avg_latency_ms} ms</td></tr>)}</tbody>
        </table>
      ) : <Empty>Sem uso registrado nos últimos 14 dias.</Empty>}
    </Card>
  );
}

function VoiceSettings({ values, onSaved }: { values: Record<string, unknown>; onSaved: () => void }) {
  const toast = useToast();
  const st = useApi<{ stt_installed: boolean; piper_installed: boolean; piper_voices: string[]; agent_voice: boolean; devices: { inputs?: { index: number; name: string }[]; outputs?: { index: number; name: string }[]; error?: string } | null }>("/api/voice/status");
  const [voices, setVoices] = useState<string[]>([]);
  useEffect(() => {
    if (!("speechSynthesis" in window)) return;
    const load = () => setVoices(window.speechSynthesis.getVoices().filter((v) => v.lang.toLowerCase().startsWith("pt")).map((v) => v.name));
    load();
    window.speechSynthesis.onvoiceschanged = load;
  }, []);
  async function agent(action: string) {
    try {
      await api.post(`/api/voice/agent/${action}`);
      toast("Comando enviado ao agente.", "ok");
      onSaved();
    } catch (e) { toast((e as Error).message, "error"); }
  }
  const d = st.data;
  return (
    <div className="stack">
      <Card title="Estado da voz">
        <div className="row">
          <Pill kind={d?.stt_installed ? "ok" : "warn"}>Transcrição local (faster-whisper) {d?.stt_installed ? "instalada" : "não instalada"}</Pill>
          <Pill kind={d?.piper_installed ? "ok" : ""}>Piper {d?.piper_installed ? `(${d.piper_voices.length} vozes)` : "não instalado"}</Pill>
          <Pill kind={d?.agent_voice ? "ok" : "warn"}>Microfone do agente {d?.agent_voice ? "disponível" : "indisponível"}</Pill>
          <Pill kind={voices.length ? "ok" : ""}>Vozes pt-BR do navegador: {voices.length}</Pill>
        </div>
        {!d?.stt_installed && <p className="muted small">Instale com scripts\install.ps1 -Voice (ou pip install -r backend/requirements-voice.txt).</p>}
        <div className="row" style={{ marginTop: 10 }}>
          <button className="btn" disabled={!d?.agent_voice} onClick={() => agent("listen")}>Falar agora (microfone do PC)</button>
          <button className="btn" disabled={!d?.agent_voice} onClick={() => agent(values.wake_word_enabled ? "wake_off" : "wake_on")}>{values.wake_word_enabled ? "Desligar palavra de ativação" : "Ligar palavra de ativação"}</button>
          <button className="btn" disabled={!d?.agent_voice} onClick={() => agent("stop_speaking")}>Interromper fala</button>
        </div>
      </Card>
      <Card title="Preferências">
        <SectionForm name="voice" values={values} onSaved={onSaved} hide={["input_device", "output_device"]} />
        {!!voices.length && <p className="muted small">Vozes do navegador disponíveis (use o nome em tts_voice): {voices.join(", ")}</p>}
      </Card>
      {d?.devices && !d.devices.error && (
        <Card title="Dispositivos de áudio (agente)">
          <DeviceSelect label="Microfone" field="input_device" options={d.devices.inputs ?? []} value={values.input_device as number | null} onSaved={onSaved} />
          <DeviceSelect label="Saída de áudio" field="output_device" options={d.devices.outputs ?? []} value={values.output_device as number | null} onSaved={onSaved} />
        </Card>
      )}
    </div>
  );
}

function DeviceSelect({ label, field, options, value, onSaved }: { label: string; field: string; options: { index: number; name: string }[]; value: number | null; onSaved: () => void }) {
  return (
    <label>{label}
      <select value={value ?? ""} onChange={async (e) => { await api.patch("/api/settings/voice", { [field]: e.target.value === "" ? null : Number(e.target.value) }); onSaved(); }}>
        <option value="">padrão do sistema</option>
        {options.map((o) => <option key={o.index} value={o.index}>{o.name}</option>)}
      </select>
    </label>
  );
}

function ReindexCard() {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  return (
    <Card title="Índice de busca">
      <p className="muted small">Ao trocar o provedor de embeddings, reindexe para que a busca semântica use o novo modelo.</p>
      <button className="btn" disabled={busy} onClick={async () => {
        setBusy(true);
        try { const r = await api.post<{ reindexed: number; embedder: string }>("/api/brain/reindex"); toast(`${r.reindexed} trechos reindexados com ${r.embedder}.`, "ok"); }
        catch (e) { toast((e as Error).message, "error"); } finally { setBusy(false); }
      }}>{busy ? "Reindexando…" : "Reindexar tudo"}</button>
    </Card>
  );
}

interface ToolInfo { name: string; description: string; risk: number; permission: string; category: string; always_confirm: boolean; enabled: boolean }

function Permissions({ policy, onSaved }: { policy: Record<string, unknown>; onSaved: () => void }) {
  const toast = useToast();
  const tools = useApi<ToolInfo[]>("/api/tools");
  const disabled = new Set((policy.disabled_permissions as string[]) ?? []);
  const levels = new Set((policy.confirm_risk_levels as number[]) ?? []);
  async function update(values: Record<string, unknown>) {
    try {
      await api.patch("/api/settings/policy", values);
      onSaved();
      void tools.reload();
    } catch (e) { toast((e as Error).message, "error"); }
  }
  const perms = [...new Set((tools.data ?? []).map((t) => t.permission))].sort();
  return (
    <div className="stack">
      <Card title="Confirmação por nível de risco">
        <div className="row">
          {[1, 2, 3, 4].map((l) => (
            <label key={l} className="inline">
              <input type="checkbox" checked={l === 4 || levels.has(l)} disabled={l === 4}
                onChange={(e) => update({ confirm_risk_levels: e.target.checked ? [...levels, l] : [...levels].filter((x) => x !== l) })} />
              {l}. {RISK_LABEL[l]}{l === 4 ? " (sempre)" : ""}
            </label>
          ))}
        </div>
        <label className="inline" style={{ marginTop: 10 }}>
          <input type="checkbox" checked={!!policy.confirm_llm_reversible_when_tainted} onChange={(e) => update({ confirm_llm_reversible_when_tainted: e.target.checked })} />
          Exigir confirmação quando a IA quiser alterar algo após ler conteúdo externo (mensagens, documentos)
        </label>
        <div className="row" style={{ marginTop: 10 }}>
          <Pill kind={policy.kill_switch ? "bad" : "ok"}>Modo de emergência {policy.kill_switch ? "ATIVO" : "desligado"}</Pill>
          <button className="btn small" onClick={() => api.post(policy.kill_switch ? "/api/emergency/resume" : "/api/emergency/stop").then(onSaved)}>{policy.kill_switch ? "Desativar" : "Ativar"}</button>
        </div>
      </Card>
      <Card title="Permissões das ferramentas">
        <div className="row" style={{ marginBottom: 10 }}>
          {perms.map((p) => (
            <label key={p} className="inline small">
              <input type="checkbox" checked={!disabled.has(p)} onChange={(e) => update({ disabled_permissions: e.target.checked ? [...disabled].filter((x) => x !== p) : [...disabled, p] })} />
              <code>{p}</code>
            </label>
          ))}
        </div>
        <table>
          <thead><tr><th>Ferramenta</th><th>Descrição</th><th>Risco</th><th>Permissão</th></tr></thead>
          <tbody>
            {(tools.data ?? []).map((t) => (
              <tr key={t.name} style={{ opacity: t.enabled ? 1 : 0.5 }}>
                <td><code>{t.name}</code></td>
                <td className="small">{t.description}</td>
                <td><Pill kind={t.risk >= 3 ? "warn" : t.risk === 2 ? "info" : "ok"}>{RISK_LABEL[t.risk]}{t.always_confirm ? " · confirma" : ""}</Pill></td>
                <td className="small"><code>{t.permission}</code></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}

function SystemTab() {
  const toast = useToast();
  const backups = useApi<{ name: string; size: number; modified: string }[]>("/api/backup");
  const logs = useApi<string[]>("/api/system/logs?lines=150");
  const audit = useApi<{ id: number; ts: string; tool: string; status: string; origin: string; risk: number; result_summary: string }[]>("/api/audit?limit=60");
  const envr = useApi<Record<string, unknown>>("/api/system/environment");
  const [oldPw, setOldPw] = useState("");
  const [newPw, setNewPw] = useState("");

  async function backup() {
    try {
      const r = await api.post<{ name: string }>("/api/backup");
      toast(`Backup criado: ${r.name}`, "ok");
      void backups.reload();
    } catch (e) { toast((e as Error).message, "error"); }
  }
  async function download(name: string) {
    const res = await fetch(`/api/backup/${encodeURIComponent(name)}`, { headers: { Authorization: `Bearer ${auth.token}` } });
    const url = URL.createObjectURL(await res.blob());
    const a = document.createElement("a");
    a.href = url; a.download = name; a.click();
    URL.revokeObjectURL(url);
  }
  async function restore(files: FileList | null) {
    if (!files?.[0] || !confirm("Restaurar substitui os dados atuais (um backup de segurança é criado antes). Continuar?")) return;
    const form = new FormData();
    form.append("file", files[0]);
    try {
      await api.upload("/api/backup/restore", form);
      toast("Backup restaurado.", "ok");
    } catch (e) { toast((e as Error).message, "error"); }
  }
  async function changePw(e: FormEvent) {
    e.preventDefault();
    try {
      await api.post("/api/auth/password", { old_password: oldPw, new_password: newPw });
      toast("Senha alterada. Entre novamente.", "ok");
      auth.set(null);
      location.reload();
    } catch (err) { toast((err as Error).message, "error"); }
  }

  return (
    <div className="stack">
      <div className="grid cols-2">
        <Card title="Backup e restauração" actions={<button className="btn primary" onClick={backup}>Criar backup</button>}>
          <ul className="list small">
            {(backups.data ?? []).map((b) => (
              <li key={b.name} className="row between"><span>{b.name} · {(b.size / 1024).toFixed(0)} KB</span><button className="btn small" onClick={() => void download(b.name)}>Baixar</button></li>
            ))}
          </ul>
          {backups.data && !backups.data.length && <Empty>Nenhum backup ainda.</Empty>}
          <label style={{ marginTop: 10 }}>Restaurar a partir de arquivo .zip<input type="file" accept=".zip" onChange={(e) => void restore(e.target.files)} /></label>
        </Card>
        <Card title="Conta e dados">
          <form className="stack" onSubmit={changePw}>
            <label>Senha atual<input type="password" autoComplete="current-password" value={oldPw} onChange={(e) => setOldPw(e.target.value)} required /></label>
            <label>Nova senha (mín. 8)<input type="password" autoComplete="new-password" value={newPw} onChange={(e) => setNewPw(e.target.value)} required minLength={8} /></label>
            <button className="btn">Alterar senha</button>
          </form>
          <div className="row" style={{ marginTop: 12 }}>
            <button className="btn" onClick={async () => { const r = await api.post<Record<string, number>>("/api/system/reload-config"); toast(`Configuração recarregada: ${r.apps} apps, ${r.routines} rotinas, ${r.projects} projetos.`, "ok"); }}>Recarregar config/jarvis.toml</button>
            <button className="btn danger" onClick={async () => { if (confirm("Apagar TODO o histórico de conversas? As memórias são mantidas.")) { const r = await api.post<{ deleted: number }>("/api/data/wipe-conversations"); toast(`${r.deleted} conversas apagadas.`, "ok"); } }}>Apagar conversas</button>
          </div>
        </Card>
      </div>
      <Card title="Ambiente">
        {envr.data ? <pre className="small">{JSON.stringify(envr.data, null, 2)}</pre> : <Empty>Carregando…</Empty>}
      </Card>
      <Card title="Auditoria de ações" actions={<button className="btn small" onClick={() => audit.reload()}>Atualizar</button>}>
        <table>
          <thead><tr><th>Quando</th><th>Ferramenta</th><th>Origem</th><th>Risco</th><th>Status</th><th>Resumo</th></tr></thead>
          <tbody>{(audit.data ?? []).map((a) => <tr key={a.id}><td className="small">{fmtDate(a.ts)}</td><td><code>{a.tool}</code></td><td>{a.origin}</td><td>{a.risk}</td><td>{a.status}</td><td className="small">{a.result_summary?.slice(0, 120)}</td></tr>)}</tbody>
        </table>
      </Card>
      <Card title="Logs" actions={<button className="btn small" onClick={() => logs.reload()}>Atualizar</button>}>
        <pre className="small" style={{ maxHeight: 360, overflow: "auto" }}>{(logs.data ?? []).join("\n") || "Sem logs."}</pre>
      </Card>
    </div>
  );
}
