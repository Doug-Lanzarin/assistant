// Medição de áudio REAL para o orb (Web Audio API).
//
// * Microfone: MediaStream → AnalyserNode (não é ligado aos alto-falantes).
// * TTS (Piper): <audio> → MediaElementSource → AnalyserNode → saída.
// * Voz do navegador (speechSynthesis): o navegador não expõe o áudio gerado,
//   então a única sincronia possível são os eventos de palavra ("boundary").
//   Isso é sinalizado como fonte "palavras" — não é amplitude.

export type LevelSource = "mic" | "tts" | "words" | "agent" | "none";

export interface AudioFrame {
  level: number; // 0..1 (escala perceptual em dB)
  bands: Float32Array; // 0..1 por faixa de frequência (log)
  source: LevelSource;
}

export const BAND_COUNT = 32;
const EMPTY = new Float32Array(BAND_COUNT);

let sharedCtx: AudioContext | null = null;

export function audioContext(): AudioContext | null {
  if (typeof window === "undefined") return null;
  const Ctor = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!Ctor) return null;
  if (!sharedCtx) sharedCtx = new Ctor();
  return sharedCtx;
}

/** Chamar dentro de um gesto do usuário (clique/tecla) para liberar o áudio. */
export async function unlockAudio(): Promise<void> {
  const ctx = audioContext();
  if (ctx && ctx.state === "suspended") {
    try {
      await ctx.resume();
    } catch {
      /* navegador recusou; o orb segue sem medição */
    }
  }
}

/** RMS (amostras −1..1) → 0..1 numa escala de −60 dB a −12 dB. */
export function rmsToLevel(rms: number): number {
  if (rms <= 1e-6) return 0;
  const db = 20 * Math.log10(rms);
  return Math.min(1, Math.max(0, (db + 60) / 48));
}

export function computeRms(samples: Float32Array): number {
  let sum = 0;
  for (let i = 0; i < samples.length; i++) sum += samples[i] * samples[i];
  return Math.sqrt(sum / Math.max(1, samples.length));
}

/** Agrupa bins de FFT (0..255) em faixas logarítmicas entre fMin e fMax. */
export function logBands(freq: Uint8Array, sampleRate: number, count = BAND_COUNT, fMin = 80, fMax = 8000, out?: Float32Array): Float32Array {
  const res = out ?? new Float32Array(count);
  const nyquist = sampleRate / 2;
  const binHz = nyquist / freq.length;
  for (let b = 0; b < count; b++) {
    const lo = fMin * Math.pow(fMax / fMin, b / count);
    const hi = fMin * Math.pow(fMax / fMin, (b + 1) / count);
    const i0 = Math.max(0, Math.floor(lo / binHz));
    const i1 = Math.min(freq.length - 1, Math.max(i0, Math.ceil(hi / binHz)));
    let peak = 0;
    for (let i = i0; i <= i1; i++) peak = Math.max(peak, freq[i]);
    res[b] = Math.pow(peak / 255, 1.6); // realça diferenças, suprime ruído de fundo
  }
  return res;
}

export class AudioMeter {
  readonly source: LevelSource;
  private analyser: AnalyserNode;
  private node: AudioNode;
  private time: Float32Array<ArrayBuffer>;
  private freq: Uint8Array<ArrayBuffer>;
  private bands = new Float32Array(BAND_COUNT);
  private ctx: AudioContext;

  private constructor(ctx: AudioContext, node: AudioNode, source: LevelSource, audible: boolean) {
    this.ctx = ctx;
    this.node = node;
    this.source = source;
    this.analyser = ctx.createAnalyser();
    this.analyser.fftSize = 1024;
    this.analyser.smoothingTimeConstant = 0.55;
    node.connect(this.analyser);
    if (audible) this.analyser.connect(ctx.destination);
    this.time = new Float32Array(this.analyser.fftSize);
    this.freq = new Uint8Array(this.analyser.frequencyBinCount);
  }

  static fromStream(stream: MediaStream): AudioMeter | null {
    const ctx = audioContext();
    if (!ctx) return null;
    return new AudioMeter(ctx, ctx.createMediaStreamSource(stream), "mic", false);
  }

  static fromElement(el: HTMLMediaElement): AudioMeter | null {
    const ctx = audioContext();
    if (!ctx) return null;
    return new AudioMeter(ctx, ctx.createMediaElementSource(el), "tts", true);
  }

  read(): AudioFrame {
    this.analyser.getFloatTimeDomainData(this.time);
    this.analyser.getByteFrequencyData(this.freq);
    return {
      level: rmsToLevel(computeRms(this.time)),
      bands: logBands(this.freq, this.ctx.sampleRate, BAND_COUNT, 80, 8000, this.bands),
      source: this.source,
    };
  }

  disconnect(): void {
    try {
      this.node.disconnect();
      this.analyser.disconnect();
    } catch {
      /* já desconectado */
    }
  }
}

/** Envelope dirigido por eventos de palavra da speechSynthesis (sem acesso ao áudio). */
export class WordEnvelope {
  private value = 0;
  private last = 0;
  private active = false;

  start(now = performance.now()) {
    this.active = true;
    this.last = now;
    this.value = 0.6;
  }

  word(now = performance.now()) {
    this.decay(now);
    this.value = 1;
  }

  stop() {
    this.active = false;
  }

  private decay(now: number) {
    const dt = (now - this.last) / 1000;
    this.last = now;
    this.value *= Math.exp(-dt / 0.22);
  }

  read(now = performance.now()): AudioFrame {
    if (!this.active) return { level: 0, bands: EMPTY, source: "none" };
    this.decay(now);
    const level = 0.2 + 0.7 * this.value;
    const bands = new Float32Array(BAND_COUNT);
    for (let i = 0; i < BAND_COUNT; i++) bands[i] = level * (1 - i / BAND_COUNT) * 0.8;
    return { level, bands, source: "words" };
  }
}

export function silentFrame(): AudioFrame {
  return { level: 0, bands: EMPTY, source: "none" };
}
