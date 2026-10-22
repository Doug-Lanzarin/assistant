import { vi } from "vitest";

type Handler = (url: string, init?: RequestInit) => unknown;

/** Simula o backend: rotas "MÉTODO /caminho" → resposta JSON (ou função). */
export function mockBackend(routes: Record<string, unknown | Handler>) {
  const calls: { method: string; url: string; body: unknown }[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = (init?.method ?? "GET").toUpperCase();
    const body = typeof init?.body === "string" ? JSON.parse(init.body) : init?.body;
    calls.push({ method, url, body });
    const path = url.split("?")[0];
    const key = Object.keys(routes).find((k) => {
      const [m, p] = k.split(" ");
      return m === method && (p === path || (p.endsWith("*") && path.startsWith(p.slice(0, -1))));
    });
    if (!key) return new Response(JSON.stringify({ detail: `rota não simulada: ${method} ${path}` }), { status: 404, headers: { "content-type": "application/json" } });
    let value = routes[key];
    if (typeof value === "function") value = await (value as Handler)(url, init);
    if (value instanceof Response) return value;
    return new Response(JSON.stringify(value), { status: 200, headers: { "content-type": "application/json" } });
  });
  vi.stubGlobal("fetch", fetchMock);
  return calls;
}

export const STATUS = {
  version: "1.0.0",
  system: { cpu_percent: 12, cpu_count: 8, ram_used_percent: 40, ram_available_gb: 9.1, ram_total_gb: 16, disk_free_gb: 200, internet: true, jarvis_rss_mb: 180 },
  ai: { mode: "remote_first", providers: [{ name: "anthropic", model: "claude-opus-5-5", remote: true, available: true, detail: "ok" }], usage: { tokens_today: 1200, cost_month_usd: 0.42 } },
  agent: { connected: true, info: {} },
  voice: { enabled: true, wake_word_enabled: false, wake_word: "jarvis", agent_voice: true },
  home: { configured: false, devices: 0 },
  whatsapp: { mode: "disabled", can_read: false, can_send: false, detail: "desativado", unread: 0 },
  kill_switch: false,
  pending_actions: 0,
  tasks_pending: 2,
  reminders: [],
  recent_activity: [{ ts: "2026-10-22T10:00:00+00:00", tool: "clipboard_save", status: "ok", result_summary: "Salvei" }],
  running_tasks: 0,
};
