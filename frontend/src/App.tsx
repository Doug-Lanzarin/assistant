import { useCallback, useEffect, useRef, useState } from "react";
import { ToastProvider, useToast } from "./components/Toasts";
import { useApi, useEvents } from "./hooks/useApi";
import { Brain } from "./pages/Brain";
import { Chat } from "./pages/Chat";
import { Clipboard } from "./pages/Clipboard";
import { Dashboard } from "./pages/Dashboard";
import { Home } from "./pages/Home";
import { Login } from "./pages/Login";
import { Orb } from "./pages/Orb";
import { Settings } from "./pages/Settings";
import { WhatsApp } from "./pages/WhatsApp";
import { api, auth } from "./services/api";
import { events } from "./services/events";
import type { Settings as SettingsT } from "./types/api";

const PAGES = [
  { id: "jarvis", label: "JARVIS", icon: "◉" },
  { id: "dashboard", label: "Painel", icon: "◎" },
  { id: "chat", label: "Conversa", icon: "💬" },
  { id: "brain", label: "Segundo cérebro", icon: "🧠" },
  { id: "clipboard", label: "Clipboard", icon: "📋" },
  { id: "home", label: "Casa", icon: "🏠" },
  { id: "whatsapp", label: "WhatsApp", icon: "✉" },
  { id: "settings", label: "Configurações", icon: "⚙" },
] as const;
type PageId = (typeof PAGES)[number]["id"];

function currentPage(): PageId {
  const h = location.hash.replace("#/", "").replace("#", "");
  return (PAGES.find((p) => p.id === h)?.id ?? "jarvis") as PageId;
}

function Shell({ onLogout }: { onLogout: () => void }) {
  const toast = useToast();
  const [page, setPage] = useState<PageId>(currentPage);
  const [busy, setBusy] = useState(false);
  // Menu lateral SEMPRE começa fechado; abre só ao clicar no botão ☰.
  const [menuOpen, setMenuOpen] = useState(false);
  const toggleRef = useRef<HTMLButtonElement>(null);
  const firstItemRef = useRef<HTMLButtonElement>(null);
  const settings = useApi<SettingsT>("/api/settings");

  const closeMenu = useCallback((returnFocus = true) => {
    setMenuOpen(false);
    if (returnFocus) toggleRef.current?.focus();
  }, []);

  useEffect(() => {
    if (!menuOpen) return;
    firstItemRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        closeMenu();
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [menuOpen, closeMenu]);

  useEffect(() => {
    const onHash = () => setPage(currentPage());
    window.addEventListener("hashchange", onHash);
    events.start();
    return () => {
      window.removeEventListener("hashchange", onHash);
      events.stop();
    };
  }, []);

  useEvents((ev) => {
    if (ev.type === "assistant_state") setBusy(ev.data.state === "thinking");
    if (ev.type === "reminder") toast(`⏰ Lembrete: ${String(ev.data.text)}`, "info");
    if (ev.type === "kill_switch") toast(ev.data.active ? "Modo de emergência ativado." : "Operações retomadas.", ev.data.active ? "error" : "ok");
    if (ev.type === "agent") toast(ev.data.connected ? "Agente local conectado." : "Agente local desconectado.", ev.data.connected ? "ok" : "error");
    if (ev.type === "consolidation") toast("Consolidação de memórias concluída.", "info");
  });

  const go = useCallback((p: string) => {
    location.hash = `#/${p}`;
    setMenuOpen(false);
  }, []);

  return (
    <div className={`app ${menuOpen ? "menu-open" : ""}`}>
      <button ref={toggleRef} className={`menu-toggle ${busy ? "busy" : ""}`} aria-expanded={menuOpen} aria-controls="menu-lateral"
        aria-label={menuOpen ? "Fechar menu" : "Abrir menu"} title={menuOpen ? "Fechar menu (Esc)" : "Menu"}
        onClick={() => (menuOpen ? closeMenu() : setMenuOpen(true))}>
        <span aria-hidden="true">{menuOpen ? "✕" : "☰"}</span>
      </button>
      {menuOpen && <div className="menu-scrim" aria-hidden="true" onClick={() => closeMenu()} />}
      <nav id="menu-lateral" className="sidebar" aria-label="Navegação principal" hidden={!menuOpen}>
        <div className="brand">
          <div className={`brand-orb ${busy ? "busy" : ""}`} aria-hidden="true" />
          JARVIS
        </div>
        {PAGES.map((p, i) => (
          <button key={p.id} ref={i === 0 ? firstItemRef : undefined} className="nav-btn"
            aria-current={page === p.id ? "page" : undefined} onClick={() => go(p.id)}>
            <span aria-hidden="true">{p.icon}</span>
            {p.label}
          </button>
        ))}
        <div className="nav-spacer" />
        <button className="nav-btn" onClick={onLogout}>
          <span aria-hidden="true">⏻</span> Sair
        </button>
      </nav>
      <main className={`main ${page === "jarvis" ? "orb-mode" : ""}`} id="conteudo">
        {page === "jarvis" && <Orb voiceSettings={(settings.data?.voice as never) ?? null} />}
        {page === "dashboard" && <Dashboard go={go} />}
        {page === "chat" && <Chat voiceSettings={(settings.data?.voice as never) ?? null} />}
        {page === "brain" && <Brain />}
        {page === "clipboard" && <Clipboard />}
        {page === "home" && <Home go={go} />}
        {page === "whatsapp" && <WhatsApp go={go} />}
        {page === "settings" && <Settings />}
      </main>
    </div>
  );
}

export default function App() {
  const [logged, setLogged] = useState<boolean | null>(auth.token ? null : false);

  useEffect(() => {
    auth.onUnauthorized(() => {
      auth.set(null);
      setLogged(false);
    });
    if (auth.token) {
      api
        .get("/api/auth/me")
        .then(() => setLogged(true))
        .catch(() => {
          auth.set(null);
          setLogged(false);
        });
    }
  }, []);

  async function logout() {
    try {
      await api.post("/api/auth/logout");
    } catch {
      /* sessão já inválida */
    }
    auth.set(null);
    setLogged(false);
  }

  return (
    <ToastProvider>
      {logged === null && <p className="muted" style={{ padding: 24 }}>Carregando…</p>}
      {logged === false && <Login onLogged={() => setLogged(true)} />}
      {logged === true && <Shell onLogout={logout} />}
    </ToastProvider>
  );
}
