import { useEffect, useRef } from "react";
import { silentFrame, type AudioFrame } from "./audio";
import { OrbEngine, type OrbSnapshot, type OrbState } from "./engine";

declare global {
  interface Window {
    __jarvisOrb?: () => OrbSnapshot & { frameCostMs: number; quality: number };
  }
}

interface Props {
  state: OrbState;
  /** Chamado a cada quadro para obter o áudio real do momento. */
  readAudio: () => AudioFrame;
  label: string;
}

export function OrbCanvas({ state, readAudio, label }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const engineRef = useRef<OrbEngine | null>(null);
  const readRef = useRef(readAudio);
  readRef.current = readAudio;

  if (!engineRef.current) engineRef.current = new OrbEngine();

  useEffect(() => {
    engineRef.current!.setState(state);
  }, [state]);

  useEffect(() => {
    const canvas = canvasRef.current;
    const engine = engineRef.current!;
    const ctx = canvas?.getContext?.("2d") ?? null;
    let quality = 1; // fração da resolução nativa (adaptativa)
    let cost = 0; // média móvel do custo de um quadro (ms)
    window.__jarvisOrb = () => ({ ...engine.snapshot(), frameCostMs: Math.round(cost * 10) / 10, quality });
    const mq = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    engine.reducedMotion = !!mq?.matches;
    if (!canvas || !ctx) return; // ambiente sem canvas (testes): só o estado é mantido

    let w = 0;
    let h = 0;
    // Resolução adaptativa: se os quadros ficarem caros (CPU sem aceleração de vídeo), reduz a
    // resolução interna para não disputar o processador com a transcrição e a IA locais.
    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2) * quality;
      const rect = canvas.getBoundingClientRect();
      w = Math.max(1, rect.width);
      h = Math.max(1, rect.height);
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    resize();
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(resize) : null;
    ro?.observe(canvas);

    let raf = 0;
    let last = performance.now();
    let checkedAt = performance.now();
    const loop = (now: number) => {
      raf = requestAnimationFrame(loop);
      // 60 quadros/s só quando a animação segue o áudio (ouvindo/falando); nos demais, 30 bastam.
      const audioDriven = engine.state === "LISTENING" || engine.state === "SPEAKING";
      if (!audioDriven && now - last < 1000 / 31) return;
      const dt = Math.min(0.1, (now - last) / 1000);
      last = now;
      let frame: AudioFrame;
      try {
        frame = readRef.current();
      } catch {
        frame = silentFrame();
      }
      const t0 = performance.now();
      engine.update(dt, frame);
      engine.draw(ctx, w, h);
      cost = cost * 0.9 + (performance.now() - t0) * 0.1;
      if (now - checkedAt > 2000) {
        checkedAt = now;
        const next = cost > 9 ? Math.max(0.5, quality - 0.25) : cost < 3 && quality < 1 ? Math.min(1, quality + 0.25) : quality;
        if (next !== quality) {
          quality = next;
          resize();
        }
      }
    };
    raf = requestAnimationFrame(loop);
    return () => {
      cancelAnimationFrame(raf);
      ro?.disconnect();
      delete window.__jarvisOrb;
    };
  }, []);

  return <canvas ref={canvasRef} className="orb-canvas" role="img" aria-label={label} />;
}
