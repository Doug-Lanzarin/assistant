import { useEffect, useRef } from "react";
import { silentFrame, type AudioFrame } from "./audio";
import { OrbEngine, type OrbSnapshot, type OrbState } from "./engine";

declare global {
  interface Window {
    __jarvisOrb?: () => OrbSnapshot;
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
    window.__jarvisOrb = () => engine.snapshot();
    const mq = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    engine.reducedMotion = !!mq?.matches;
    if (!canvas || !ctx) return; // ambiente sem canvas (testes): só o estado é mantido

    let w = 0;
    let h = 0;
    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
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
    const loop = (now: number) => {
      const dt = (now - last) / 1000;
      last = now;
      let frame: AudioFrame;
      try {
        frame = readRef.current();
      } catch {
        frame = silentFrame();
      }
      engine.update(dt, frame);
      engine.draw(ctx, w, h);
      raf = requestAnimationFrame(loop);
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
