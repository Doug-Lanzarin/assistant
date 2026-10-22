import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { describe, expect, it } from "vitest";
import App from "../src/App";
import { Chat } from "../src/pages/Chat";
import { Clipboard } from "../src/pages/Clipboard";
import { Dashboard } from "../src/pages/Dashboard";
import { ToastProvider } from "../src/components/Toasts";
import { mockBackend, STATUS } from "./helpers";

async function noA11yViolations(container: HTMLElement) {
  const res = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
  const serious = res.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(serious.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
}

describe("Login", () => {
  it("mostra o primeiro cadastro e entra", async () => {
    const calls = mockBackend({
      "GET /api/auth/status": { has_user: false },
      "POST /api/auth/setup": { token: "tok", username: "doug" },
      "GET /api/settings": { voice: {} },
      "GET /api/status": STATUS,
    });
    const { container } = render(<App />);
    expect(await screen.findByText(/Primeiro acesso/)).toBeInTheDocument();
    await noA11yViolations(container);
    await userEvent.type(screen.getByLabelText("Usuário"), "doug");
    await userEvent.type(screen.getByLabelText("Senha"), "senha-forte-1");
    await userEvent.type(screen.getByLabelText("Confirmar senha"), "senha-forte-1");
    await userEvent.click(screen.getByRole("button", { name: "Criar acesso" }));
    expect(await screen.findByText("Sessão de voz encerrada")).toBeInTheDocument();
    expect(localStorage.getItem("jarvis.token")).toBe("tok");
    expect(calls.find((c) => c.url === "/api/auth/setup")?.body).toEqual({ username: "doug", password: "senha-forte-1" });
  });

  it("exibe erro de senha incorreta", async () => {
    mockBackend({
      "GET /api/auth/status": { has_user: true },
      "POST /api/auth/login": () => new Response(JSON.stringify({ detail: "Usuário ou senha incorretos." }), { status: 401, headers: { "content-type": "application/json" } }),
    });
    render(<App />);
    await userEvent.type(await screen.findByLabelText("Usuário"), "doug");
    await userEvent.type(screen.getByLabelText("Senha"), "errada");
    await userEvent.click(screen.getByRole("button", { name: "Entrar" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("incorretos");
  });

  it("avisa quando o backend está fora do ar", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("Failed to fetch"); }));
    render(<App />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Sem conexão com o backend");
  });
});

describe("Painel", () => {
  it("mostra estados reais e é acessível", async () => {
    mockBackend({ "GET /api/status": STATUS });
    const { container } = render(<ToastProvider><Dashboard go={() => {}} /></ToastProvider>);
    expect(await screen.findByText(/Agente local conectado/)).toBeInTheDocument();
    expect(screen.getByText(/claude-opus-5-5/)).toBeInTheDocument();
    expect(screen.getByText("clipboard_save")).toBeInTheDocument();
    await noA11yViolations(container);
  });

  it("exibe erro com opção de tentar novamente", async () => {
    mockBackend({ "GET /api/status": () => new Response(JSON.stringify({ detail: "falhou" }), { status: 500, headers: { "content-type": "application/json" } }) });
    render(<ToastProvider><Dashboard go={() => {}} /></ToastProvider>);
    expect(await screen.findByRole("alert")).toHaveTextContent("falhou");
    expect(screen.getByRole("button", { name: "Tentar novamente" })).toBeInTheDocument();
  });

  it("aciona a parada de emergência", async () => {
    const calls = mockBackend({ "GET /api/status": STATUS, "POST /api/emergency/stop": { message: "Modo de emergência ativado." } });
    render(<ToastProvider><Dashboard go={() => {}} /></ToastProvider>);
    await userEvent.click(await screen.findByRole("button", { name: "Parada de emergência" }));
    await waitFor(() => expect(calls.some((c) => c.url === "/api/emergency/stop")).toBe(true));
  });
});

describe("Conversa", () => {
  it("envia mensagem, mostra resposta e confirma ação pendente", async () => {
    const pending = [{ id: "p1", conversation_id: 7, tool: "whatsapp_send", summary: "Encontrei João Silva. Vou enviar: “Estou chegando”.", risk: 3, created_at: "", expires_at: new Date(Date.now() + 60000).toISOString() }];
    const calls = mockBackend({
      "GET /api/conversations": [],
      "POST /api/chat": { conversation_id: 7, text: "Encontrei João Silva. Posso enviar?", actions: [{ tool: "whatsapp_send", status: "needs_confirmation", message: "", risk: 3 }], pending, provider: "regras" },
      "GET /api/conversations/7/messages": [],
      "GET /api/actions/pending": pending,
      "POST /api/actions/p1/confirm": { status: "ok", tool: "whatsapp_send", message: "Mensagem enviada para João Silva.", pending_id: "p1", risk: 3 },
    });
    const { container } = render(<ToastProvider><Chat voiceSettings={null} /></ToastProvider>);
    await userEvent.type(screen.getByLabelText("Mensagem"), "mande uma mensagem para o João dizendo que estou chegando{Enter}");
    expect(await screen.findByText("Encontrei João Silva. Posso enviar?")).toBeInTheDocument();
    expect(await screen.findByText("Confirmação necessária")).toBeInTheDocument();
    await noA11yViolations(container);
    await userEvent.click(screen.getByRole("button", { name: "Confirmar" }));
    expect(await screen.findAllByText("Mensagem enviada para João Silva.")).not.toHaveLength(0);
    expect(calls.find((c) => c.url === "/api/actions/p1/confirm")?.body).toEqual({ approve: true });
  });

  it("mostra erro de rede de forma transparente", async () => {
    mockBackend({ "GET /api/conversations": [], "POST /api/chat": () => new Response(JSON.stringify({ detail: "Erro interno" }), { status: 500, headers: { "content-type": "application/json" } }) });
    render(<ToastProvider><Chat voiceSettings={null} /></ToastProvider>);
    await userEvent.type(screen.getByLabelText("Mensagem"), "oi{Enter}");
    expect(await screen.findByText(/Erro interno/)).toBeInTheDocument();
  });
});

describe("Clipboard", () => {
  it("lista registros e copia para o clipboard do Windows", async () => {
    const item = { id: 1, title: "consulta SQL de coletas", category: "sql", project_name: "JARVIS", tags: [], pinned: false, sensitive: false, char_count: 40, copy_count: 0, preview: "SELECT * FROM coletas", created_at: "2026-10-22T10:00:00", updated_at: "", last_copied_at: null };
    const calls = mockBackend({
      "GET /api/clipboard": [item],
      "GET /api/clipboard/categories": [{ category: "sql", n: 1 }],
      "POST /api/clipboard/1/copy": item,
    });
    const { container } = render(<ToastProvider><Clipboard /></ToastProvider>);
    expect(await screen.findByText("consulta SQL de coletas")).toBeInTheDocument();
    await noA11yViolations(container);
    await userEvent.click(screen.getByRole("button", { name: "Copiar" }));
    expect(await screen.findByText(/Cole com Ctrl\+V/)).toBeInTheDocument();
    expect(calls.some((c) => c.method === "POST" && c.url === "/api/clipboard/1/copy")).toBe(true);
  });

  it("informa quando o agente local está desconectado", async () => {
    mockBackend({
      "GET /api/clipboard": [],
      "GET /api/clipboard/categories": [],
      "POST /api/clipboard/save-current": () => new Response(JSON.stringify({ detail: "O agente local do Windows não está conectado." }), { status: 503, headers: { "content-type": "application/json" } }),
    });
    render(<ToastProvider><Clipboard /></ToastProvider>);
    await userEvent.click(await screen.findByRole("button", { name: "Salvar o que copiei" }));
    expect(await screen.findByText(/agente local do Windows não está conectado/)).toBeInTheDocument();
  });
});
