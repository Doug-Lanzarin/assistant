// Motor do "AI Voice Orb" (Canvas 2D, sem dependências).
//
// Cada estado define ALVOS para um conjunto de parâmetros visuais; o motor
// interpola continuamente para esses alvos (transições suaves). O nível e as
// faixas de frequência vêm de áudio REAL a cada quadro (ver audio.ts):
//   repouso  → respiração lenta
//   ouvindo  → anéis polares deformados pelo espectro do microfone
//   processando → arcos girando + partículas em órbita
//   falando  → núcleo expande/contrai com a amplitude do TTS + ondas nos picos
//   off      → orb apagado (início/encerramento da sessão)

import { BAND_COUNT, type AudioFrame } from "./audio";

export type OrbState = "off" | "idle" | "listening" | "thinking" | "speaking" | "error";

export interface OrbParams {
  presence: number; // 0 = apagado, 1 = visível
  scale: number; // escala base do núcleo
  breath: number; // amplitude da respiração em repouso
  glow: number; // intensidade do brilho
  rings: number; // reatividade dos anéis ao espectro
  spin: number; // velocidade dos arcos/HUD
  particles: number; // densidade/brilho das partículas
  arcs: number; // visibilidade dos arcos de processamento
  levelGain: number; // quanto o nível de áudio expande o núcleo
  warn: number; // 0 = ciano, 1 = âmbar (erro)
}

export const STATE_TARGETS: Record<OrbState, OrbParams> = {
  off: { presence: 0, scale: 0.35, breath: 0, glow: 0, rings: 0, spin: 0.05, particles: 0, arcs: 0, levelGain: 0, warn: 0 },
  idle: { presence: 1, scale: 1, breath: 0.035, glow: 0.55, rings: 0.08, spin: 0.06, particles: 0.18, arcs: 0.12, levelGain: 0.05, warn: 0 },
  listening: { presence: 1, scale: 1.02, breath: 0.01, glow: 0.75, rings: 1, spin: 0.12, particles: 0.3, arcs: 0.25, levelGain: 0.12, warn: 0 },
  thinking: { presence: 1, scale: 0.9, breath: 0.015, glow: 0.62, rings: 0.12, spin: 1, particles: 1, arcs: 1, levelGain: 0, warn: 0 },
  speaking: { presence: 1, scale: 1, breath: 0.005, glow: 0.7, rings: 0.4, spin: 0.16, particles: 0.35, arcs: 0.2, levelGain: 0.42, warn: 0 },
  error: { presence: 1, scale: 0.95, breath: 0.02, glow: 0.5, rings: 0.05, spin: 0.04, particles: 0.1, arcs: 0.1, levelGain: 0, warn: 1 },
};

const KEYS = Object.keys(STATE_TARGETS.idle) as (keyof OrbParams)[];

/** Aproximação exponencial independente da taxa de quadros. */
export function approach(current: number, target: number, dt: number, tau: number): number {
  return current + (target - current) * (1 - Math.exp(-dt / Math.max(1e-3, tau)));
}

/** Seguidor de envelope: sobe rápido (ataque), desce devagar (liberação). */
export function follow(current: number, input: number, dt: number, attack = 0.035, release = 0.16): number {
  return approach(current, input, dt, input > current ? attack : release);
}

interface Particle {
  angle: number;
  radius: number; // múltiplo do raio base
  speed: number;
  size: number;
  phase: number;
}

interface Ripple {
  r: number; // múltiplo do raio base
  alpha: number;
}

export interface OrbSnapshot {
  state: OrbState;
  params: OrbParams;
  level: number;
  coreRadius: number;
  source: string;
}

export class OrbEngine {
  state: OrbState = "off";
  params: OrbParams = { ...STATE_TARGETS.off };
  level = 0;
  private bands = new Float32Array(BAND_COUNT);
  private source = "none";
  private prevLevel = 0;
  private t = 0;
  private rot = 0;
  private particles: Particle[] = [];
  private ripples: Ripple[] = [];
  private coreRadius = 0;
  reducedMotion = false;

  constructor(seed = 7) {
    // Distribuição determinística das partículas (sem aleatoriedade no áudio).
    let s = seed;
    const rnd = () => ((s = (s * 16807) % 2147483647) / 2147483647);
    for (let i = 0; i < 70; i++) {
      this.particles.push({ angle: rnd() * Math.PI * 2, radius: 1.35 + rnd() * 1.1, speed: 0.15 + rnd() * 0.5,
        size: 0.6 + rnd() * 1.6, phase: rnd() * Math.PI * 2 });
    }
  }

  setState(s: OrbState) {
    this.state = s;
  }

  /** Avança a simulação dt segundos com o quadro de áudio atual. */
  update(dt: number, frame: AudioFrame) {
    dt = Math.min(0.1, Math.max(0, dt));
    this.t += dt;
    const target = STATE_TARGETS[this.state];
    const tau = this.state === "off" ? 0.6 : 0.32;
    for (const k of KEYS) this.params[k] = approach(this.params[k], target[k], dt, tau);
    const input = this.state === "listening" || this.state === "speaking" ? frame.level : frame.level * 0.3;
    this.level = follow(this.level, input, dt);
    for (let i = 0; i < BAND_COUNT; i++) this.bands[i] = follow(this.bands[i], frame.bands[i] ?? 0, dt, 0.03, 0.12);
    this.source = frame.source;
    this.rot += dt * (0.25 + this.params.spin * 2.2);
    // Onda nos picos (início de sílaba/palavra)
    if ((this.state === "speaking" || this.state === "listening") && this.level - this.prevLevel > 0.06 && this.level > 0.35) {
      if (!this.ripples.length || this.ripples[this.ripples.length - 1].r > 1.25) this.ripples.push({ r: 1.02, alpha: 0.55 * this.level });
    }
    this.prevLevel = approach(this.prevLevel, this.level, dt, 0.08);
    for (const rp of this.ripples) {
      rp.r += dt * 0.9;
      rp.alpha *= Math.exp(-dt / 0.45);
    }
    this.ripples = this.ripples.filter((r) => r.alpha > 0.02 && r.r < 3);
    for (const p of this.particles) p.angle += dt * p.speed * (0.2 + this.params.spin * 1.6) * (p.phase > Math.PI ? 1 : -1);
  }

  /** Raio do núcleo em múltiplos do raio base (exposto para testes). */
  coreScale(): number {
    const p = this.params;
    const breath = Math.sin(this.t * 1.35) * p.breath * (this.reducedMotion ? 0.3 : 1);
    return Math.max(0, p.scale * (1 + breath) * (1 + this.level * p.levelGain) * (0.55 + 0.45 * p.presence));
  }

  snapshot(): OrbSnapshot {
    return { state: this.state, params: { ...this.params }, level: this.level, coreRadius: this.coreRadius, source: this.source };
  }

  draw(ctx: CanvasRenderingContext2D, w: number, h: number) {
    const p = this.params;
    const cx = w / 2;
    const cy = h * (h > 600 ? 0.42 : 0.4); // deixa espaço para legendas e controles
    const R = Math.min(w, h * 0.92) * 0.145;
    ctx.save();
    ctx.globalCompositeOperation = "source-over";
    ctx.fillStyle = "#01040b";
    ctx.fillRect(0, 0, w, h);
    const vg = ctx.createRadialGradient(cx, cy, R * 0.5, cx, cy, Math.max(w, h) * 0.7);
    vg.addColorStop(0, `rgba(8, 40, 70, ${0.55 * p.presence})`);
    vg.addColorStop(0.45, "rgba(3, 14, 30, 0.6)");
    vg.addColorStop(1, "rgba(0, 0, 0, 1)");
    ctx.fillStyle = vg;
    ctx.fillRect(0, 0, w, h);

    const hue = 190 - 150 * p.warn; // ciano → âmbar
    const col = (l: number, a: number) => `hsla(${hue}, 100%, ${l}%, ${Math.max(0, Math.min(1, a))})`;
    ctx.globalCompositeOperation = "lighter";
    ctx.translate(cx, cy);

    this.drawHud(ctx, R, col);
    this.drawArcs(ctx, R, col);
    this.drawRings(ctx, R, col);
    this.drawParticles(ctx, R, col);
    for (const rp of this.ripples) {
      ctx.beginPath();
      ctx.arc(0, 0, R * rp.r, 0, Math.PI * 2);
      ctx.strokeStyle = col(70, rp.alpha * p.presence);
      ctx.lineWidth = 1.5;
      ctx.stroke();
    }
    this.drawCore(ctx, R, col);
    ctx.restore();
  }

  private drawHud(ctx: CanvasRenderingContext2D, R: number, col: (l: number, a: number) => string) {
    const p = this.params;
    const a = p.presence * (0.08 + 0.12 * p.arcs);
    ctx.lineWidth = 1;
    for (const [k, alpha] of [[1.95, a], [2.45, a * 0.7]] as const) {
      ctx.beginPath();
      ctx.arc(0, 0, R * k, 0, Math.PI * 2);
      ctx.strokeStyle = col(65, alpha);
      ctx.stroke();
    }
    // Marcações do anel externo, girando devagar
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
      ctx.strokeStyle = col(70, p.presence * (long ? 0.3 : 0.12));
      ctx.stroke();
    }
    ctx.restore();
  }

  private drawArcs(ctx: CanvasRenderingContext2D, R: number, col: (l: number, a: number) => string) {
    const p = this.params;
    if (p.arcs < 0.02) return;
    const spec: [number, number, number, number][] = [
      // raio, sentido, extensão, espessura
      [1.22, 1, 1.9, 2.2], [1.36, -1.3, 1.2, 1.4], [1.62, 0.7, 0.8, 1], [1.62, 0.7, 0.35, 1],
    ];
    spec.forEach(([r, dir, span, lw], i) => {
      const start = this.rot * dir + i * 2.1;
      ctx.beginPath();
      ctx.arc(0, 0, R * r, start, start + span);
      ctx.strokeStyle = col(68, p.presence * p.arcs * (0.65 - i * 0.1));
      ctx.lineWidth = lw;
      ctx.lineCap = "round";
      ctx.stroke();
    });
  }

  private drawRings(ctx: CanvasRenderingContext2D, R: number, col: (l: number, a: number) => string) {
    const p = this.params;
    const N = 128;
    const amp = p.rings * (this.reducedMotion ? 0.5 : 1);
    for (let k = 0; k < 3; k++) {
      const base = R * (1.16 + k * 0.13);
      ctx.beginPath();
      for (let i = 0; i <= N; i++) {
        const a = (i / N) * Math.PI * 2;
        // espelha as faixas para o anel ficar simétrico
        const pos = (i / N) * 2;
        const idx = Math.floor((pos <= 1 ? pos : 2 - pos) * (BAND_COUNT - 1));
        const band = this.bands[idx] ?? 0;
        const wobble = Math.sin(a * (3 + k) + this.t * (1.2 + k * 0.4)) * 0.015;
        const r = base * (1 + wobble * amp) + band * R * 0.5 * amp * (1 - k * 0.28) + this.level * R * 0.08 * amp;
        const x = Math.cos(a + this.rot * 0.05 * (k + 1)) * r;
        const y = Math.sin(a + this.rot * 0.05 * (k + 1)) * r;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.strokeStyle = col(65 + k * 6, p.presence * (0.12 + 0.45 * amp) * (1 - k * 0.25));
      ctx.lineWidth = 1.6 - k * 0.4;
      ctx.stroke();
    }
  }

  private drawParticles(ctx: CanvasRenderingContext2D, R: number, col: (l: number, a: number) => string) {
    const p = this.params;
    if (p.particles < 0.02 || this.reducedMotion) return;
    for (const pt of this.particles) {
      const r = R * (pt.radius + Math.sin(this.t * 0.8 + pt.phase) * 0.06 * p.spin);
      const x = Math.cos(pt.angle) * r;
      const y = Math.sin(pt.angle) * r;
      const tw = 0.5 + 0.5 * Math.sin(this.t * 2 + pt.phase);
      ctx.beginPath();
      ctx.arc(x, y, pt.size * (0.6 + 0.4 * tw), 0, Math.PI * 2);
      ctx.fillStyle = col(75, p.presence * p.particles * (0.25 + 0.5 * tw));
      ctx.fill();
    }
  }

  private drawCore(ctx: CanvasRenderingContext2D, R: number, col: (l: number, a: number) => string) {
    const p = this.params;
    const r = R * this.coreScale();
    this.coreRadius = r;
    if (r < 0.5) return;
    const glowA = p.presence * (p.glow + this.level * p.levelGain * 1.2);
    // halo externo
    const halo = ctx.createRadialGradient(0, 0, r * 0.4, 0, 0, r * 2.6);
    halo.addColorStop(0, col(60, 0.35 * glowA));
    halo.addColorStop(0.45, col(50, 0.12 * glowA));
    halo.addColorStop(1, col(40, 0));
    ctx.fillStyle = halo;
    ctx.beginPath();
    ctx.arc(0, 0, r * 2.6, 0, Math.PI * 2);
    ctx.fill();
    // núcleo
    const core = ctx.createRadialGradient(-r * 0.18, -r * 0.22, r * 0.05, 0, 0, r);
    core.addColorStop(0, `rgba(235, 255, 255, ${0.95 * p.presence})`);
    core.addColorStop(0.28, col(78, 0.85 * p.presence));
    core.addColorStop(0.7, col(52, 0.55 * p.presence));
    core.addColorStop(1, col(45, 0.05 * p.presence));
    ctx.fillStyle = core;
    ctx.beginPath();
    ctx.arc(0, 0, r, 0, Math.PI * 2);
    ctx.fill();
    // borda luminosa
    ctx.beginPath();
    ctx.arc(0, 0, r * 1.02, 0, Math.PI * 2);
    ctx.strokeStyle = col(80, 0.55 * p.presence);
    ctx.lineWidth = 1.5;
    ctx.stroke();
  }
}
