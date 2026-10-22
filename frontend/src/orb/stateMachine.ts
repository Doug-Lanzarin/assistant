// Máquina de estados explícita do assistente de voz.
//
// O estado visual do orb é SEMPRE o estado desta máquina, e a máquina só muda
// com eventos funcionais reais:
//   MIC_STARTED   – o fluxo do microfone está ativo (getUserMedia + gravação, ou agente ouvindo)
//   MIC_STOPPED   – a gravação terminou sem nada a processar
//   PROCESSING_STARTED / PROCESSING_DONE – transcrição ou pedido à IA em andamento / concluído sem fala
//   TTS_STARTED   – o áudio da resposta começou a TOCAR (evento "playing"/"start" do mecanismo TTS)
//   TTS_ENDED     – o áudio terminou ou foi interrompido
//   FAILED        – falha de microfone, transcrição, IA ou síntese
//   RECOVER       – fim da sinalização de erro
//   CANCEL        – o usuário interrompeu tudo
//   SESSION_START / SESSION_END – iniciar / encerrar a sessão de voz

export type AssistantState = "OFF" | "IDLE" | "LISTENING" | "THINKING" | "SPEAKING" | "ERROR";

export type AudioOrigin = "browser" | "agent";

export type AssistantEvent =
  | { type: "SESSION_START" }
  | { type: "SESSION_END" }
  | { type: "MIC_STARTED"; origin: AudioOrigin }
  | { type: "MIC_STOPPED" }
  | { type: "PROCESSING_STARTED"; what: "transcription" | "request" }
  | { type: "PROCESSING_DONE" }
  | { type: "TTS_STARTED"; origin: AudioOrigin }
  | { type: "TTS_ENDED" }
  | { type: "FAILED"; reason: string }
  | { type: "RECOVER" }
  | { type: "CANCEL" };

export interface MachineState {
  state: AssistantState;
  since: number; // ms (performance.now) da última transição
  origin: AudioOrigin | null; // quem produz o áudio em LISTENING/SPEAKING
  reason: string | null; // motivo do erro
  processing: "transcription" | "request" | null;
}

export const initialMachine = (now = 0): MachineState => ({ state: "OFF", since: now, origin: null, reason: null, processing: null });

type Handler = (m: MachineState, e: AssistantEvent) => Partial<MachineState> | null;

const to = (state: AssistantState, extra: Partial<MachineState> = {}): Partial<MachineState> => ({
  state, origin: null, reason: null, processing: null, ...extra,
});

/** Tabela de transições: estado → evento → próximo estado (null = evento ignorado nesse estado). */
export const TRANSITIONS: Record<AssistantState, Partial<Record<AssistantEvent["type"], Handler>>> = {
  OFF: {
    SESSION_START: () => to("IDLE"),
  },
  IDLE: {
    MIC_STARTED: (_m, e) => to("LISTENING", { origin: (e as { origin: AudioOrigin }).origin }),
    PROCESSING_STARTED: (_m, e) => to("THINKING", { processing: (e as { what: "transcription" | "request" }).what }),
    TTS_STARTED: (_m, e) => to("SPEAKING", { origin: (e as { origin: AudioOrigin }).origin }),
  },
  LISTENING: {
    MIC_STOPPED: () => to("IDLE"),
    PROCESSING_STARTED: (_m, e) => to("THINKING", { processing: (e as { what: "transcription" | "request" }).what }),
    TTS_STARTED: (_m, e) => to("SPEAKING", { origin: (e as { origin: AudioOrigin }).origin }),
  },
  THINKING: {
    PROCESSING_STARTED: (_m, e) => to("THINKING", { processing: (e as { what: "transcription" | "request" }).what }),
    PROCESSING_DONE: () => to("IDLE"),
    TTS_STARTED: (_m, e) => to("SPEAKING", { origin: (e as { origin: AudioOrigin }).origin }),
    MIC_STARTED: (_m, e) => to("LISTENING", { origin: (e as { origin: AudioOrigin }).origin }),
  },
  SPEAKING: {
    TTS_ENDED: () => to("IDLE"),
    MIC_STARTED: (_m, e) => to("LISTENING", { origin: (e as { origin: AudioOrigin }).origin }), // interrupção pelo usuário
    PROCESSING_STARTED: (_m, e) => to("THINKING", { processing: (e as { what: "transcription" | "request" }).what }),
  },
  ERROR: {
    RECOVER: () => to("IDLE"),
    MIC_STARTED: (_m, e) => to("LISTENING", { origin: (e as { origin: AudioOrigin }).origin }),
    PROCESSING_STARTED: (_m, e) => to("THINKING", { processing: (e as { what: "transcription" | "request" }).what }),
    TTS_STARTED: (_m, e) => to("SPEAKING", { origin: (e as { origin: AudioOrigin }).origin }),
  },
};

/** Eventos válidos em qualquer estado ativo (exceto OFF). */
const GLOBAL: Partial<Record<AssistantEvent["type"], Handler>> = {
  SESSION_END: () => to("OFF"),
  FAILED: (_m, e) => to("ERROR", { reason: (e as { reason: string }).reason }),
  CANCEL: () => to("IDLE"),
};

export function transition(m: MachineState, e: AssistantEvent, now = typeof performance !== "undefined" ? performance.now() : 0): MachineState {
  const handler = TRANSITIONS[m.state][e.type] ?? (m.state !== "OFF" ? GLOBAL[e.type] : undefined);
  if (!handler) return m; // evento sem efeito neste estado (ex.: TTS_ENDED em repouso)
  const patch = handler(m, e);
  if (!patch) return m;
  const next = { ...m, ...patch } as MachineState;
  if (next.state !== m.state) next.since = now;
  return next;
}

/** Tempo que o erro fica sinalizado antes de RECOVER. */
export const ERROR_HOLD_MS = 2600;
