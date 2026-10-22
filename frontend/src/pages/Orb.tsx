import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { PendingActions } from "../components/PendingActions";
import { useEvents } from "../hooks/useApi";
import { useVoice, type VoiceSettings } from "../hooks/useVoice";
import { BAND_COUNT, silentFrame, unlockAudio, type AudioFrame } from "../orb/audio";
import type { OrbState } from "../orb/engine";
import { OrbCanvas } from "../orb/OrbCanvas";
import { api } from "../services/api";
import type { ChatReply, Pending } from "../types/api";

const LABELS: Record<OrbState, string> = {
  off: "Sessão de voz encerrada",
  idle: "Em repouso",
  listening: "Ouvindo…",
  thinking: "Processando…",
  speaking: "Falando…",
  error: "Algo deu errado",
};

const SOURCE_LABEL: Record<string, string> = {
  mic: "microfone (navegador)",
  tts: "voz Piper — amplitude real",
  words: "voz do navegador — sincronia por palavra",
  agent: "microfone/voz do PC (agente)",
};

interface AgentLevel {
  level: number;
  at: number;
  source: string;
}

export function Orb({ voiceSettings }: { voiceSettings: VoiceSettings | null }) {
  const voice = useVoice(voiceSettings);
  const [active, setActive] = useState(false);
  const [busy, setBusy] = useState(false); // backend processando (evento WebSocket)
  const [requesting, setRequesting] = useState(false); // pedido desta tela em andamento
  // Entre a resposta chegar e o áudio começar (download do TTS) o orb continua "processando".
  const [preparingSpeech, setPreparingSpeech] = useState(false);
  const [agentState, setAgentState] = useState<string | null>(null);
  const [errorFlash, setErrorFlash] = useState(false);
  const [heard, setHeard] = useState("");
  const [reply, setReply] = useState("");
  const [pending, setPending] = useState<Pending[]>([]);
  const [typing, setTyping] = useState(false);
  const [text, setText] = useState("");
  const [continuous, setContinuous] = useState(false);
  const [muted, setMuted] = useState(false);
  const [cid, setCid] = useState<number | null>(() => Number(sessionStorage.getItem("jarvis.orb.cid")) || null);
  const agentLevel = useRef<AgentLevel>({ level: 0, at: 0, source: "agent" });
  const agentBands = useRef(new Float32Array(BAND_COUNT));
  const activeRef = useRef(active);
  activeRef.current = active;

  useEffect(() => {
    if (cid) sessionStorage.setItem("jarvis.orb.cid", String(cid));
  }, [cid]);

  // Eventos do backend: estado do assistente e voz do agente (microfone do PC).
  useEvents((ev) => {
    if (ev.type === "assistant_state") setBusy(ev.data.state === "thinking");
    if (ev.type === "voice_state") setAgentState(String(ev.data.state ?? "idle"));
    if (ev.type === "voice_level") {
      agentLevel.current = { level: Number(ev.data.level ?? 0), at: performance.now(), source: String(ev.data.source ?? "mic") };
    }
    if (ev.type === "voice_transcript") setHeard(String(ev.data.text ?? ""));
    if (ev.type === "voice_reply") {
      setReply(String(ev.data.text ?? ""));
      if (ev.data.conversation_id) setCid(Number(ev.data.conversation_id));
    }
    if (ev.type === "confirmation_required" && cid && ev.data.conversation_id === cid) {
      api.get<Pending[]>(`/api/actions/pending?conversation_id=${cid}`).then(setPending).catch(() => {});
    }
  }, ["assistant_state", "voice_state", "voice_level", "voice_transcript", "voice_reply", "confirmation_required"]);

  const state: OrbState = useMemo(() => {
    if (!active) return "off";
    if (errorFlash || voice.state === "error") return "error";
    if (voice.state === "listening" || agentState === "listening") return "listening";
    if (voice.state === "speaking" || agentState === "speaking") return "speaking";
    if (busy || requesting || preparingSpeech || voice.state === "transcribing" || agentState === "transcribing") return "thinking";
    return "idle";
  }, [active, errorFlash, voice.state, agentState, busy, requesting, preparingSpeech]);

  useEffect(() => {
    if (voice.state === "speaking" || voice.state === "error") setPreparingSpeech(false);
  }, [voice.state]);

  useEffect(() => {
    if (!errorFlash) return;
    const t = setTimeout(() => setErrorFlash(false), 1800);
    return () => clearTimeout(t);
  }, [errorFlash]);

  const readAudio = useCallback((): AudioFrame => {
    const local = voice.readAudio();
    if (local.source !== "none") return local;
    const a = agentLevel.current;
    const age = performance.now() - a.at;
    if (age < 400) {
      // O agente envia o nível medido no PC; as faixas seguem esse nível.
      const lvl = a.level;
      const bands = agentBands.current;
      for (let i = 0; i < BAND_COUNT; i++) bands[i] = lvl * (0.55 + 0.45 * Math.cos((i / BAND_COUNT) * Math.PI));
      return { level: lvl, bands, source: "agent" };
    }
    return silentFrame();
  }, [voice]);

  const send = useCallback(
    async (msg: string, origin: "user" | "voice") => {
      const t = msg.trim();
      if (!t) return;
      setHeard(t);
      setReply("");
      setRequesting(true);
      try {
        const r = await api.post<ChatReply>("/api/chat", { text: t, conversation_id: cid, origin });
        setCid(r.conversation_id);
        setReply(r.text);
        setPending(r.pending ?? []);
        if (!muted && activeRef.current) {
          setPreparingSpeech(true);
          setRequesting(false);
          try {
            await voice.speak(r.text);
          } finally {
            setPreparingSpeech(false);
          }
        } else {
          setRequesting(false);
        }
        if (continuous && activeRef.current && !(r.pending ?? []).length) listenRef.current();
      } catch (e) {
        setRequesting(false);
        setReply(`⚠ ${(e as Error).message}`);
        setErrorFlash(true);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [cid, muted, continuous, voice],
  );

  const listen = useCallback(() => {
    void voice.startListening({
      onUtterance: (said) => {
        if (said) void send(said, "voice");
      },
    });
  }, [voice, send]);
  const listenRef = useRef(listen);
  listenRef.current = listen;

  async function toggleSession() {
    await unlockAudio();
    if (active) {
      voice.cancelListening();
      voice.stopSpeaking();
      setActive(false);
    } else {
      setActive(true);
    }
  }

  async function micButton() {
    await unlockAudio();
    if (!active) setActive(true);
    if (voice.state === "listening") {
      const said = await voice.stopListening(true);
      if (said) void send(said, "voice");
      voice.markIdle();
    } else if (voice.state === "speaking") {
      voice.stopSpeaking();
      listen();
    } else {
      listen();
    }
  }

  async function stopAll() {
    voice.cancelListening();
    voice.stopSpeaking();
    if (busy || requesting) await api.post(`/api/chat/cancel${cid ? `?conversation_id=${cid}` : ""}`).catch(() => {});
  }

  // Atalhos: Espaço = falar/parar, Esc = interromper tudo
  const micRef = useRef(micButton);
  micRef.current = micButton;
  const stopRef = useRef(stopAll);
  stopRef.current = stopAll;
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement | null)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "BUTTON") return;
      if (e.code === "Space") {
        e.preventDefault();
        void micRef.current();
      } else if (e.key === "Escape") {
        void stopRef.current();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  async function submitText(e: FormEvent) {
    e.preventDefault();
    await unlockAudio();
    if (!active) setActive(true);
    const t = text;
    setText("");
    await send(t, "user");
  }

  const frameSource = state === "listening" || state === "speaking"
    ? (voice.state === "listening" ? "mic" : voice.state === "speaking" ? (voice.ttsSource === "piper" ? "tts" : "words") : "agent")
    : null;

  return (
    <div className={`orb-stage state-${state}`}>
      <OrbCanvas state={state} readAudio={readAudio} label={`Orb do JARVIS: ${LABELS[state]}`} />

      <header className="orb-top">
        <span className="orb-brand">J.A.R.V.I.S.</span>
        <span className="orb-chip" aria-live="polite">
          <span className={`orb-dot ${state}`} aria-hidden="true" /> {LABELS[state]}
        </span>
      </header>

      <div className="orb-caption" aria-live="polite">
        {heard && <p className="orb-heard">“{heard}”</p>}
        {reply && <p className="orb-reply">{reply.length > 420 ? `${reply.slice(0, 420)}…` : reply}</p>}
        {!heard && !reply && active && <p className="orb-hint">Pressione <kbd>Espaço</kbd> ou toque no microfone e fale. <kbd>Esc</kbd> interrompe.</p>}
        {!active && <p className="orb-hint">Toque em <strong>Iniciar</strong> para ativar o JARVIS.</p>}
        {voice.error && <p className="orb-error" role="alert">{voice.error}</p>}
        {frameSource && <p className="orb-source">sincronia: {SOURCE_LABEL[frameSource]}</p>}
      </div>

      {pending.length > 0 && (
        <div className="orb-pending">
          <PendingActions items={pending} onDone={(out) => {
            setPending((p) => p.filter((x) => x.id !== out.pending_id));
            setReply(out.message);
            if (!muted) void voice.speak(out.message);
          }} />
        </div>
      )}

      <nav className="orb-controls" aria-label="Controles de voz">
        <button className="orb-btn" onClick={toggleSession} aria-pressed={active} title={active ? "Encerrar sessão de voz" : "Iniciar sessão de voz"}>
          <span aria-hidden="true">⏻</span><span className="orb-btn-label">{active ? "Encerrar" : "Iniciar"}</span>
        </button>
        <button className={`orb-btn orb-mic ${state === "listening" ? "on" : ""}`} onClick={micButton}
          aria-label={voice.state === "listening" ? "Parar e enviar" : "Falar com o JARVIS"} disabled={voice.state === "transcribing"}>
          <svg viewBox="0 0 24 24" width="28" height="28" aria-hidden="true"><path fill="currentColor" d="M12 15a3 3 0 0 0 3-3V6a3 3 0 1 0-6 0v6a3 3 0 0 0 3 3Zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.92V21h2v-2.08A7 7 0 0 0 19 12h-2Z" /></svg>
        </button>
        <button className="orb-btn" onClick={stopAll} title="Interromper (Esc)" disabled={state === "idle" || state === "off"}>
          <span aria-hidden="true">■</span><span className="orb-btn-label">Parar</span>
        </button>
      </nav>

      <div className="orb-options">
        <label className="orb-toggle"><input type="checkbox" checked={continuous} onChange={(e) => setContinuous(e.target.checked)} /> conversa contínua</label>
        <label className="orb-toggle"><input type="checkbox" checked={muted} onChange={(e) => setMuted(e.target.checked)} /> sem voz</label>
        <button className="orb-link" onClick={() => setTyping((v) => !v)}>{typing ? "fechar teclado" : "digitar"}</button>
      </div>

      {typing && (
        <form className="orb-type" onSubmit={submitText}>
          <label className="sr-only" htmlFor="orb-input">Mensagem para o JARVIS</label>
          <input id="orb-input" value={text} onChange={(e) => setText(e.target.value)} placeholder="Digite um pedido…" autoFocus />
          <button className="orb-btn small" disabled={!text.trim()}>Enviar</button>
        </form>
      )}
    </div>
  );
}
