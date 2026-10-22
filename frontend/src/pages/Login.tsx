import { useEffect, useState, type FormEvent } from "react";
import { api, auth } from "../services/api";

export function Login({ onLogged }: { onLogged: () => void }) {
  const [hasUser, setHasUser] = useState<boolean | null>(null);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api
      .get<{ has_user: boolean }>("/api/auth/status")
      .then((r) => setHasUser(r.has_user))
      .catch((e) => setError((e as Error).message));
  }, []);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (hasUser === false && password !== confirm) {
      setError("As senhas não conferem.");
      return;
    }
    setBusy(true);
    try {
      const path = hasUser ? "/api/auth/login" : "/api/auth/setup";
      const r = await api.post<{ token: string }>(path, { username, password });
      auth.set(r.token);
      onLogged();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="login-wrap">
      <form className="card login-card stack" onSubmit={submit} aria-labelledby="login-title">
        <div className="row" style={{ gap: 12, marginBottom: 8 }}>
          <div className="brand-orb" aria-hidden="true" />
          <h1 id="login-title" style={{ letterSpacing: 4 }}>
            JARVIS
          </h1>
        </div>
        {hasUser === null && !error && <p className="muted">Conectando ao backend…</p>}
        {hasUser === false && <p className="muted small">Primeiro acesso: crie o usuário do painel (somente neste computador).</p>}
        <label>
          Usuário
          <input autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required />
        </label>
        <label>
          Senha
          <input type="password" autoComplete={hasUser ? "current-password" : "new-password"} value={password} onChange={(e) => setPassword(e.target.value)} required minLength={hasUser ? 1 : 8} />
        </label>
        {hasUser === false && (
          <label>
            Confirmar senha
            <input type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} required minLength={8} />
          </label>
        )}
        {error && (
          <div className="banner danger" role="alert">
            {error}
          </div>
        )}
        <button className="btn primary" disabled={busy || hasUser === null}>
          {hasUser === false ? "Criar acesso" : "Entrar"}
        </button>
      </form>
    </main>
  );
}
