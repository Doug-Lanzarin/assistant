// Motor do "AI Voice Orb" (Canvas 2D, sem dependências).
//
// O estado vem da máquina de estados (stateMachine.ts). Cada estado define
// ALVOS de cor e de parâmetros; o motor interpola continuamente para eles
// (transições suaves de cor e de animação). Tudo que reage a som usa o quadro
// de áudio REAL recebido a cada quadro (audio.ts):
//
//   IDLE      azul profundo · pulsação lenta · brilho baixo
//   LISTENING verde-ciano · núcleo e ondas seguem a intensidade do MICROFONE
//   THINKING  violeta · anéis girando, partículas, pulsação dinâmica
//   SPEAKING  azul elétrico + ciano · núcleo, brilho e ondas concêntricas seguem a AMPLITUDE DO TTS
//   ERROR     vermelho · três pulsos curtos e depois brilho estável
//
// Não há aleatoriedade: ondas só nascem da energia acumulada do áudio
// (silêncio = nenhuma onda) e as partículas têm posições determinísticas.

import { BAND_COUNT, type AudioFrame } from "./audio";
import type { AssistantState } from "./stateMachine";

export type OrbState = AssistantState;
export type RGB = [number, number, number];

export interface OrbParams {
  presence: number; // 0 = apagado, 1 = visível
  scale: number; // escala base do núcleo
  breath: number; // amplitude da pulsação própria do estado (sem áudio)
  breathHz: number; // frequência dessa pulsação
  glow: number; // brilho base
  glowGain: number; // quanto o áudio aumenta o brilho
  levelGain: number; // quanto o áudio expande o núcleo
  rings: number; // anéis polares reagindo ao espectro
  waves: number; // ondas concêntricas dirigidas por energia de áudio
  spin: number; // velocidade de arcos/HUD
  particles: number; // partículas
  arcs: number; // arcos de processamento
}

export interface OrbStyle {
  params: OrbParams;
  primary: RGB; // cor principal (halo, anéis, ondas)
  accent: RGB; // realce do núcleo
}

export const STYLES: Record<AssistantState, OrbStyle> = {
  OFF: {
    params: { presence: 0, scale: 0.35, breath: 0, breathHz: 0.25, glow: 0, glowGain: 0, levelGain: 0, rings: 0, waves: 0, spin: 0.05, particles: 0, arcs: 0 },
    primary: [20, 70, 200], accent: [90, 150, 255],
  },
  IDLE: {
    params: { presence: 1, scale: 0.96, breath: 0.03, breathHz: 0.25, glow: 0.3, glowGain: 0, levelGain: 0, rings: 0, waves: 0, spin: 0.05, particles: 0.12, arcs: 0.08 },
    primary: [24, 78, 210], accent: [110, 160, 255], // azul profundo
  },
  LISTENING: {
    params: { presence: 1, scale: 1, breath: 0, breathHz: 0, glow: 0.78, glowGain: 0.5, levelGain: 0.32, rings: 1, waves: 0.65, spin: 0.12, particles: 0.2, arcs: 0.15 },
    primary: [0, 228, 180], accent: [160, 255, 232], // verde-ciano
  },
  THINKING: {
    params: { presence: 1, scale: 0.92, breath: 0.035, breathHz: 1.4, glow: 0.62, glowGain: 0, levelGain: 0, rings: 0.1, waves: 0, spin: 1, particles: 0.85, arcs: 1 },
    primary: [140, 82, 255], accent: [214, 176, 255], // violeta
  },
  SPEAKING: {
    params: { presence: 1, scale: 1, breath: 0, breathHz: 0, glow: 0.9, glowGain: 0.85, levelGain: 0.45, rings: 0.35, waves: 1, spin: 0.16, particles: 0.25, arcs: 0.12 },
    primary: [0, 136, 255], accent: [90, 242, 255], // azul elétrico + ciano
  },
  ERROR: {
    params: { presence: 1, scale: 0.95, breath: 0, breathHz: 0, glow: 0.6, glowGain: 0, levelGain: 0, rings: 0, waves: 0, spin: 0.03, particles: 0.05, arcs: 0.05 },
    primary: [255, 42, 64], accent: [255, 160, 165], // vermelho
  },
};

/** Duração dos três pulsos de erro (s); depois o brilho fica estável. */
export const ERROR_PULSES = 3;
export const ERROR_PULSE_S = 0.32;

const KEYS = Object.keys(STYLES.IDLE.params) as (keyof OrbParams)[];

/** Aproximação exponencial independente da taxa de quadros. */
export function approach(current: number, target: number, dt: number, tau: number): number {
  return current + (target - current) * (1 - Math.exp(-dt / Math.max(1e-3, tau)));
}

/** Seguidor de envelope: sobe rápido (ataque), desce devagar (liberação). */
export function follow(current: number, input: number, dt: number, attack = 0.035, release = 0.16): number {
  return approach(current, input, dt, input > current ? attack : release);
}

/** Envelope dos pulsos de erro: 3 pulsos curtos e depois 0 (estável). */
export function errorPulse(t: number): number {
  if (t < 0 || t >= ERROR_PULSES * ERROR_PULSE_S) return 0;
  const s = Math.sin((Math.PI * t) / ERROR_PULSE_S);
  return s * s;
}

interface Particle {
  angle: number;
  radius: number;
  speed: number;
  size: number;
  phase: number;
}

interface Wave {
  r: number; // múltiplo do raio base
  alpha: number;
  width: number;
}

export interface OrbSnapshot {
  state: AssistantState;
  params: OrbParams;
  level: number;
  coreRadius: number;
  glow: number;
  color: RGB;
  waves: number;
  source: string;
}

export class OrbEngine {
  state: AssistantState = "OFF";
  params: OrbParams = { ...STYLES.OFF.params };
  primary: RGB = [...STYLES.OFF.primary];
  accent: RGB = [...STYLES.OFF.accent];
  level = 0;
  reducedMotion = false;
  private bands = new Float32Array(BAND_COUNT);
  private source = "none";
  private t = 0;
  private stateT = 0; // segundos desde a última troca de estado
  private rot = 0;
  private energy = 0; // acumulador de energia de áudio → ondas
  private particles: Particle[] = [];
  private waves: Wave[] = [];
  private coreRadius = 0;
  private lastGlow = 0;

  constructor(seed = 7) {
    let s = seed;
    const rnd = () => ((s = (s * 16807) % 2147483647) / 2147483647); // determinístico
    for (let i = 0; i < 70; i++) {
      this.particles.push({ angle: rnd() * Math.PI * 2, radius: 1.35 + rnd() * 1.1, speed: 0.15 + rnd() * 0.5,
        size: 0.6 + rnd() * 1.6, phase: rnd() * Math.PI * 2 });
    }
  }

  setState(s: AssistantState) {
    if (s !== this.state) {
      this.state = s;
      this.stateT = 0;
      this.energy = 0;
    }
  }

  update(dt: number, frame: AudioFrame) {
    dt = Math.min(0.1, Math.max(0, dt));
    this.t += dt;
    this.stateT += dt;
    const style = STYLES[this.state];
    const tau = this.state === "OFF" ? 0.6 : 0.3;
    for (const k of KEYS) this.params[k] = approach(this.params[k], style.params[k], dt, tau);
    for (let i = 0; i < 3; i++) {
      this.primary[i] = approach(this.primary[i], style.primary[i], dt, 0.35);
      this.accent[i] = approach(this.accent[i], style.accent[i], dt, 0.35);
    }
    // Só LISTENING e SPEAKING escutam áudio (microfone / TTS, respectivamente).
    const reactive = this.state === "LISTENING" || this.state === "SPEAKING";
    const input = reactive ? frame.level : 0;
    this.level = follow(this.level, input, dt);
    for (let i = 0; i < BAND_COUNT; i++) this.bands[i] = follow(this.bands[i], reactive ? (frame.bands[i] ?? 0) : 0, dt, 0.03, 0.12);
    this.source = reactive ? frame.source : "none";
    this.rot += dt * (0.25 + this.params.spin * 2.2);

    // Ondas: nascem da energia acumulada do áudio (mais volume = mais ondas). Silêncio = nenhuma.
    if (reactive && this.params.waves > 0.05) {
      this.energy += Math.pow(this.level, 1.5) * dt * 4.2 * this.params.waves;
      if (this.energy >= 1) {
        this.energy -= 1;
        this.waves.push({ r: 1.0, alpha: 0.25 + 0.5 * this.level, width: 1 + 2.2 * this.level });
      }
    }
    for (const w of this.waves) {
      w.r += dt * 0.85;
      w.alpha *= Math.exp(-dt / 0.55);
    }
    this.waves = this.waves.filter((w) => w.alpha > 0.015 && w.r < 3.2);
    for (const p of this.particles) p.angle += dt * p.speed * (0.2 + this.params.spin * 1.6) * (p.phase > Math.PI ? 1 : -1);
  }

  /** Pulsação própria do estado (relógio), usada só em IDLE/THINKING e nos pulsos de erro. */
  private ownPulse(): number {
    const p = this.params;
    let v = Math.sin(this.t * Math.PI * 2 * p.breathHz) * p.breath * (this.reducedMotion ? 0.3 : 1);
    if (this.state === "ERROR") v += 0.09 * errorPulse(this.stateT);
    return v;
  }

  coreScale(): number {
    const p = this.params;
    return Math.max(0, p.scale * (1 + this.ownPulse()) * (1 + this.level * p.levelGain) * (0.55 + 0.45 * p.presence));
  }

  glowLevel(): number {
    const p = this.params;
    let g = p.glow + this.level * p.glowGain;
    if (this.state === "ERROR") g += 0.45 * errorPulse(this.stateT);
    if (this.state === "THINKING") g += 0.12 * Math.sin(this.t * Math.PI * 2 * p.breathHz);
    return Math.max(0, g * p.presence);
  }

  snapshot(): OrbSnapshot {
    return {
      state: this.state, params: { ...this.params }, level: this.level, coreRadius: this.coreRadius, glow: this.lastGlow,
      color: this.primary.map((c) => Math.round(c)) as RGB, waves: this.waves.length, source: this.source,
    };
  }

  draw(ctx: CanvasRenderingContext2D, w: number, h: number) {
    const p = this.params;
    const cx = w / 2;
    const cy = h * (h > 600 ? 0.42 : 0.4);
    const R = Math.min(w, h * 0.92) * 0.145;
    const [pr, pg, pb] = this.primary.map(Math.round);
    const [ar, ag, ab] = this.accent.map(Math.round);
    const prim = (a: number) => `rgba(${pr},${pg},${pb},${Math.max(0, Math.min(1, a))})`;
    const acc = (a: number) => `rgba(${ar},${ag},${ab},${Math.max(0, Math.min(1, a))})`;
    const glow = this.glowLevel();
    this.lastGlow = glow;

    ctx.save();
    ctx.globalCompositeOperation = "source-over";
    ctx.fillStyle = "#01040b";
    ctx.fillRect(0, 0, w, h);
    const vg = ctx.createRadialGradient(cx, cy, R * 0.5, cx, cy, Math.max(w, h) * 0.7);
    vg.addColorStop(0, `rgba(${pr >> 2},${pg >> 2},${pb >> 2},${0.5 * p.presence})`);
    vg.addColorStop(0.45, "rgba(3, 10, 24, 0.65)");
    vg.addColorStop(1, "rgba(0, 0, 0, 1)");
    ctx.fillStyle = vg;
    ctx.fillRect(0, 0, w, h);

    ctx.globalCompositeOperation = "lighter";
    ctx.translate(cx, cy);
    this.drawHud(ctx, R, prim);
    this.drawArcs(ctx, R, prim, acc);
    this.drawRings(ctx, R, prim);
    this.drawParticles(ctx, R, acc);
    for (const wv of this.waves) {
      ctx.beginPath();
      ctx.arc(0, 0, R * wv.r, 0, Math.PI * 2);
      ctx.strokeStyle = prim(wv.alpha * p.presence);
      ctx.lineWidth = wv.width;
      ctx.stroke();
    }
    this.drawCore(ctx, R, prim, acc, glow);
    ctx.restore();
  }

  private drawHud(ctx: CanvasRenderingContext2D, R: number, prim: (a: number) => string) {
    const p = this.params;
    const a = p.presence * (0.07 + 0.1 * p.arcs);
    ctx.lineWidth = 1;
    for (const [k, alpha] of [[1.95, a], [2.45, a * 0.7]] as const) {
      ctx.beginPath();
      ctx.arc(0, 0, R * k, 0, Math.PI * 2);
      ctx.strokeStyle = prim(alpha);
      ctx.stroke();
    }
    const ticks = 72;
    ctx.save();
    ctx.rotate(this.rot * 0.15);
    for (let i = 0; i < ticks; i++) {
      const long = i % 6 === 0;
      const ang = (i / ticks) * Math.PI * 2;
      const r0 = R * 2.45;
      const r1 = R * (long ? 2.58 : 2.51);
      ctx.beginPath();
      ctx.moveTo(Math.cos(ang) * r0, Math.sin(ang) * r0);
      ctx.lineTo(Math.cos(ang) * r1, Math.sin(ang) * r1);
      ctx.strokeStyle = prim(p.presence * (long ? 0.28 : 0.1));
      ctx.stroke();
    }
    ctx.restore();
  }

  private drawArcs(ctx: CanvasRenderingContext2D, R: number, prim: (a: number) => string, acc: (a: number) => string) {
    const p = this.params;
    if (p.arcs < 0.02) return;
    const spec: [number, number, number, number][] = [
      [1.22, 1, 1.9, 2.4], [1.36, -1.3, 1.2, 1.5], [1.62, 0.7, 0.8, 1], [1.62, 0.7, 0.35, 1], [1.8, -0.5, 2.6, 0.8],
    ];
    spec.forEach(([r, dir, span, lw], i) => {
      const start = this.rot * dir + i * 2.1;
      ctx.beginPath();
      ctx.arc(0, 0, R * r, start, start + span);
      ctx.strokeStyle = (i === 0 ? acc : prim)(p.presence * p.arcs * (0.7 - i * 0.1));
      ctx.lineWidth = lw;
      ctx.lineCap = "round";
      ctx.stroke();
    });
  }

  private drawRings(ctx: CanvasRenderingContext2D, R: number, prim: (a: number) => string) {
    const p = this.params;
    const amp = p.rings * (this.reducedMotion ? 0.5 : 1);
    if (amp < 0.02) return;
    const N = 128;
    for (let k = 0; k < 3; k++) {
      const base = R * (1.16 + k * 0.13);
      ctx.beginPath();
      for (let i = 0; i <= N; i++) {
        const a = (i / N) * Math.PI * 2;
        const pos = (i / N) * 2;
        const idx = Math.floor((pos <= 1 ? pos : 2 - pos) * (BAND_COUNT - 1));
        const band = this.bands[idx] ?? 0;
        const r = base + band * R * 0.55 * amp * (1 - k * 0.28) + this.level * R * 0.1 * amp;
        const rot = this.rot * 0.05 * (k + 1);
        const x = Math.cos(a + rot) * r;
        const y = Math.sin(a + rot) * r;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.strokeStyle = prim(p.presence * (0.1 + 0.5 * amp * (0.3 + this.level)) * (1 - k * 0.25));
      ctx.lineWidth = 1.7 - k * 0.4;
      ctx.stroke();
    }
  }

  private drawParticles(ctx: CanvasRenderingContext2D, R: number, acc: (a: number) => string) {
    const p = this.params;
    if (p.particles < 0.02 || this.reducedMotion) return;
    for (const pt of this.particles) {
      const r = R * (pt.radius + Math.sin(this.t * 0.8 + pt.phase) * 0.06 * p.spin);
      const tw = 0.5 + 0.5 * Math.sin(this.t * 2 + pt.phase);
      ctx.beginPath();
      ctx.arc(Math.cos(pt.angle) * r, Math.sin(pt.angle) * r, pt.size * (0.6 + 0.4 * tw), 0, Math.PI * 2);
      ctx.fillStyle = acc(p.presence * p.particles * (0.2 + 0.45 * tw));
      ctx.fill();
    }
  }

  private drawCore(ctx: CanvasRenderingContext2D, R: number, prim: (a: number) => string, acc: (a: number) => string, glow: number) {
    const p = this.params;
    const r = R * this.coreScale();
    this.coreRadius = r;
    if (r < 0.5) return;
    // luz suave ampla (bloom) — cresce com o brilho
    const bloom = ctx.createRadialGradient(0, 0, r * 0.6, 0, 0, r * 4);
    bloom.addColorStop(0, prim(0.16 * glow));
    bloom.addColorStop(1, prim(0));
    ctx.fillStyle = bloom;
    ctx.beginPath();
    ctx.arc(0, 0, r * 4, 0, Math.PI * 2);
    ctx.fill();
    // halo
    const halo = ctx.createRadialGradient(0, 0, r * 0.4, 0, 0, r * 2.5);
    halo.addColorStop(0, prim(0.42 * glow));
    halo.addColorStop(0.45, prim(0.14 * glow));
    halo.addColorStop(1, prim(0));
    ctx.fillStyle = halo;
    ctx.beginPath();
    ctx.arc(0, 0, r * 2.5, 0, Math.PI * 2);
    ctx.fill();
    // núcleo: centro claro → realce → cor principal; intensidade segue o brilho
    const k = Math.min(1, 0.45 + 0.55 * glow);
    const core = ctx.createRadialGradient(-r * 0.18, -r * 0.22, r * 0.05, 0, 0, r);
    core.addColorStop(0, `rgba(240, 250, 255, ${0.9 * p.presence * k})`);
    core.addColorStop(0.3, acc(0.85 * p.presence * k));
    core.addColorStop(0.72, prim(0.6 * p.presence * k));
    core.addColorStop(1, prim(0.05 * p.presence));
    ctx.fillStyle = core;
    ctx.beginPath();
    ctx.arc(0, 0, r, 0, Math.PI * 2);
    ctx.fill();
    ctx.beginPath();
    ctx.arc(0, 0, r * 1.02, 0, Math.PI * 2);
    ctx.strokeStyle = acc(0.5 * p.presence * k);
    ctx.lineWidth = 1.5;
    ctx.stroke();
  }
}
