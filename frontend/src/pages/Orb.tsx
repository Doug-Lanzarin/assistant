import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { PendingActions } from "../components/PendingActions";
import { useEvents } from "../hooks/useApi";
import { useVoice, type VoiceEvent, type VoiceSettings } from "../hooks/useVoice";
import { BAND_COUNT, silentFrame, unlockAudio, type AudioFrame } from "../orb/audio";
import { OrbCanvas } from "../orb/OrbCanvas";
import { ERROR_HOLD_MS, type AssistantState } from "../orb/stateMachine";
import { useAssistantMachine } from "../orb/useAssistantMachine";
import { api } from "../services/api";
import type { ChatReply, Pending } from "../types/api";

const LABELS: Record<AssistantState, string> = {
  OFF: "Sessão de voz encerrada",
  IDLE: "Em repouso",
  LISTENING: "Ouvindo…",
  THINKING: "Processando…",
  SPEAKING: "Falando…",
  ERROR: "Falha",
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
  const { machine, dispatch, current } = useAssistantMachine();
  const state = machine.state;
  const active = state !== "OFF";
  const [heard, setHeard] = useState("");
  const [reply, setReply] = useState("");
  const [failure, setFailure] = useState<string | null>(null);
  const [pending, setPending] = useState<Pending[]>([]);
  const [typing, setTyping] = useState(false);
  const [text, setText] = useState("");
  const [continuous, setContinuous] = useState(false);
  const [muted, setMuted] = useState(false);
  const [cid, setCid] = useState<number | null>(() => Number(sessionStorage.getItem("jarvis.orb.cid")) || null);
  const agentLevel = useRef<AgentLevel>({ level: 0, at: 0, source: "mic" });
  const agentBands = useRef(new Float32Array(BAND_COUNT));
  const requesting = useRef(false); // pedido desta tela em andamento
  const [notice, setNotice] = useState<string | null>(null); // aviso sem erro (ex.: "não ouvi nada")
  const [waited, setWaited] = useState(0); // segundos em THINKING
  const [sttLoading, setSttLoading] = useState(false);

  // Eventos reais do navegador (microfone/TTS) → máquina de estados.
  const onVoiceEvent = useCallback((e: VoiceEvent) => {
    switch (e.type) {
      case "mic_started": dispatch({ type: "MIC_STARTED", origin: "browser" }); break;
      case "mic_stopped": dispatch({ type: "MIC_STOPPED" }); break;
      case "transcribing": dispatch({ type: "PROCESSING_STARTED", what: "transcription" }); break;
      case "tts_started": dispatch({ type: "TTS_STARTED", origin: "browser" }); break;
      case "tts_ended": dispatch({ type: "TTS_ENDED" }); break;
      case "error":
        setFailure(e.reason);
        dispatch({ type: "FAILED", reason: e.reason });
        break;
      default: break;
    }
  }, [dispatch]);
  const voice = useVoice(voiceSettings, onVoiceEvent);

  useEffect(() => {
    if (cid) sessionStorage.setItem("jarvis.orb.cid", String(cid));
  }, [cid]);

  // Processando há muito tempo: mostra o tempo e o motivo provável (nunca fica "mudo").
  useEffect(() => {
    if (state !== "THINKING") {
      setWaited(0);
      setSttLoading(false);
      return;
    }
    const t0 = performance.now();
    let asked = false;
    const iv = setInterval(() => {
      const secs = Math.floor((performance.now() - t0) / 1000);
      setWaited(secs);
      if (secs >= 3 && !asked && current.current.processing === "transcription") {
        asked = true;
        api.get<{ stt_loading?: string | null }>("/api/voice/status").then((st) => setSttLoading(Boolean(st.stt_loading))).catch(() => {});
      }
    }, 1000);
    return () => clearInterval(iv);
  }, [state, machine.since, current]);

  // ERROR: pulsos e brilho estável por um tempo, depois volta ao repouso.
  useEffect(() => {
    if (state !== "ERROR") return;
    const t = setTimeout(() => dispatch({ type: "RECOVER" }), ERROR_HOLD_MS);
    return () => clearTimeout(t);
  }, [state, machine.since, dispatch]);

  // Eventos do backend: voz do agente (microfone/alto-falante do PC) e pedidos feitos por voz no PC.
  useEvents((ev) => {
    const m = current.current;
    if (ev.type === "voice_state") {
      const st = String(ev.data.state ?? "idle");
      if (st === "listening") dispatch({ type: "MIC_STARTED", origin: "agent" });
      else if (st === "transcribing") dispatch({ type: "PROCESSING_STARTED", what: "transcription" });
      else if (st === "speaking") dispatch({ type: "TTS_STARTED", origin: "agent" });
      else if (st === "error") {
        const reason = String(ev.data.error ?? "falha na voz do PC");
        setFailure(reason);
        dispatch({ type: "FAILED", reason });
      } else if (m.origin === "agent" && m.state === "LISTENING") dispatch({ type: "MIC_STOPPED" });
      else if (m.origin === "agent" && m.state === "SPEAKING") dispatch({ type: "TTS_ENDED" });
    }
    if (ev.type === "voice_level") {
      agentLevel.current = { level: Number(ev.data.level ?? 0), at: performance.now(), source: String(ev.data.source ?? "mic") };
    }
    if (ev.type === "voice_transcript") {
      setHeard(String(ev.data.text ?? ""));
      if (!requesting.current) dispatch({ type: "PROCESSING_STARTED", what: "request" });
    }
    if (ev.type === "voice_reply") {
      setReply(String(ev.data.text ?? ""));
      if (ev.data.conversation_id) setCid(Number(ev.data.conversation_id));
      // pedido do agente concluído; se ele for falar, voice_state=speaking chega em seguida
      if (!requesting.current && current.current.state === "THINKING" && current.current.processing === "request") {
        setTimeout(() => {
          if (current.current.state === "THINKING" && !requesting.current) dispatch({ type: "PROCESSING_DONE" });
        }, 1500);
      }
    }
    if (ev.type === "confirmation_required" && cid && ev.data.conversation_id === cid) {
      api.get<Pending[]>(`/api/actions/pending?conversation_id=${cid}`).then(setPending).catch(() => {});
    }
  }, ["voice_state", "voice_level", "voice_transcript", "voice_reply", "confirmation_required"]);

  /** Áudio REAL que corresponde ao estado: microfone em LISTENING, TTS em SPEAKING. */
  const readAudio = useCallback((): AudioFrame => {
    const m = current.current;
    if (m.state !== "LISTENING" && m.state !== "SPEAKING") return silentFrame();
    if (m.origin === "browser") return voice.readAudio();
    const a = agentLevel.current;
    const wanted = m.state === "LISTENING" ? "mic" : "tts";
    if (a.source === wanted && performance.now() - a.at < 400) {
      const bands = agentBands.current;
      for (let i = 0; i < BAND_COUNT; i++) bands[i] = a.level * (0.55 + 0.45 * Math.cos((i / BAND_COUNT) * Math.PI));
      return { level: a.level, bands, source: "agent" };
    }
    return silentFrame();
  }, [voice, current]);

  const send = useCallback(
    async (msg: string, origin: "user" | "voice") => {
      const t = msg.trim();
      if (!t) return;
      setHeard(t);
      setReply("");
      setFailure(null);
      setNotice(null);
      requesting.current = true;
      dispatch({ type: "PROCESSING_STARTED", what: "request" });
      let r: ChatReply;
      try {
        // O backend encerra pedidos à IA em 150 s; a margem cobre a rede e a resposta.
        r = await api.post<ChatReply>("/api/chat", { text: t, conversation_id: cid, origin }, 180_000);
      } catch (e) {
        requesting.current = false;
        const reason = `Falha no processamento: ${(e as Error).message}`;
        setReply("");
        setFailure(reason);
        dispatch({ type: "FAILED", reason });
        return;
      }
      requesting.current = false;
      setCid(r.conversation_id);
      setReply(r.text);
      setPending(r.pending ?? []);
      // Continua THINKING até o áudio realmente começar (TTS_STARTED).
      if (!muted && current.current.state !== "OFF") await voice.speak(r.text);
      if (current.current.state === "THINKING") dispatch({ type: "PROCESSING_DONE" });
      if (continuous && current.current.state === "IDLE" && !(r.pending ?? []).length) listenRef.current();
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [cid, muted, continuous, voice, dispatch],
  );

  const listen = useCallback(() => {
    setNotice(null);
    void voice.startListening({
      onUtterance: (said) => {
        if (said) void send(said, "voice");
        else if (said === null && current.current.state !== "ERROR") {
          setNotice("Não ouvi nada. Toque no microfone e fale logo em seguida, perto do microfone.");
        }
      },
    });
  }, [voice, send, current]);
  const listenRef = useRef(listen);
  listenRef.current = listen;

  async function toggleSession() {
    await unlockAudio();
    if (active) {
      voice.cancelListening();
      voice.stopSpeaking();
      dispatch({ type: "SESSION_END" });
    } else {
      dispatch({ type: "SESSION_START" });
    }
  }

  async function micButton() {
    await unlockAudio();
    if (!active) dispatch({ type: "SESSION_START" });
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
    dispatch({ type: "CANCEL" });
    if (requesting.current) await api.post(`/api/chat/cancel${cid ? `?conversation_id=${cid}` : ""}`).catch(() => {});
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
    if (!active) dispatch({ type: "SESSION_START" });
    const t = text;
    setText("");
    await send(t, "user");
  }

  const frameSource = state === "LISTENING" || state === "SPEAKING"
    ? (machine.origin === "agent" ? "agent" : state === "LISTENING" ? "mic" : voice.ttsSource === "piper" ? "tts" : "words")
    : null;
  const cls = state.toLowerCase();

  return (
    <div className={`orb-stage state-${cls}`} data-state={state}>
      <OrbCanvas state={state} readAudio={readAudio} label={`Orb do JARVIS: ${LABELS[state]}`} />

      <header className="orb-top">
        <span className="orb-brand">J.A.R.V.I.S.</span>
        <span className="orb-chip" aria-live="polite">
          <span className={`orb-dot ${cls}`} aria-hidden="true" /> {LABELS[state]}
        </span>
      </header>

      <div className="orb-caption" aria-live="polite">
        {heard && <p className="orb-heard">“{heard}”</p>}
        {reply && <p className="orb-reply">{reply.length > 420 ? `${reply.slice(0, 420)}…` : reply}</p>}
        {!heard && !reply && active && <p className="orb-hint">Pressione <kbd>Espaço</kbd> ou toque no microfone e fale. <kbd>Esc</kbd> interrompe.</p>}
        {!active && <p className="orb-hint">Toque em <strong>Iniciar</strong> para ativar o JARVIS.</p>}
        {state === "THINKING" && waited >= 3 && (
          <p className="orb-wait">
            {machine.processing === "transcription"
              ? (sttLoading ? "Preparando o reconhecimento de voz (só na primeira vez)…" : "Transcrevendo o que você disse…")
              : waited >= 12 ? `Ainda pensando… ${waited} s. Modelos locais no processador podem levar até 1 minuto; Esc cancela.`
                : `Pensando… ${waited} s`}
          </p>
        )}
        {notice && !failure && <p className="orb-hint">{notice}</p>}
        {(failure || voice.error) && <p className="orb-error" role="alert">{failure ?? voice.error}</p>}
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
        <button className={`orb-btn orb-mic ${state === "LISTENING" ? "on" : ""}`} onClick={micButton}
          aria-label={voice.state === "listening" ? "Parar e enviar" : "Falar com o JARVIS"} disabled={voice.state === "transcribing"}>
          <svg viewBox="0 0 24 24" width="28" height="28" aria-hidden="true"><path fill="currentColor" d="M12 15a3 3 0 0 0 3-3V6a3 3 0 1 0-6 0v6a3 3 0 0 0 3 3Zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.92V21h2v-2.08A7 7 0 0 0 19 12h-2Z" /></svg>
        </button>
        <button className="orb-btn" onClick={stopAll} title="Interromper (Esc)" disabled={state === "IDLE" || state === "OFF"}>
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
