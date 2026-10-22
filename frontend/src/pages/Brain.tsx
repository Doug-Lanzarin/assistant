import { useMemo, useState, type FormEvent } from "react";
import { useToast } from "../components/Toasts";
import { Card, Empty, ErrorBox, fmtDate, Modal, Pill, Tabs } from "../components/ui";
import { useApi } from "../hooks/useApi";
import { api, qs } from "../services/api";
import type { Memory, SearchHit } from "../types/api";

type Tab = "search" | "memories" | "projects" | "tasks" | "docs" | "timeline" | "graph" | "consolidation";

const KINDS: [string, string][] = [
  ["note", "nota"], ["idea", "ideia"], ["decision", "decisão"], ["fact", "fato"], ["preference", "preferência"],
  ["learning", "aprendizado"], ["goal", "objetivo"], ["event", "evento"], ["project", "estado de projeto"], ["episodic", "episódio"],
];
const STATUS_KIND: Record<string, "ok" | "warn" | "bad" | "info" | ""> = {
  explicit: "ok", confirmed: "ok", inferred: "info", outdated: "warn", contradicted: "bad", rejected: "bad",
};

export function Brain() {
  const [tab, setTab] = useState<Tab>("search");
  return (
    <div>
      <div className="page-head">
        <h1>Segundo cérebro</h1>
        <Stats />
      </div>
      <Tabs
        label="Seções do segundo cérebro"
        value={tab}
        onChange={setTab}
        tabs={[
          { id: "search", label: "Busca" }, { id: "memories", label: "Memórias" }, { id: "projects", label: "Projetos" },
          { id: "tasks", label: "Tarefas" }, { id: "docs", label: "Documentos" }, { id: "timeline", label: "Linha do tempo" },
          { id: "graph", label: "Relações" }, { id: "consolidation", label: "Consolidação" },
        ]}
      />
      {tab === "search" && <Search />}
      {tab === "memories" && <Memories />}
      {tab === "projects" && <Projects />}
      {tab === "tasks" && <Tasks />}
      {tab === "docs" && <Documents />}
      {tab === "timeline" && <Timeline />}
      {tab === "graph" && <GraphView />}
      {tab === "consolidation" && <Consolidation />}
    </div>
  );
}

function Stats() {
  const { data } = useApi<Record<string, number | string>>("/api/brain/stats");
  if (!data) return null;
  return (
    <div className="row small muted">
      <span>{data.memories} memórias</span>·<span>{data.documents} documentos</span>·<span>{data.clipboard} clipboard</span>·
      <span>{data.entities} entidades</span>·<span>embeddings: {data.embedder}</span>
    </div>
  );
}

function Search() {
  const [q, setQ] = useState("");
  const [kind, setKind] = useState("");
  const [period, setPeriod] = useState("");
  const [project, setProject] = useState("");
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  async function run(e: FormEvent) {
    e.preventDefault();
    try {
      setHits(await api.get<SearchHit[]>(`/api/brain/search${qs({ q, kind, period, project })}`));
      setError(null);
    } catch (err) {
      setError((err as Error).message);
    }
  }
  return (
    <div className="stack">
      <form className="card row" onSubmit={run} role="search">
        <label style={{ flex: 3, minWidth: 220 }}>
          Buscar em memórias, documentos e clipboard
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="ex.: decisões sobre o banco de dados" required />
        </label>
        <label style={{ flex: 1, minWidth: 140 }}>
          Tipo
          <select value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="">todos</option>
            {KINDS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select>
        </label>
        <label style={{ flex: 1, minWidth: 140 }}>
          Período
          <select value={period} onChange={(e) => setPeriod(e.target.value)}>
            <option value="">qualquer</option>
            {["hoje", "ontem", "esta semana", "semana passada", "este mês", "mês passado", "últimos 90 dias"].map((p) => <option key={p}>{p}</option>)}
          </select>
        </label>
        <label style={{ flex: 1, minWidth: 140 }}>
          Projeto
          <input value={project} onChange={(e) => setProject(e.target.value)} />
        </label>
        <button className="btn primary" style={{ alignSelf: "flex-end" }}>Buscar</button>
      </form>
      <ErrorBox error={error} />
      {hits && (
        <Card title={`${hits.length} resultado(s)`}>
          {hits.length ? (
            <ul className="list">
              {hits.map((h) => (
                <li key={`${h.owner_type}${h.owner_id}`}>
                  <div className="row between">
                    <strong>{h.title}</strong>
                    <span className="row">
                      <Pill kind="info">{h.kind}</Pill>
                      {h.status && <Pill kind={STATUS_KIND[h.status] ?? ""}>{h.status}</Pill>}
                      {h.stale && <Pill kind="warn">possivelmente desatualizada</Pill>}
                    </span>
                  </div>
                  <p className="small" style={{ margin: "6px 0" }}>{h.snippet}</p>
                  <div className="muted small">{h.citation} · {fmtDate(h.created_at)} · relevância {h.score}</div>
                </li>
              ))}
            </ul>
          ) : (
            <Empty>Nada encontrado. O JARVIS não inventa: se não há evidência, não há resultado.</Empty>
          )}
        </Card>
      )}
    </div>
  );
}

function MemoryForm({ initial, onSaved }: { initial?: Memory; onSaved: () => void }) {
  const toast = useToast();
  const [content, setContent] = useState(initial?.content ?? "");
  const [title, setTitle] = useState(initial?.title ?? "");
  const [kind, setKind] = useState(initial?.kind ?? "note");
  const [project, setProject] = useState(initial?.project_name ?? "");
  const [tags, setTags] = useState((initial?.tags ?? []).join(", "));
  async function save(e: FormEvent) {
    e.preventDefault();
    const body = { content, title, kind, project: project || null, tags: tags.split(",").map((t) => t.trim()).filter(Boolean) };
    try {
      if (initial) await api.patch(`/api/brain/memories/${initial.id}`, body);
      else await api.post("/api/brain/memories", body);
      toast("Memória salva.", "ok");
      onSaved();
    } catch (err) {
      toast((err as Error).message, "error");
    }
  }
  return (
    <form className="stack" onSubmit={save}>
      <label>Título (opcional)<input value={title} onChange={(e) => setTitle(e.target.value)} /></label>
      <label>Conteúdo<textarea rows={5} value={content} onChange={(e) => setContent(e.target.value)} required /></label>
      <div className="row">
        <label style={{ flex: 1 }}>Tipo
          <select value={kind} onChange={(e) => setKind(e.target.value)}>{KINDS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
        </label>
        <label style={{ flex: 1 }}>Projeto<input value={project} onChange={(e) => setProject(e.target.value)} /></label>
      </div>
      <label>Etiquetas (separadas por vírgula)<input value={tags} onChange={(e) => setTags(e.target.value)} /></label>
      <button className="btn primary">Salvar</button>
    </form>
  );
}

function Memories() {
  const toast = useToast();
  const [kind, setKind] = useState("");
  const [status, setStatus] = useState("");
  const { data, error, reload } = useApi<Memory[]>(`/api/brain/memories${qs({ kind, status, limit: 200 })}`, [kind, status]);
  const [editing, setEditing] = useState<Memory | null | "new">(null);

  async function setSt(m: Memory, st: string) {
    await api.patch(`/api/brain/memories/${m.id}`, { status: st });
    toast(`Memória #${m.id}: ${st}`, "ok");
    void reload();
  }
  async function remove(m: Memory) {
    if (!confirm(`Apagar a memória #${m.id} e todos os índices derivados? Isso não pode ser desfeito.`)) return;
    const r = await api.del<{ chunks: number; graph_links: number }>(`/api/brain/memories/${m.id}`);
    toast(`Apagada (${r.chunks} trechos e ${r.graph_links} ligações removidos).`, "ok");
    void reload();
  }

  return (
    <div className="stack">
      <div className="row">
        <select aria-label="Filtrar tipo" value={kind} onChange={(e) => setKind(e.target.value)} style={{ width: 180 }}>
          <option value="">todos os tipos</option>
          {[...KINDS, ["session_summary", "resumo de sessão"]].map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </select>
        <select aria-label="Filtrar estado" value={status} onChange={(e) => setStatus(e.target.value)} style={{ width: 180 }}>
          <option value="">estados ativos</option>
          {Object.keys(STATUS_KIND).map((s) => <option key={s}>{s}</option>)}
        </select>
        <button className="btn primary" onClick={() => setEditing("new")}>Nova memória</button>
      </div>
      <ErrorBox error={error} onRetry={reload} />
      <ul className="list">
        {(data ?? []).map((m) => (
          <li key={m.id}>
            <div className="row between">
              <strong>#{m.id} {m.title || m.content.slice(0, 70)}</strong>
              <span className="row">
                <Pill kind="info">{m.kind_label}</Pill>
                <Pill kind={STATUS_KIND[m.status] ?? ""} title={`confiança ${m.confidence}`}>{m.status}</Pill>
                {m.stale && <Pill kind="warn">desatualizada?</Pill>}
                {m.project_name && <Pill>{m.project_name}</Pill>}
              </span>
            </div>
            <p className="small" style={{ whiteSpace: "pre-wrap", margin: "6px 0" }}>{m.content}</p>
            <div className="row between small">
              <span className="muted">origem: {m.source} · {fmtDate(m.created_at)}{m.tags.length ? ` · #${m.tags.join(" #")}` : ""}</span>
              <span className="row">
                {m.status === "inferred" && <button className="btn small success" onClick={() => setSt(m, "confirmed")}>Confirmar</button>}
                {m.status !== "rejected" && m.status !== "explicit" && m.status !== "confirmed" && <button className="btn small" onClick={() => setSt(m, "rejected")}>Rejeitar</button>}
                {m.status !== "outdated" && <button className="btn small" onClick={() => setSt(m, "outdated")}>Desatualizada</button>}
                <button className="btn small" onClick={() => setEditing(m)}>Editar</button>
                <button className="btn small danger" onClick={() => remove(m)}>Apagar</button>
              </span>
            </div>
          </li>
        ))}
      </ul>
      {data && !data.length && <Empty>Nenhuma memória com esses filtros.</Empty>}
      <Modal open={editing !== null} onClose={() => setEditing(null)} title={editing === "new" ? "Nova memória" : "Editar memória"}>
        <MemoryForm initial={editing === "new" || editing === null ? undefined : editing} onSaved={() => { setEditing(null); void reload(); }} />
      </Modal>
    </div>
  );
}

interface Project { id: number; name: string; description: string; status: string; memories: number; pending_tasks: number; updated_at: string }
interface Overview { project: Project; decisions: Memory[]; ideas: Memory[]; memories: Memory[]; tasks: { id: number; title: string; status: string }[]; relations: { rel: string; direction: string; other_name: string; other_type: string }[] }

function Projects() {
  const { data, reload } = useApi<Project[]>("/api/brain/projects");
  const [sel, setSel] = useState<number | null>(null);
  const ov = useApi<Overview>(sel ? `/api/brain/projects/${sel}` : null, [sel]);
  const [name, setName] = useState("");
  async function create(e: FormEvent) {
    e.preventDefault();
    const p = await api.post<Project>("/api/brain/projects", { name });
    setName("");
    await reload();
    setSel(p.id);
  }
  return (
    <div className="split">
      <div className="card tight stack">
        <form className="row" onSubmit={create}>
          <input aria-label="Nome do novo projeto" placeholder="Novo projeto" value={name} onChange={(e) => setName(e.target.value)} required style={{ flex: 1 }} />
          <button className="btn small primary">Criar</button>
        </form>
        <ul className="list">
          {(data ?? []).map((p) => (
            <li key={p.id} className={p.id === sel ? "active" : ""}>
              <button className="item" onClick={() => setSel(p.id)}>
                <strong>{p.name}</strong>
                <div className="muted small">{p.memories} memórias · {p.pending_tasks} tarefas pendentes</div>
              </button>
            </li>
          ))}
        </ul>
        {data && !data.length && <Empty>Projetos aparecem quando você registra algo "no projeto X".</Empty>}
      </div>
      <div className="stack">
        {!ov.data && <Empty>Selecione um projeto.</Empty>}
        {ov.data && (
          <>
            <Card title={ov.data.project.name}>
              <p className="muted small">{ov.data.project.description || "Sem descrição."} · atualizado {fmtDate(ov.data.project.updated_at)}</p>
              {!!ov.data.relations.length && (
                <div className="row">
                  {ov.data.relations.map((r, i) => <Pill key={i} kind="info">{r.direction === "out" ? `${r.rel.replace("_", " ")} ${r.other_name}` : `${r.other_name} ${r.rel}`}</Pill>)}
                </div>
              )}
            </Card>
            <div className="grid cols-2">
              <Card title="Decisões">{ov.data.decisions.length ? <ul className="list small">{ov.data.decisions.map((d) => <li key={d.id}>{d.content}</li>)}</ul> : <Empty>Nenhuma.</Empty>}</Card>
              <Card title="Tarefas">{ov.data.tasks.length ? <ul className="list small">{ov.data.tasks.map((t) => <li key={t.id}>{t.status === "done" ? "✔ " : "○ "}{t.title}</li>)}</ul> : <Empty>Nenhuma.</Empty>}</Card>
              <Card title="Ideias">{ov.data.ideas.length ? <ul className="list small">{ov.data.ideas.map((d) => <li key={d.id}>{d.content}</li>)}</ul> : <Empty>Nenhuma.</Empty>}</Card>
              <Card title="Memórias recentes">{ov.data.memories.length ? <ul className="list small">{ov.data.memories.slice(0, 10).map((d) => <li key={d.id}>[{d.kind_label}] {d.content.slice(0, 160)}</li>)}</ul> : <Empty>Nenhuma.</Empty>}</Card>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

interface Task { id: number; title: string; status: string; due_at: string | null; project_name: string | null }
interface Reminder { id: number; text: string; due_at: string; status: string }

function Tasks() {
  const toast = useToast();
  const [show, setShow] = useState("pending");
  const tasks = useApi<Task[]>(`/api/brain/tasks${qs({ status: show })}`, [show]);
  const reminders = useApi<Reminder[]>("/api/brain/reminders");
  const [title, setTitle] = useState("");
  const [due, setDue] = useState("");
  const [project, setProject] = useState("");
  const [rem, setRem] = useState("");
  async function add(e: FormEvent) {
    e.preventDefault();
    try {
      await api.post("/api/brain/tasks", { title, due_text: due || null, project: project || null });
      setTitle(""); setDue("");
      void tasks.reload();
    } catch (err) { toast((err as Error).message, "error"); }
  }
  async function addReminder(e: FormEvent) {
    e.preventDefault();
    try {
      await api.post("/api/brain/reminders", { text: rem });
      setRem("");
      void reminders.reload();
    } catch (err) { toast((err as Error).message, "error"); }
  }
  async function setStatus(t: Task, status: string) {
    await api.patch(`/api/brain/tasks/${t.id}`, { status });
    void tasks.reload();
  }
  return (
    <div className="grid cols-2">
      <Card title="Tarefas" actions={
        <select aria-label="Filtrar tarefas" value={show} onChange={(e) => setShow(e.target.value)} style={{ width: 140 }}>
          <option value="pending">pendentes</option><option value="done">concluídas</option><option value="">todas</option>
        </select>}>
        <form className="stack" onSubmit={add}>
          <input aria-label="Nova tarefa" placeholder="Nova tarefa" value={title} onChange={(e) => setTitle(e.target.value)} required />
          <div className="row">
            <input aria-label="Prazo" placeholder="prazo (ex.: sexta às 15)" value={due} onChange={(e) => setDue(e.target.value)} style={{ flex: 1 }} />
            <input aria-label="Projeto da tarefa" placeholder="projeto" value={project} onChange={(e) => setProject(e.target.value)} style={{ flex: 1 }} />
            <button className="btn primary">Adicionar</button>
          </div>
        </form>
        <ul className="list" style={{ marginTop: 12 }}>
          {(tasks.data ?? []).map((t) => (
            <li key={t.id} className="row between">
              <label className="inline">
                <input type="checkbox" checked={t.status === "done"} onChange={() => setStatus(t, t.status === "done" ? "pending" : "done")} />
                <span>{t.title}{t.project_name && <span className="muted small"> · {t.project_name}</span>}{t.due_at && <span className="muted small"> · {fmtDate(t.due_at)}</span>}</span>
              </label>
              <button className="btn small ghost" aria-label={`Apagar ${t.title}`} onClick={async () => { await api.del(`/api/brain/tasks/${t.id}`); void tasks.reload(); }}>✕</button>
            </li>
          ))}
        </ul>
        {tasks.data && !tasks.data.length && <Empty>Nada por aqui.</Empty>}
      </Card>
      <Card title="Lembretes">
        <form className="row" onSubmit={addReminder}>
          <input aria-label="Novo lembrete" placeholder="ex.: revisar o código amanhã às 9" value={rem} onChange={(e) => setRem(e.target.value)} required style={{ flex: 1 }} />
          <button className="btn primary">Agendar</button>
        </form>
        <ul className="list" style={{ marginTop: 12 }}>
          {(reminders.data ?? []).map((r) => (
            <li key={r.id} className="row between">
              <span>{r.text} <span className="muted small">— {fmtDate(r.due_at)}</span></span>
              <button className="btn small ghost" aria-label={`Cancelar ${r.text}`} onClick={async () => { await api.del(`/api/brain/reminders/${r.id}`); void reminders.reload(); }}>✕</button>
            </li>
          ))}
        </ul>
        {reminders.data && !reminders.data.length && <Empty>Nenhum lembrete agendado.</Empty>}
      </Card>
    </div>
  );
}

interface Doc { id: number; title: string; filename: string; size: number; char_count: number; imported_at: string; project_name: string | null }

function Documents() {
  const toast = useToast();
  const { data, reload } = useApi<Doc[]>("/api/brain/documents");
  const [busy, setBusy] = useState(false);
  const [project, setProject] = useState("");
  const [view, setView] = useState<(Doc & { text: string }) | null>(null);
  async function upload(files: FileList | null) {
    if (!files?.length) return;
    setBusy(true);
    for (const f of Array.from(files)) {
      const form = new FormData();
      form.append("file", f);
      if (project) form.append("project", project);
      try {
        const r = await api.upload<{ duplicate: boolean; chunks: number }>("/api/brain/documents", form);
        toast(r.duplicate ? `${f.name}: já importado.` : `${f.name}: ${r.chunks} trecho(s) indexado(s).`, "ok");
      } catch (e) {
        toast(`${f.name}: ${(e as Error).message}`, "error");
      }
    }
    setBusy(false);
    void reload();
  }
  return (
    <div className="stack">
      <Card title="Importar documentos">
        <p className="muted small">PDF, DOCX, Markdown, texto e código. O conteúdo é tratado como dado (nunca como instrução) e fica só neste computador.</p>
        <div className="row">
          <input type="file" multiple aria-label="Arquivos para importar" disabled={busy} onChange={(e) => void upload(e.target.files)}
            accept=".pdf,.docx,.md,.markdown,.txt,.csv,.json,.yaml,.yml,.toml,.py,.js,.ts,.tsx,.java,.cs,.sql,.html,.htm,.log,.ps1,.sh" />
          <input aria-label="Projeto dos documentos" placeholder="projeto (opcional)" value={project} onChange={(e) => setProject(e.target.value)} style={{ maxWidth: 220 }} />
          {busy && <span className="muted">Importando…</span>}
        </div>
      </Card>
      <Card title="Biblioteca">
        {data?.length ? (
          <table>
            <thead><tr><th>Documento</th><th>Projeto</th><th>Tamanho</th><th>Importado</th><th /></tr></thead>
            <tbody>
              {data.map((d) => (
                <tr key={d.id}>
                  <td><button className="btn ghost small" onClick={async () => setView(await api.get(`/api/brain/documents/${d.id}`))}>{d.title}</button><div className="muted small">{d.filename}</div></td>
                  <td>{d.project_name ?? "—"}</td>
                  <td className="small">{(d.size / 1024).toFixed(0)} KB · {d.char_count} car.</td>
                  <td className="small">{fmtDate(d.imported_at)}</td>
                  <td><button className="btn small danger" onClick={async () => { if (confirm(`Remover ${d.filename} e seus índices?`)) { await api.del(`/api/brain/documents/${d.id}`); void reload(); } }}>Remover</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <Empty>Nenhum documento importado.</Empty>}
      </Card>
      <Modal open={!!view} onClose={() => setView(null)} title={view?.filename ?? ""}>
        <pre style={{ maxHeight: "60vh", overflow: "auto" }}>{view?.text}</pre>
      </Modal>
    </div>
  );
}

interface TimelineItem { type: string; id: number; kind: string; title: string; at: string; project: string | null }

function Timeline() {
  const [period, setPeriod] = useState("últimos 30 dias");
  const { data } = useApi<{ label: string; items: TimelineItem[] }>(`/api/brain/timeline${qs({ period })}`, [period]);
  const groups = useMemo(() => {
    const g: Record<string, TimelineItem[]> = {};
    for (const it of data?.items ?? []) (g[new Date(it.at).toLocaleDateString("pt-BR")] ??= []).push(it);
    return Object.entries(g);
  }, [data]);
  return (
    <Card title="Linha do tempo" actions={
      <select aria-label="Período" value={period} onChange={(e) => setPeriod(e.target.value)} style={{ width: 180 }}>
        {["hoje", "ontem", "esta semana", "semana passada", "últimos 30 dias", "mês passado", "últimos 90 dias", "ano passado"].map((p) => <option key={p}>{p}</option>)}
      </select>}>
      {groups.length ? groups.map(([day, items]) => (
        <div key={day} style={{ marginBottom: 14 }}>
          <h3>{day}</h3>
          <ul className="list">
            {items.map((it) => (
              <li key={`${it.type}${it.id}${it.kind}`} className="small">
                <span className="muted">{new Date(it.at).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}</span> · <Pill>{it.kind}</Pill> {it.title}
                {it.project && <span className="muted"> · {it.project}</span>}
              </li>
            ))}
          </ul>
        </div>
      )) : <Empty>Sem registros em {data?.label ?? period}.</Empty>}
    </Card>
  );
}

interface GNode { id: number; type: string; name: string; mentions: number }
interface GEdge { id: number; src_id: number; rel: string; dst_id: number; status: string }
const TYPE_COLOR: Record<string, string> = { project: "#3fb6ff", technology: "#2fe0a0", person: "#ffc857", idea: "#c792ea", decision: "#ff8f6b", task: "#93a4c6", document: "#6bd1ff", tag: "#7a8bb0" };

function GraphView() {
  const { data } = useApi<{ nodes: GNode[]; edges: GEdge[] }>("/api/brain/graph?limit=80");
  const [focus, setFocus] = useState<GNode | null>(null);
  const layout = useMemo(() => {
    const nodes = data?.nodes ?? [];
    const pos = new Map<number, { x: number; y: number }>();
    const projects = nodes.filter((n) => n.type === "project");
    const others = nodes.filter((n) => n.type !== "project");
    projects.forEach((n, i) => {
      const a = (2 * Math.PI * i) / Math.max(1, projects.length);
      pos.set(n.id, { x: 450 + 120 * Math.cos(a), y: 230 + 90 * Math.sin(a) });
    });
    others.forEach((n, i) => {
      const a = (2 * Math.PI * i) / Math.max(1, others.length);
      pos.set(n.id, { x: 450 + 360 * Math.cos(a), y: 230 + 190 * Math.sin(a) });
    });
    return pos;
  }, [data]);
  if (!data) return <p className="muted">Carregando…</p>;
  if (!data.nodes.length) return <Empty>O grafo cresce conforme você registra memórias com projetos, tecnologias e pessoas.</Empty>;
  const related = focus ? new Set(data.edges.filter((e) => e.src_id === focus.id || e.dst_id === focus.id).flatMap((e) => [e.src_id, e.dst_id])) : null;
  return (
    <Card title="Relações entre informações" actions={<span className="muted small">{data.nodes.length} entidades · {data.edges.length} relações</span>}>
      <svg className="graph-svg" viewBox="0 0 900 460" role="img" aria-label="Grafo de conhecimento">
        {data.edges.map((e) => {
          const a = layout.get(e.src_id), b = layout.get(e.dst_id);
          if (!a || !b) return null;
          const dim = related && !(related.has(e.src_id) && related.has(e.dst_id));
          return <line key={e.id} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke={e.status === "inferred" ? "#2a4170" : "#3b5a94"} strokeDasharray={e.status === "inferred" ? "4 3" : undefined} opacity={dim ? 0.15 : 0.9} />;
        })}
        {data.nodes.map((n) => {
          const p = layout.get(n.id)!;
          const dim = related && !related.has(n.id);
          return (
            <g key={n.id} transform={`translate(${p.x},${p.y})`} opacity={dim ? 0.25 : 1} onClick={() => setFocus(focus?.id === n.id ? null : n)} style={{ cursor: "pointer" }}
              role="button" tabIndex={0} aria-label={`${n.type} ${n.name}`} onKeyDown={(e) => e.key === "Enter" && setFocus(n)}>
              <circle r={5 + Math.min(10, n.mentions)} fill={TYPE_COLOR[n.type] ?? "#93a4c6"} />
              <text y={-10 - Math.min(10, n.mentions)} textAnchor="middle">{n.name.slice(0, 22)}</text>
            </g>
          );
        })}
      </svg>
      <div className="row small" style={{ marginTop: 8 }}>
        {Object.entries(TYPE_COLOR).map(([t, c]) => <span key={t} className="row"><span className="dot" style={{ background: c, width: 10, height: 10, borderRadius: 5 }} /> {t}</span>)}
        <span className="muted">· linhas tracejadas = relações inferidas</span>
      </div>
    </Card>
  );
}

function Consolidation() {
  const toast = useToast();
  const { data, reload } = useApi<{ running: boolean; report: Record<string, unknown> }>("/api/brain/consolidate");
  const inferred = useApi<Memory[]>("/api/brain/memories?status=inferred&limit=100");
  const [busy, setBusy] = useState(false);
  async function run() {
    setBusy(true);
    try {
      await api.post("/api/brain/consolidate");
      toast("Consolidação concluída.", "ok");
      void reload(); void inferred.reload();
    } catch (e) { toast((e as Error).message, "error"); } finally { setBusy(false); }
  }
  async function decide(m: Memory, status: string) {
    await api.patch(`/api/brain/memories/${m.id}`, { status });
    void inferred.reload();
  }
  const rep = data?.report ?? {};
  return (
    <div className="grid cols-2">
      <Card title="Consolidação de memórias" actions={<button className="btn primary" disabled={busy || data?.running} onClick={run}>{busy ? "Consolidando…" : "Executar agora"}</button>}>
        <p className="muted small">Resume sessões, extrai decisões, pendências e ideias, encontra duplicatas, contradições e novas conexões. Tudo entra como <strong>inferência</strong> até você confirmar.</p>
        {rep.finished_at ? (
          <ul className="list small">
            <li>Última execução: {fmtDate(String(rep.finished_at))}</li>
            <li>Sessões resumidas: {String(rep.sessions)} · decisões: {String(rep.decisions)} · pendências: {String(rep.pending)} · ideias: {String(rep.ideas)}</li>
            <li>Duplicatas: {(rep.duplicates as unknown[])?.length ?? 0} · contradições: {(rep.contradictions as unknown[])?.length ?? 0} · novas conexões: {String(rep.connections)}</li>
          </ul>
        ) : <Empty>Ainda não executada.</Empty>}
        {((rep.duplicates as { a: number; b: number; similarity: number }[]) ?? []).slice(0, 10).map((d) => (
          <p key={`${d.a}-${d.b}`} className="small">Possível duplicata: #{d.a} ≈ #{d.b} ({Math.round(d.similarity * 100)}%)</p>
        ))}
      </Card>
      <Card title={`Inferências para revisar (${inferred.data?.length ?? 0})`}>
        <ul className="list">
          {(inferred.data ?? []).map((m) => (
            <li key={m.id}>
              <div className="small"><Pill kind="info">{m.kind_label}</Pill> {m.content}</div>
              <div className="row" style={{ marginTop: 6 }}>
                <button className="btn small success" onClick={() => decide(m, "confirmed")}>Confirmar</button>
                <button className="btn small" onClick={() => decide(m, "rejected")}>Rejeitar</button>
              </div>
            </li>
          ))}
        </ul>
        {inferred.data && !inferred.data.length && <Empty>Nada para revisar.</Empty>}
      </Card>
    </div>
  );
}
