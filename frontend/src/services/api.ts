// Cliente HTTP autenticado do backend do JARVIS.

const TOKEN_KEY = "jarvis.token";

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, message: string, detail?: unknown) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

let unauthorizedHandler: (() => void) | null = null;

export const auth = {
  get token(): string | null {
    try {
      return localStorage.getItem(TOKEN_KEY);
    } catch {
      return null;
    }
  },
  set(token: string | null) {
    try {
      if (token) localStorage.setItem(TOKEN_KEY, token);
      else localStorage.removeItem(TOKEN_KEY);
    } catch {
      /* armazenamento indisponível: sessão só em memória */
    }
  },
  onUnauthorized(fn: () => void) {
    unauthorizedHandler = fn;
  },
};

function messageFrom(body: unknown, status: number): string {
  if (body && typeof body === "object" && "detail" in body) {
    const d = (body as { detail: unknown }).detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d)) return d.map((x) => (x && typeof x === "object" && "msg" in x ? String(x.msg) : String(x))).join("; ");
    if (d && typeof d === "object" && "message" in d) return String((d as { message: unknown }).message);
  }
  return `Erro HTTP ${status}`;
}

export async function request<T = unknown>(path: string, init: RequestInit & { json?: unknown; timeoutMs?: number } = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const token = auth.token;
  if (token) headers.set("Authorization", `Bearer ${token}`);
  let body = init.body;
  if (init.json !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(init.json);
  }
  let res: Response;
  const { timeoutMs, json: _json, ...rest } = init;
  const ctrl = timeoutMs ? new AbortController() : null;
  const timer = ctrl ? setTimeout(() => ctrl.abort(), timeoutMs) : null;
  try {
    res = await fetch(path, { ...rest, headers, body, signal: ctrl?.signal ?? rest.signal });
  } catch {
    if (ctrl?.signal.aborted) {
      throw new ApiError(0, `O JARVIS não respondeu em ${Math.round((timeoutMs ?? 0) / 1000)} s. Tente de novo ou use um pedido mais curto.`);
    }
    throw new ApiError(0, "Sem conexão com o backend do JARVIS. Ele está em execução?");
  } finally {
    if (timer) clearTimeout(timer);
  }
  const ctype = res.headers.get("content-type") ?? "";
  const data = ctype.includes("json") ? await res.json().catch(() => null) : await res.text();
  if (!res.ok) {
    if (res.status === 401 && unauthorizedHandler && !path.startsWith("/api/auth/")) unauthorizedHandler();
    throw new ApiError(res.status, messageFrom(data, res.status), data);
  }
  return data as T;
}

export const api = {
  get: <T = unknown>(p: string) => request<T>(p),
  post: <T = unknown>(p: string, json?: unknown, timeoutMs?: number) => request<T>(p, { method: "POST", json: json ?? {}, timeoutMs }),
  patch: <T = unknown>(p: string, json: unknown) => request<T>(p, { method: "PATCH", json }),
  put: <T = unknown>(p: string, json: unknown) => request<T>(p, { method: "PUT", json }),
  del: <T = unknown>(p: string) => request<T>(p, { method: "DELETE" }),
  upload: <T = unknown>(p: string, form: FormData, timeoutMs?: number) => request<T>(p, { method: "POST", body: form, timeoutMs }),
};

export function qs(params: Record<string, string | number | boolean | undefined | null>): string {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") u.set(k, String(v));
  const s = u.toString();
  return s ? `?${s}` : "";
}
