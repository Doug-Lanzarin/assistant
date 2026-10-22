import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { ToastProvider } from "../src/components/Toasts";
import { BAND_COUNT, computeRms, logBands, rmsToLevel, WordEnvelope, type AudioFrame } from "../src/orb/audio";
import { approach, follow, OrbEngine, STATE_TARGETS } from "../src/orb/engine";
import { Orb } from "../src/pages/Orb";
import { mockBackend } from "./helpers";

const frame = (level: number): AudioFrame => ({ level, bands: new Float32Array(BAND_COUNT).fill(level), source: level ? "tts" : "none" });

function run(engine: OrbEngine, seconds: number, level: number | ((t: number) => number), step = 1 / 60) {
  for (let t = 0; t < seconds; t += step) engine.update(step, frame(typeof level === "function" ? level(t) : level));
}

describe("medição de áudio", () => {
  it("converte RMS em nível perceptual (dB)", () => {
    expect(rmsToLevel(0)).toBe(0);
    expect(rmsToLevel(0.001)).toBe(0); // −60 dB: silêncio
    expect(rmsToLevel(0.25)).toBeCloseTo(1, 2); // −12 dB: cheio
    expect(rmsToLevel(0.03)).toBeGreaterThan(0.3);
    expect(rmsToLevel(0.03)).toBeLessThan(0.7);
    const sine = new Float32Array(1024).map((_, i) => 0.5 * Math.sin(i / 5));
    expect(computeRms(sine)).toBeCloseTo(0.5 / Math.SQRT2, 2);
  });

  it("agrupa o espectro em faixas logarítmicas", () => {
    const freq = new Uint8Array(512);
    freq[10] = 255; // ~470 Hz com 48 kHz / 1024
    const bands = logBands(freq, 48000);
    expect(bands.length).toBe(BAND_COUNT);
    const peak = bands.indexOf(Math.max(...bands));
    expect(peak).toBeGreaterThan(5);
    expect(peak).toBeLessThan(16);
    expect(bands[BAND_COUNT - 1]).toBe(0);
  });

  it("envelope por palavra decai entre eventos (voz do navegador)", () => {
    const env = new WordEnvelope();
    env.start(0);
    env.word(100);
    const high = env.read(110).level;
    const low = env.read(900).level;
    expect(high).toBeGreaterThan(0.8);
    expect(low).toBeLessThan(0.3);
    env.stop();
    expect(env.read(1000).source).toBe("none");
  });
});

describe("motor do orb", () => {
  it("interpolação é independente da taxa de quadros", () => {
    let a = 0;
    for (let i = 0; i < 60; i++) a = approach(a, 1, 1 / 60, 0.3);
    let b = 0;
    for (let i = 0; i < 20; i++) b = approach(b, 1, 1 / 20, 0.3);
    expect(Math.abs(a - b)).toBeLessThan(1e-9);
    expect(follow(0, 1, 0.035)).toBeGreaterThan(follow(1, 0, 0.035) === 0 ? 0 : 0.6); // ataque rápido
  });

  it("transições são suaves (sem saltos) e convergem para o estado", () => {
    const e = new OrbEngine();
    e.setState("idle");
    let prev = e.params.presence;
    let maxJump = 0;
    for (let i = 0; i < 120; i++) {
      e.update(1 / 60, frame(0));
      maxJump = Math.max(maxJump, Math.abs(e.params.presence - prev));
      prev = e.params.presence;
    }
    expect(maxJump).toBeLessThan(0.06);
    expect(e.params.presence).toBeGreaterThan(0.95);
    e.setState("thinking");
    run(e, 2, 0);
    expect(e.params.spin).toBeCloseTo(STATE_TARGETS.thinking.spin, 1);
    expect(e.params.particles).toBeGreaterThan(0.9);
    e.setState("off");
    run(e, 4, 0);
    expect(e.params.presence).toBeLessThan(0.02);
  });

  it("ao falar, o núcleo acompanha a amplitude real (e não pulsa sozinho)", () => {
    const e = new OrbEngine();
    e.setState("speaking");
    run(e, 2, 0);
    const silent = e.coreScale();
    run(e, 0.3, 0.9);
    const loud = e.coreScale();
    run(e, 1, 0);
    const back = e.coreScale();
    expect(loud).toBeGreaterThan(silent * 1.25);
    expect(back).toBeLessThan(silent * 1.03);
    // segue um sinal oscilante: correlação positiva entre entrada e raio
    const ins: number[] = [];
    const outs: number[] = [];
    let t = 0;
    for (let i = 0; i < 240; i++) {
      const lvl = 0.5 + 0.5 * Math.sin(t * 2 * Math.PI * 2); // 2 Hz, como sílabas
      e.update(1 / 60, frame(lvl));
      ins.push(lvl);
      outs.push(e.coreScale());
      t += 1 / 60;
    }
    const mean = (a: number[]) => a.reduce((x, y) => x + y, 0) / a.length;
    const mi = mean(ins), mo = mean(outs);
    const cov = ins.reduce((s, x, i) => s + (x - mi) * (outs[i] - mo), 0);
    expect(cov).toBeGreaterThan(0);
  });

  it("em repouso o áudio quase não altera o núcleo; ouvindo, os anéis reagem", () => {
    const e = new OrbEngine();
    e.setState("idle");
    run(e, 2, 0);
    const a = e.coreScale();
    run(e, 0.5, 1);
    expect(Math.abs(e.coreScale() - a)).toBeLessThan(0.08);
    e.setState("listening");
    run(e, 1.5, 0.8);
    expect(e.params.rings).toBeGreaterThan(0.95);
    expect(e.level).toBeGreaterThan(0.7);
  });
});

describe("tela do orb", () => {
  it("inicia, encerra e pede o microfone com Espaço", async () => {
    mockBackend({ "POST /api/chat": { conversation_id: 1, text: "ok", actions: [], pending: [] } });
    render(<ToastProvider><Orb voiceSettings={{ tts_engine: "browser" }} /></ToastProvider>);
    expect(screen.getByText("Sessão de voz encerrada")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Iniciar/ }));
    expect(await screen.findByText("Em repouso")).toBeInTheDocument();
    (document.activeElement as HTMLElement | null)?.blur();
    await userEvent.keyboard(" ");
    // jsdom não tem microfone: o erro é mostrado de forma transparente
    expect(await screen.findByRole("alert")).toHaveTextContent(/não permite gravar|Microfone indisponível/);
    await userEvent.click(screen.getByRole("button", { name: /Encerrar/ }));
    expect(await screen.findByText("Sessão de voz encerrada")).toBeInTheDocument();
  });

  it("modo digitação envia ao JARVIS e mostra a resposta", async () => {
    const calls = mockBackend({ "POST /api/chat": { conversation_id: 3, text: "Agora são 10:00.", actions: [], pending: [] } });
    render(<ToastProvider><Orb voiceSettings={{ tts_engine: "browser" }} /></ToastProvider>);
    await userEvent.click(screen.getByRole("button", { name: "digitar" }));
    await userEvent.type(screen.getByLabelText("Mensagem para o JARVIS"), "que horas são?{Enter}");
    expect(await screen.findByText("Agora são 10:00.")).toBeInTheDocument();
    await waitFor(() => expect(calls.find((c) => c.url === "/api/chat")?.body).toMatchObject({ text: "que horas são?", origin: "user" }));
  });
});
