import { describe, expect, it } from "vitest";
import { createVad, vadThresholds } from "../src/hooks/useVoice";

/** Simula o detector a cada 50 ms com uma sequência de (nível, duração em ms). */
function run(parts: [number, number][], maxSeconds = 12) {
  const vad = createVad(maxSeconds);
  let t = 0;
  for (const [lvl, ms] of parts) {
    for (let e = 0; e < ms; e += 50) {
      t += 50;
      const v = vad.feed(lvl, t);
      if (v) return { verdict: v, at: t, floor: vad.floor };
    }
  }
  return { verdict: null, at: t, floor: vad.floor };
}

describe("detecção de fim de fala adaptativa", () => {
  it("sala silenciosa: termina ~0,9 s depois que a fala para", () => {
    const r = run([[0.05, 500], [0.7, 1200], [0.05, 3000]]);
    expect(r.verdict).toBe("speech_end");
    expect(r.at).toBeGreaterThan(1700 + 850);
    expect(r.at).toBeLessThan(1700 + 1100);
  });

  it("notebook com ventoinha (ruído alto): também termina, sem esperar o limite de 12 s", () => {
    // Antes: limiar fixo de silêncio 0,28 abaixo do ruído de 0,33 → só parava em 15 s.
    const r = run([[0.33, 800], [0.75, 1500], [0.34, 4000]]);
    expect(r.verdict).toBe("speech_end");
    expect(r.at).toBeLessThan(4000);
    expect(r.floor).toBeGreaterThan(0.25);
  });

  it("voz baixa (microfone distante) ainda conta como fala", () => {
    const r = run([[0.06, 600], [0.36, 1200], [0.06, 2000]]);
    expect(r.verdict).toBe("speech_end");
  });

  it("estalo curto não é fala; silêncio total encerra sem transcrever", () => {
    const r = run([[0.05, 1000], [0.9, 60], [0.05, 8000]]);
    expect(r.verdict).toBe("no_speech");
    expect(r.at).toBeLessThanOrEqual(7100);
  });

  it("fala contínua longa para no limite", () => {
    expect(run([[0.7, 13_000]], 12).verdict).toBe("too_long");
  });

  it("limiares sobem com o ruído, com mínimos", () => {
    expect(vadThresholds(0.05)).toEqual({ speech: 0.3, silence: 0.16 });
    const noisy = vadThresholds(0.33);
    expect(noisy.speech).toBeCloseTo(0.49);
    expect(noisy.silence).toBeCloseTo(0.4);
  });
});

describe("começar a falar no mesmo instante do clique", () => {
  it("a voz não é aprendida como ruído e o fim é detectado", () => {
    const r = run([[0.7, 1500], [0.05, 2000]]);
    expect(r.verdict).toBe("speech_end");
    expect(r.at).toBeLessThan(1500 + 1100);
  });
});
