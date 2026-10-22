// Cliente WebSocket de eventos em tempo real, com reconexão automática.
import { auth } from "./api";

export interface JarvisEvent {
  type: string;
  ts?: string;
  data: Record<string, unknown>;
}

type Listener = (ev: JarvisEvent) => void;

class EventStream {
  private ws: WebSocket | null = null;
  private listeners = new Set<Listener>();
  private retry = 1000;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private stopped = true;
  connected = false;

  start() {
    this.stopped = false;
    this.connect();
  }

  stop() {
    this.stopped = true;
    if (this.timer) clearTimeout(this.timer);
    this.ws?.close();
    this.ws = null;
  }

  private connect() {
    const token = auth.token;
    if (!token || this.stopped || typeof WebSocket === "undefined") return;
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/api/ws?token=${encodeURIComponent(token)}`);
    this.ws = ws;
    ws.onopen = () => {
      this.retry = 1000;
      this.connected = true;
      this.emit({ type: "ws", data: { connected: true } });
    };
    ws.onmessage = (m) => {
      try {
        this.emit(JSON.parse(m.data as string) as JarvisEvent);
      } catch {
        /* mensagem não-JSON (pong) */
      }
    };
    ws.onclose = () => {
      this.connected = false;
      this.emit({ type: "ws", data: { connected: false } });
      if (!this.stopped) {
        this.timer = setTimeout(() => this.connect(), this.retry);
        this.retry = Math.min(this.retry * 2, 15000);
      }
    };
  }

  private emit(ev: JarvisEvent) {
    for (const l of this.listeners) l(ev);
  }

  subscribe(fn: Listener): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }
}

export const events = new EventStream();
