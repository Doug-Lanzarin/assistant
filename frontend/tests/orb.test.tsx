import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { ToastProvider } from "../src/components/Toasts";
import { BAND_COUNT, computeRms, logBands, rmsToLevel, WordEnvelope, type AudioFrame } from "../src/orb/audio";
import { approach, ERROR_PULSE_S, ERROR_PULSES, errorPulse, follow, OrbEngine, STYLES } from "../src/orb/engine";
import { initialMachine, transition, TRANSITIONS, type AssistantEvent, type AssistantState } from "../src/orb/stateMachine";
import { Orb } from "../src/pages/Orb";
import { mockBackend } from "./helpers";

const frame = (level: number, source: AudioFrame["source"] = "tts"): AudioFrame =>
  ({ level, bands: new Float32Array(BAND_COUNT).fill(level), source: level ? source : "none" });

function run(engine: OrbEngine, seconds: number, level: number | ((t: number) => number), step = 1 / 60) {
  for (let t = 0; t < seconds; t += step) engine.update(step, frame(typeof level === "function" ? level(t) : level));
}

function play(events: AssistantEvent[]): AssistantState[] {
  let m = initialMachine();
  const seen: AssistantState[] = [m.state];
  for (const e of events) {
    m = transition(m, e, 0);
    seen.push(m.state);
  }
  return seen;
}

describe("máquina de estados", () => {
  it("segue o fluxo real: microfone → transcrição → IA → TTS tocando → fim", () => {
    expect(play([
      { type: "SESSION_START" },
      { type: "MIC_STARTED", origin: "browser" },
      { type: "PROCESSING_STARTED", what: "transcription" },
      { type: "PROCESSING_STARTED", what: "request" },
      { type: "TTS_STARTED", origin: "browser" },
      { type: "TTS_ENDED" },
      { type: "SESSION_END" },
    ])).toEqual(["OFF", "IDLE", "LISTENING", "THINKING", "THINKING", "SPEAKING", "IDLE", "OFF"]);
  });

  it("LISTENING só com microfone real e SPEAKING só com áudio do TTS tocando", () => {
    let m = transition(initialMachine(), { type: "SESSION_START" });
    // terminar fala sem estar falando não muda nada
    expect(transition(m, { type: "TTS_ENDED" })).toBe(m);
    expect(transition(m, { type: "MIC_STOPPED" })).toBe(m);
    // pedido concluído sem áudio volta ao repouso; o processamento não "vira" fala sozinho
    m = transition(m, { type: "PROCESSING_STARTED", what: "request" });
    expect(m.state).toBe("THINKING");
    expect(transition(m, { type: "PROCESSING_DONE" }).state).toBe("IDLE");
    expect(transition(m, { type: "TTS_STARTED", origin: "agent" })).toMatchObject({ state: "SPEAKING", origin: "agent" });
  });

  it("nada acontece desligado, exceto iniciar", () => {
    const off = initialMachine();
    for (const t of ["MIC_STARTED", "TTS_STARTED", "FAILED", "PROCESSING_STARTED"] as const) {
      expect(transition(off, { type: t, origin: "browser", reason: "x", what: "request" } as unknown as AssistantEvent)).toBe(off);
    }
    expect(Object.keys(TRANSITIONS.OFF)).toEqual(["SESSION_START"]);
  });

  it("falha leva a ERROR de qualquer estado ativo, com motivo, e RECOVER volta ao repouso", () => {
    for (const evs of [[], [{ type: "MIC_STARTED", origin: "browser" }], [{ type: "PROCESSING_STARTED", what: "request" }],
      [{ type: "TTS_STARTED", origin: "browser" }]] as AssistantEvent[][]) {
      let m = transition(initialMachine(), { type: "SESSION_START" });
      for (const e of evs) m = transition(m, e);
      m = transition(m, { type: "FAILED", reason: "microfone negado" }, 123);
      expect(m).toMatchObject({ state: "ERROR", reason: "microfone negado", since: 123 });
      expect(transition(m, { type: "RECOVER" }).state).toBe("IDLE");
    }
  });

  it("CANCEL interrompe e o usuário pode interromper a fala com o microfone", () => {
    let m = transition(initialMachine(), { type: "SESSION_START" });
    m = transition(m, { type: "TTS_STARTED", origin: "browser" });
    expect(transition(m, { type: "MIC_STARTED", origin: "browser" }).state).toBe("LISTENING");
    expect(transition(m, { type: "CANCEL" }).state).toBe("IDLE");
  });
});

describe("medição de áudio", () => {
  it("converte RMS em nível perceptual (dB) e agrupa faixas log", () => {
    expect(rmsToLevel(0.001)).toBe(0);
    expect(rmsToLevel(0.25)).toBeCloseTo(1, 2);
    const sine = new Float32Array(1024).map((_, i) => 0.5 * Math.sin(i / 5));
    expect(computeRms(sine)).toBeCloseTo(0.5 / Math.SQRT2, 2);
    const freq = new Uint8Array(512);
    freq[10] = 255;
    const bands = logBands(freq, 48000);
    const peak = bands.indexOf(Math.max(...bands));
    expect(peak).toBeGreaterThan(5);
    expect(peak).toBeLessThan(16);
  });

  it("envelope por palavra decai entre eventos (voz do navegador)", () => {
    const env = new WordEnvelope();
    env.start(0);
    env.word(100);
    expect(env.read(110).level).toBeGreaterThan(0.8);
    expect(env.read(900).level).toBeLessThan(0.3);
  });
});

describe("visual por estado", () => {
  const settle = (s: AssistantState, level = 0) => {
    const e = new OrbEngine();
    e.setState(s);
    run(e, 3, level);
    return e;
  };

  it("cada estado converge para a sua cor", () => {
    const close = (a: number[], b: number[]) => a.every((v, i) => Math.abs(v - b[i]) < 3);
    for (const s of ["IDLE", "LISTENING", "THINKING", "SPEAKING", "ERROR"] as const) {
      expect(close(settle(s).primary, STYLES[s].primary)).toBe(true);
    }
    const [r, g, b] = STYLES.ERROR.primary;
    expect(r).toBeGreaterThan(200); // vermelho
    expect(g + b).toBeLessThan(140);
    expect(STYLES.THINKING.primary[0]).toBeGreaterThan(STYLES.THINKING.primary[1]); // violeta
    expect(STYLES.LISTENING.primary[1]).toBeGreaterThan(200); // verde-ciano
  });

  it("brilho: repouso baixo < processando < ouvindo/falando (com áudio)", () => {
    const idle = settle("IDLE").glowLevel();
    const think = settle("THINKING").glowLevel();
    const listen = settle("LISTENING", 0.7).glowLevel();
    const speak = settle("SPEAKING", 0.7).glowLevel();
    expect(idle).toBeLessThan(0.4);
    expect(think).toBeGreaterThan(idle);
    expect(listen).toBeGreaterThan(think);
    expect(speak).toBeGreaterThan(listen);
  });

  it("transição de cor é suave (sem saltos)", () => {
    const e = settle("IDLE");
    e.setState("THINKING");
    let prev = [...e.primary];
    let maxJump = 0;
    for (let i = 0; i < 90; i++) {
      e.update(1 / 60, frame(0));
      maxJump = Math.max(maxJump, ...e.primary.map((c, k) => Math.abs(c - prev[k])));
      prev = [...e.primary];
    }
    expect(maxJump).toBeLessThan(12);
  });

  it("FALANDO: núcleo e brilho seguem a amplitude real; silêncio não gera ondas", () => {
    const e = settle("SPEAKING", 0);
    const quiet = e.coreScale();
    expect(e.snapshot().waves).toBe(0);
    run(e, 0.4, 0.9);
    expect(e.coreScale()).toBeGreaterThan(quiet * 1.3);
    expect(e.snapshot().waves).toBeGreaterThan(0);
    // mais volume → mais ondas concêntricas
    const count = (lvl: number) => {
      const x = settle("SPEAKING", 0);
      let n = 0;
      let last = 0;
      for (let t = 0; t < 2; t += 1 / 60) {
        x.update(1 / 60, frame(lvl));
        const w = x.snapshot().waves;
        if (w > last) n += w - last;
        last = w;
      }
      return n;
    };
    expect(count(0.9)).toBeGreaterThan(count(0.4));
    expect(count(0)).toBe(0);
  });

  it("OUVINDO: o núcleo expande com a voz; em PROCESSANDO o áudio não interfere", () => {
    const l = settle("LISTENING", 0);
    const base = l.coreScale();
    run(l, 0.3, 0.8);
    expect(l.coreScale()).toBeGreaterThan(base * 1.15);
    const t = settle("THINKING", 0);
    const s0 = t.snapshot();
    run(t, 0.5, 1);
    expect(t.level).toBe(0);
    expect(s0.waves).toBe(0);
  });

  it("ERRO: três pulsos curtos e depois brilho estável", () => {
    expect(errorPulse(-0.1)).toBe(0);
    let peaks = 0;
    let prev = 0;
    let rising = false;
    for (let t = 0; t < 2; t += 0.005) {
      const v = errorPulse(t);
      if (v > prev) rising = true;
      else if (rising && v < prev) {
        peaks++;
        rising = false;
      }
      prev = v;
    }
    expect(peaks).toBe(ERROR_PULSES);
    const e = settle("IDLE");
    e.setState("ERROR");
    const scales: number[] = [];
    for (let t = 0; t < 2.2; t += 1 / 60) {
      e.update(1 / 60, frame(0));
      scales.push(e.coreScale());
    }
    const after = scales.slice(Math.ceil(((ERROR_PULSES * ERROR_PULSE_S) + 0.6) * 60));
    expect(Math.max(...after) - Math.min(...after)).toBeLessThan(0.01); // estável
  });

  it("interpolação independente da taxa de quadros", () => {
    let a = 0;
    for (let i = 0; i < 60; i++) a = approach(a, 1, 1 / 60, 0.3);
    let b = 0;
    for (let i = 0; i < 20; i++) b = approach(b, 1, 1 / 20, 0.3);
    expect(Math.abs(a - b)).toBeLessThan(1e-9);
    expect(follow(0, 1, 0.05)).toBeGreaterThan(0.7);
  });
});

describe("tela do orb", () => {
  it("estado visual = estado da máquina: iniciar, falha real do microfone, recuperação, encerrar", async () => {
    mockBackend({});
    render(<ToastProvider><Orb voiceSettings={{ tts_engine: "browser" }} /></ToastProvider>);
    const stage = () => document.querySelector(".orb-stage")!;
    expect(stage().getAttribute("data-state")).toBe("OFF");
    await userEvent.click(screen.getByRole("button", { name: /Iniciar/ }));
    expect(stage().getAttribute("data-state")).toBe("IDLE");
    (document.activeElement as HTMLElement | null)?.blur();
    await userEvent.keyboard(" ");
    // jsdom não tem microfone → evento real de falha → ERROR (vermelho) com motivo
    await waitFor(() => expect(stage().getAttribute("data-state")).toBe("ERROR"));
    expect(screen.getByRole("alert")).toHaveTextContent(/não permite gravar|Microfone indisponível/);
    expect(window.__jarvisMachine!().log.map((l) => l.to)).toEqual(["IDLE", "ERROR"]);
    await waitFor(() => expect(stage().getAttribute("data-state")).toBe("IDLE"), { timeout: 4000 });
    await userEvent.click(screen.getByRole("button", { name: /Encerrar/ }));
    expect(stage().getAttribute("data-state")).toBe("OFF");
  });

  it("pedido digitado: THINKING durante o processamento e volta ao repouso sem voz", async () => {
    let release!: () => void;
    const gate = new Promise<void>((r) => (release = r));
    mockBackend({
      "POST /api/chat": async () => {
        await gate;
        return { conversation_id: 3, text: "Agora são 10:00.", actions: [], pending: [] };
      },
    });
    render(<ToastProvider><Orb voiceSettings={{ tts_engine: "browser" }} /></ToastProvider>);
    await userEvent.click(screen.getByRole("checkbox", { name: /sem voz/ }));
    await userEvent.click(screen.getByRole("button", { name: "digitar" }));
    await userEvent.type(screen.getByLabelText("Mensagem para o JARVIS"), "que horas são?{Enter}");
    const stage = () => document.querySelector(".orb-stage")!;
    await waitFor(() => expect(stage().getAttribute("data-state")).toBe("THINKING"));
    await act(async () => release());
    expect(await screen.findByText("Agora são 10:00.")).toBeInTheDocument();
    await waitFor(() => expect(stage().getAttribute("data-state")).toBe("IDLE"));
  });

  it("falha do backend vira ERROR com o motivo", async () => {
    mockBackend({ "POST /api/chat": () => new Response(JSON.stringify({ detail: "Erro interno" }), { status: 500, headers: { "content-type": "application/json" } }) });
    render(<ToastProvider><Orb voiceSettings={{ tts_engine: "browser" }} /></ToastProvider>);
    await userEvent.click(screen.getByRole("button", { name: "digitar" }));
    await userEvent.type(screen.getByLabelText("Mensagem para o JARVIS"), "oi{Enter}");
    await waitFor(() => expect(document.querySelector(".orb-stage")!.getAttribute("data-state")).toBe("ERROR"));
    expect(screen.getByRole("alert")).toHaveTextContent("Falha no processamento: Erro interno");
  });
});
