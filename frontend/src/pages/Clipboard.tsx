import { useEffect, useState, type FormEvent } from "react";
import { useToast } from "../components/Toasts";
import { Card, Empty, ErrorBox, fmtDate, Modal, Pill } from "../components/ui";
import { useApi } from "../hooks/useApi";
import { api, qs } from "../services/api";
import type { ClipItem } from "../types/api";

interface HistoryRow { id: number; change_type: string; old_title: string; old_content: string; changed_at: string }

export function Clipboard() {
  const toast = useToast();
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");
  const list = useApi<ClipItem[]>(`/api/clipboard${qs({ q: query, category })}`, [query, category]);
  const cats = useApi<{ category: string; n: number }[]>("/api/clipboard/categories");
  const [sel, setSel] = useState<ClipItem | null>(null);
  const [adding, setAdding] = useState(false);

  async function openItem(id: number) {
    setSel(await api.get<ClipItem>(`/api/clipboard/${id}`));
  }
  function refresh() {
    void list.reload();
    void cats.reload();
  }
  async function copy(item: ClipItem) {
    try {
      await api.post(`/api/clipboard/${item.id}/copy`);
      toast(`“${item.title}” está no clipboard do Windows. Cole com Ctrl+V.`, "ok");
      refresh();
    } catch (e) {
      toast((e as Error).message, "error");
    }
  }
  async function saveCurrent() {
    try {
      const r = await api.post<{ item: ClipItem; duplicate: boolean }>("/api/clipboard/save-current", {});
      toast(r.duplicate ? `Já estava salvo como “${r.item.title}”.` : `Salvo como “${r.item.title}”.`, "ok");
      refresh();
      void openItem(r.item.id);
    } catch (e) {
      toast((e as Error).message, "error");
    }
  }
  async function exportAll() {
    const data = await api.get("/api/clipboard/export");
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `jarvis-clipboard-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }
  async function importFile(files: FileList | null) {
    if (!files?.[0]) return;
    try {
      const payload = JSON.parse(await files[0].text());
      const r = await api.post<{ created: number; skipped: number }>("/api/clipboard/import", payload);
      toast(`Importados: ${r.created} · ignorados (duplicados/inválidos): ${r.skipped}`, "ok");
      refresh();
    } catch (e) {
      toast(`Importação falhou: ${(e as Error).message}`, "error");
    }
  }

  return (
    <div>
      <div className="page-head">
        <h1>Área de transferência</h1>
        <div className="row">
          <button className="btn primary" onClick={saveCurrent} title="Lê o Ctrl+C atual pelo agente local">Salvar o que copiei</button>
          <button className="btn" onClick={() => setAdding(true)}>Novo manual</button>
          <button className="btn" onClick={exportAll}>Exportar</button>
          <label className="btn" style={{ display: "inline-flex" }}>
            Importar<input type="file" accept="application/json" className="sr-only" onChange={(e) => void importFile(e.target.files)} />
          </label>
        </div>
      </div>
      <div className="split">
        <div className="stack">
          <form className="row" role="search" onSubmit={(e) => { e.preventDefault(); setQuery(q); }}>
            <input aria-label="Pesquisar registros" placeholder="ex.: consulta SQL de coletas" value={q} onChange={(e) => setQ(e.target.value)} style={{ flex: 1 }} />
            <button className="btn">Buscar</button>
          </form>
          <div className="row">
            <button className={`btn small ${!category ? "primary" : ""}`} onClick={() => setCategory("")}>todas</button>
            {(cats.data ?? []).map((c) => (
              <button key={c.category} className={`btn small ${category === c.category ? "primary" : ""}`} onClick={() => setCategory(c.category)}>
                {c.category} ({c.n})
              </button>
            ))}
          </div>
          <ErrorBox error={list.error} onRetry={list.reload} />
          <ul className="list">
            {(list.data ?? []).map((it) => (
              <li key={it.id} className={sel?.id === it.id ? "active" : ""}>
                <button className="item" onClick={() => void openItem(it.id)}>
                  <div className="row between">
                    <strong className="small">{it.pinned ? "📌 " : ""}{it.title}</strong>
                    <span className="pill">{it.category}</span>
                  </div>
                  <div className="muted small" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{it.preview}</div>
                </button>
                <div className="row" style={{ marginTop: 6 }}>
                  <button className="btn small success" onClick={() => void copy(it)}>Copiar</button>
                  {it.project_name && <span className="muted small">{it.project_name}</span>}
                </div>
              </li>
            ))}
          </ul>
          {list.data && !list.data.length && <Empty>Nenhum registro. Copie algo e diga “Jarvis, salve o que copiei”.</Empty>}
        </div>
        <div>{sel ? <ItemDetail key={sel.id} item={sel} onChanged={(it) => { setSel(it); refresh(); }} onDeleted={() => { setSel(null); refresh(); }} onCopy={copy} /> : <Empty>Selecione um registro para ver o conteúdo.</Empty>}</div>
      </div>
      <Modal open={adding} onClose={() => setAdding(false)} title="Novo registro">
        <NewItem onSaved={(it) => { setAdding(false); refresh(); void openItem(it.id); }} />
      </Modal>
    </div>
  );
}

function NewItem({ onSaved }: { onSaved: (it: ClipItem) => void }) {
  const toast = useToast();
  const [content, setContent] = useState("");
  const [title, setTitle] = useState("");
  const [category, setCategory] = useState("");
  const [project, setProject] = useState("");
  async function save(e: FormEvent) {
    e.preventDefault();
    try {
      const r = await api.post<{ item: ClipItem }>("/api/clipboard", { content, title: title || null, category: category || null, project: project || null });
      onSaved(r.item);
    } catch (err) {
      toast((err as Error).message, "error");
    }
  }
  return (
    <form className="stack" onSubmit={save}>
      <label>Título<input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="sugerido automaticamente se vazio" /></label>
      <label>Conteúdo<textarea className="mono" rows={10} value={content} onChange={(e) => setContent(e.target.value)} required /></label>
      <div className="row">
        <label style={{ flex: 1 }}>Categoria<input value={category} onChange={(e) => setCategory(e.target.value)} placeholder="detectada automaticamente" /></label>
        <label style={{ flex: 1 }}>Projeto<input value={project} onChange={(e) => setProject(e.target.value)} /></label>
      </div>
      <button className="btn primary">Salvar</button>
    </form>
  );
}

function ItemDetail({ item, onChanged, onDeleted, onCopy }: { item: ClipItem; onChanged: (it: ClipItem) => void; onDeleted: () => void; onCopy: (it: ClipItem) => void }) {
  const toast = useToast();
  const [title, setTitle] = useState(item.title);
  const [category, setCategory] = useState(item.category);
  const [project, setProject] = useState(item.project_name ?? "");
  const [tags, setTags] = useState(item.tags.join(", "));
  const [content, setContent] = useState(item.content ?? "");
  const [history, setHistory] = useState<HistoryRow[]>([]);
  const [reveal, setReveal] = useState(!item.sensitive);

  useEffect(() => {
    api.get<HistoryRow[]>(`/api/clipboard/${item.id}/history`).then(setHistory).catch(() => {});
  }, [item.id]);

  async function save() {
    try {
      const body: Record<string, unknown> = { title, category, project, tags: tags.split(",").map((t) => t.trim()).filter(Boolean) };
      if (content !== item.content) body.content = content;
      await api.patch(`/api/clipboard/${item.id}`, body);
      toast("Registro atualizado.", "ok");
      onChanged(await api.get<ClipItem>(`/api/clipboard/${item.id}`));
    } catch (e) {
      toast((e as Error).message, "error");
    }
  }
  async function pin() {
    await api.patch(`/api/clipboard/${item.id}`, { pinned: !item.pinned });
    onChanged(await api.get<ClipItem>(`/api/clipboard/${item.id}`));
  }
  async function replaceWithClipboard() {
    if (!confirm(`Substituir o conteúdo de “${item.title}” pelo que está no clipboard agora? A versão atual fica no histórico.`)) return;
    try {
      await api.post(`/api/clipboard/${item.id}/update-from-clipboard`);
      onChanged(await api.get<ClipItem>(`/api/clipboard/${item.id}`));
      toast("Conteúdo substituído.", "ok");
    } catch (e) {
      toast((e as Error).message, "error");
    }
  }
  async function remove() {
    if (!confirm(`Apagar definitivamente “${item.title}”?`)) return;
    await api.del(`/api/clipboard/${item.id}`);
    toast("Registro apagado.", "ok");
    onDeleted();
  }

  return (
    <Card title={item.title} actions={<>
      <button className="btn success" onClick={() => onCopy(item)}>Copiar</button>
      <button className="btn" onClick={pin}>{item.pinned ? "Desafixar" : "Fixar"}</button>
    </>}>
      <div className="row small muted" style={{ marginBottom: 10 }}>
        <span>{item.char_count} caracteres</span>·<span>criado {fmtDate(item.created_at)}</span>·<span>copiado {item.copy_count}x</span>
        {item.sensitive && <Pill kind="warn">sensível · cifrado · não enviado à IA</Pill>}
      </div>
      <div className="stack">
        <div className="row">
          <label style={{ flex: 2 }}>Título<input value={title} onChange={(e) => setTitle(e.target.value)} /></label>
          <label style={{ flex: 1 }}>Categoria<input value={category} onChange={(e) => setCategory(e.target.value)} /></label>
          <label style={{ flex: 1 }}>Projeto<input value={project} onChange={(e) => setProject(e.target.value)} /></label>
        </div>
        <label>Etiquetas<input value={tags} onChange={(e) => setTags(e.target.value)} /></label>
        {reveal ? (
          <label>Conteúdo<textarea className="mono" rows={14} value={content} onChange={(e) => setContent(e.target.value)} spellCheck={false} /></label>
        ) : (
          <button className="btn" onClick={() => setReveal(true)}>Mostrar conteúdo sensível</button>
        )}
        <div className="row">
          <button className="btn primary" onClick={save}>Salvar alterações</button>
          <button className="btn" onClick={replaceWithClipboard}>Substituir pelo clipboard atual</button>
          <button className="btn danger" onClick={remove}>Apagar</button>
        </div>
        {!!history.length && (
          <details>
            <summary className="small">Histórico de alterações ({history.length})</summary>
            <ul className="list small" style={{ marginTop: 8 }}>
              {history.map((h) => (
                <li key={h.id}>
                  <div className="muted">{fmtDate(h.changed_at)} · {h.change_type === "title" ? `título anterior: ${h.old_title}` : "conteúdo anterior"}</div>
                  {h.change_type === "content" && <pre>{h.old_content?.slice(0, 600)}</pre>}
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>
    </Card>
  );
}
