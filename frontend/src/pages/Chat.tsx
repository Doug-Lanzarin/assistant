import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { PendingActions } from "../components/PendingActions";
import { useToast } from "../components/Toasts";
import { Empty, Modal, Pill } from "../components/ui";
import { useApi, useEvents } from "../hooks/useApi";
import { useVoice, type VoiceSettings } from "../hooks/useVoice";
import { api } from "../services/api";
import type { Action, ChatReply, Conversation, Message, Pending, Source } from "../types/api";

interface Bubble {
  id: string;
  role: "user" | "assistant";
  text: string;
  provider?: string;
  actions?: Action[];
  sources?: Source[];
}

function toBubbles(msgs: Message[]): Bubble[] {
  return msgs
    .filter((m) => m.role === "user" || m.role === "assistant")
    .map((m) => ({ id: String(m.id), role: m.role as "user" | "assistant", text: m.content, provider: m.meta?.provider, actions: m.meta?.actions, sources: m.meta?.sources }));
}

export function Chat({ voiceSettings }: { voiceSettings: VoiceSettings | null }) {
  const toast = useToast();
  const [cid, setCid] = useState<number | null>(() => Number(sessionStorage.getItem("jarvis.cid")) || null);
  const [bubbles, setBubbles] = useState<Bubble[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<Pending[]>([]);
  const [running, setRunning] = useState<string | null>(null);
  const [sources, setSources] = useState<Source[] | null>(null);
  const [autoSpeak, setAutoSpeak] = useState(false);
  const convs = useApi<Conversation[]>("/api/conversations");
  const voice = useVoice(voiceSettings);
  const end = useRef<HTMLDivElement>(null);
  const skipLoad = useRef(false);

  useEffect(() => {
    if (cid) sessionStorage.setItem("jarvis.cid", String(cid));
    else sessionStorage.removeItem("jarvis.cid");
    if (!cid) {
      setBubbles([]);
      setPending([]);
      return;
    }
    if (skipLoad.current) {
      // conversa recém-criada por esta tela: as mensagens já estão na tela
      skipLoad.current = false;
      return;
    }
    api.get<Message[]>(`/api/conversations/${cid}/messages`).then((m) => setBubbles(toBubbles(m))).catch(() => setCid(null));
    api.get<Pending[]>(`/api/actions/pending?conversation_id=${cid}`).then(setPending).catch(() => {});
  }, [cid]);

  useEffect(() => end.current?.scrollIntoView?.({ behavior: "smooth" }), [bubbles, busy]);

  useEvents((ev) => {
    if (ev.type === "tool_started") setRunning(String(ev.data.tool));
    if (ev.type === "tool_finished") setRunning(null);
    if (ev.type === "confirmation_required" && ev.data.conversation_id === cid)
      api.get<Pending[]>(`/api/actions/pending?conversation_id=${cid}`).then(setPending).catch(() => {});
    if (ev.type === "voice_reply" && ev.data.conversation_id === cid) {
      api.get<Message[]>(`/api/conversations/${cid}/messages`).then((m) => setBubbles(toBubbles(m)));
    }
  }, ["tool_started", "tool_finished", "confirmation_required", "voice_reply"]);

  async function send(input?: string, origin: "user" | "voice" = "user") {
    const msg = (input ?? text).trim();
    if (!msg || busy) return;
    setText("");
    setBubbles((b) => [...b, { id: `u${Date.now()}`, role: "user", text: msg }]);
    setBusy(true);
    try {
      const r = await api.post<ChatReply>("/api/chat", { text: msg, conversation_id: cid, origin });
      if (r.conversation_id !== cid) {
        skipLoad.current = true;
        setCid(r.conversation_id);
      }
      void convs.reload();
      setBubbles((b) => [...b, { id: `a${r.message_id ?? Date.now()}`, role: "assistant", text: r.text, provider: r.provider, actions: r.actions, sources: r.sources }]);
      setPending(r.pending ?? []);
      if (autoSpeak || origin === "voice") void voice.speak(r.text);
    } catch (e) {
      setBubbles((b) => [...b, { id: `e${Date.now()}`, role: "assistant", text: `⚠ ${(e as Error).message}` }]);
    } finally {
      setBusy(false);
    }
  }

  async function cancel() {
    await api.post(`/api/chat/cancel${cid ? `?conversation_id=${cid}` : ""}`);
    toast("Cancelamento solicitado.");
  }

  async function toggleMic() {
    if (voice.state === "listening") {
      const said = await voice.stopListening();
      if (said) void send(said, "voice");
    } else {
      await voice.startListening();
    }
  }

  function onKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void send();
    }
  }

  return (
    <div className="split">
      <aside className="card tight stack" aria-label="Conversas">
        <div className="row between">
          <h2>Conversas</h2>
          <button className="btn small primary" onClick={() => setCid(null)}>
            Nova
          </button>
        </div>
        <ul className="list">
          {(convs.data ?? []).map((c) => (
            <li key={c.id} className={c.id === cid ? "active" : ""}>
              <button className="item" onClick={() => setCid(c.id)} aria-current={c.id === cid}>
                <div className="small">{c.title}</div>
                <div className="muted small">{c.messages} mensagens</div>
              </button>
            </li>
          ))}
        </ul>
        {!convs.data?.length && <Empty>Nenhuma conversa ainda.</Empty>}
      </aside>

      <section className="card chat" aria-label="Conversa">
        <div className="messages" aria-live="polite">
          {!bubbles.length && (
            <div className="muted">
              <p>Diga ou digite um pedido. Exemplos:</p>
              <ul className="small">
                <li>salve o que copiei como consulta SQL de coletas</li>
                <li>quais tarefas estão pendentes?</li>
                <li>ajuste o ar para 23 graus</li>
                <li>encontre a ideia de aplicativo que registrei</li>
              </ul>
            </div>
          )}
          {bubbles.map((b) => (
            <div key={b.id} className={`msg ${b.role}`}>
              {b.text}
              {b.role === "assistant" && (b.provider || b.actions?.length || b.sources?.length) ? (
                <div className="msg-meta">
                  {b.provider && <span>via {b.provider}</span>}
                  {b.actions?.map((a, i) => (
                    <Pill key={i} kind={a.status === "ok" ? "ok" : a.status === "needs_confirmation" ? "warn" : "bad"}>
                      {a.tool}: {a.status}
                    </Pill>
                  ))}
                  {!!b.sources?.length && (
                    <button className="btn ghost small" onClick={() => setSources(b.sources ?? [])}>
                      Fontes ({b.sources.length})
                    </button>
                  )}
                  <button className="btn ghost small" onClick={() => void voice.speak(b.text)} aria-label="Ouvir resposta">
                    🔊
                  </button>
                </div>
              ) : null}
            </div>
          ))}
          {busy && (
            <div className="msg assistant muted" role="status">
              {running ? `Executando ${running}…` : "Pensando…"}
            </div>
          )}
          <div ref={end} />
        </div>
        <PendingActions
          items={pending}
          onDone={(out) => {
            setPending((p) => p.filter((x) => x.id !== out.pending_id));
            setBubbles((b) => [...b, { id: `c${Date.now()}`, role: "assistant", text: out.message, actions: [out] }]);
            if (cid) api.get<Pending[]>(`/api/actions/pending?conversation_id=${cid}`).then(setPending);
          }}
        />
        {voice.error && (
          <div className="banner warn" role="alert">
            {voice.error}
            <button className="btn small" onClick={() => voice.setError(null)}>
              OK
            </button>
          </div>
        )}
        <div className="composer">
          <button
            className={`btn voice-btn ${voice.state === "listening" ? "listening" : ""}`}
            onClick={toggleMic}
            aria-label={voice.state === "listening" ? "Parar e enviar fala" : "Falar"}
            aria-pressed={voice.state === "listening"}
            disabled={voice.state === "transcribing"}
          >
            {voice.state === "transcribing" ? "…" : "🎤"}
          </button>
          <label className="sr-only" htmlFor="chat-input">
            Mensagem
          </label>
          <textarea id="chat-input" value={text} onChange={(e) => setText(e.target.value)} onKeyDown={onKey} placeholder="Fale com o JARVIS… (Enter envia, Shift+Enter quebra linha)" rows={1} />
          {busy ? (
            <button className="btn danger" onClick={cancel}>
              Cancelar
            </button>
          ) : (
            <button className="btn primary" onClick={() => void send()} disabled={!text.trim()}>
              Enviar
            </button>
          )}
        </div>
        <div className="row small muted" style={{ marginTop: 6 }}>
          <label className="inline">
            <input type="checkbox" checked={autoSpeak} onChange={(e) => setAutoSpeak(e.target.checked)} /> responder em voz alta
          </label>
          {voice.state === "speaking" && (
            <button className="btn small" onClick={voice.stopSpeaking}>
              Interromper fala
            </button>
          )}
          <span aria-live="polite">{voice.state === "listening" ? "🎙 ouvindo — clique novamente para enviar" : voice.state === "transcribing" ? "transcrevendo localmente…" : ""}</span>
        </div>
      </section>

      <Modal open={sources !== null} onClose={() => setSources(null)} title="Fontes usadas">
        <ul className="list">
          {(sources ?? []).map((s, i) => (
            <li key={i}>
              <strong>{s.citation ?? s.title}</strong>
              {s.stale && <span className="pill warn" style={{ marginLeft: 8 }}>possivelmente desatualizada</span>}
              {s.snippet && <p className="small muted">{s.snippet}</p>}
            </li>
          ))}
        </ul>
      </Modal>
    </div>
  );
}
