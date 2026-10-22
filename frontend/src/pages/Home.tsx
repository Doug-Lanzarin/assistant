import { useMemo, useState } from "react";
import { useToast } from "../components/Toasts";
import { Card, Empty, ErrorBox, Modal, Pill } from "../components/ui";
import { useApi } from "../hooks/useApi";
import { api } from "../services/api";
import type { Action, Device } from "../types/api";

interface HomeStatus { configured: boolean; url: string; devices: number; connection?: { ok: boolean; message: string; entities?: number }; tcl: Record<string, string>; alexa: Record<string, unknown> }

const DOMAIN_LABEL: Record<string, string> = { light: "Luz", switch: "Tomada/interruptor", climate: "Clima", fan: "Ventilador", media_player: "Mídia", cover: "Cortina/portão", lock: "Fechadura", sensor: "Sensor", binary_sensor: "Sensor", scene: "Cena", script: "Script", automation: "Automação", input_boolean: "Chave", vacuum: "Aspirador" };

export function Home({ go }: { go: (p: string) => void }) {
  const toast = useToast();
  const status = useApi<HomeStatus>("/api/home/status");
  const devices = useApi<Device[]>("/api/home/devices");
  const [busy, setBusy] = useState<string | null>(null);
  const [edit, setEdit] = useState<Device | null>(null);

  const byRoom = useMemo(() => {
    const g: Record<string, Device[]> = {};
    for (const d of devices.data ?? []) (g[d.room ?? "Sem cômodo"] ??= []).push(d);
    return Object.entries(g).sort();
  }, [devices.data]);

  async function sync() {
    setBusy("sync");
    try {
      const r = await api.post<Device[]>("/api/home/sync");
      toast(`${r.length} entidades sincronizadas.`, "ok");
      void devices.reload();
      void status.reload();
    } catch (e) { toast((e as Error).message, "error"); } finally { setBusy(null); }
  }

  async function command(tool: string, args: Record<string, unknown>, key: string) {
    setBusy(key);
    try {
      const out = await api.post<Action>("/api/home/command", { tool, args });
      toast(out.message, out.status === "ok" ? "ok" : out.status === "needs_confirmation" ? "info" : "error");
      if (out.status === "needs_confirmation") go("chat");
      void devices.reload();
    } catch (e) { toast((e as Error).message, "error"); } finally { setBusy(null); }
  }

  const st = status.data;
  return (
    <div className="stack" style={{ gap: 16 }}>
      <div className="page-head">
        <h1>Casa inteligente</h1>
        <div className="row">
          <button className="btn primary" disabled={!st?.configured || busy === "sync"} onClick={sync}>{busy === "sync" ? "Sincronizando…" : "Sincronizar dispositivos"}</button>
          <button className="btn" onClick={() => go("settings")}>Configurar integrações</button>
        </div>
      </div>
      <ErrorBox error={status.error} />
      {st && !st.configured && (
        <div className="banner info">Home Assistant não configurado. Informe a URL e o token de longa duração em Configurações → Integrações (guia em docs/HOME_ASSISTANT.md).</div>
      )}
      {st?.connection && (
        <div className="row">
          <Pill kind={st.connection.ok ? "ok" : "bad"}>{st.connection.ok ? `Conectado: ${st.connection.message} (${st.connection.entities} entidades)` : st.connection.message}</Pill>
          {st.tcl?.climate_entity ? <Pill kind="info">Ar TCL: {st.tcl.climate_entity}</Pill> : <Pill>TCL: entidade não definida</Pill>}
          <Pill kind={st.alexa?.enabled ? "info" : ""}>Alexa {st.alexa?.enabled ? "ativa" : "não configurada"}</Pill>
        </div>
      )}
      {byRoom.map(([room, devs]) => (
        <Card key={room} title={room}>
          <div className="grid cols-3">
            {devs.filter((d) => !["automation"].includes(d.domain)).map((d) => (
              <div key={d.entity_id} className="card tight">
                <div className="row between">
                  <strong className="small">{d.name}</strong>
                  <button className="btn ghost small" aria-label={`Editar nomes de ${d.name}`} onClick={() => setEdit(d)}>✎</button>
                </div>
                <div className="muted small">{DOMAIN_LABEL[d.domain] ?? d.domain} · {d.entity_id}</div>
                <div className="row" style={{ marginTop: 8 }}>
                  <Pill kind={d.last_state === "on" || d.last_state === "cool" || d.last_state === "heat" ? "ok" : ""}>{d.last_state ?? "?"}{d.domain === "sensor" && d.attributes.unit_of_measurement ? ` ${String(d.attributes.unit_of_measurement)}` : ""}</Pill>
                  {["light", "switch", "fan", "climate", "media_player", "input_boolean"].includes(d.domain) && (
                    <>
                      <button className="btn small" disabled={busy === d.entity_id} onClick={() => command("home_turn", { target: d.entity_id, on: true }, d.entity_id)}>Ligar</button>
                      <button className="btn small" disabled={busy === d.entity_id} onClick={() => command("home_turn", { target: d.entity_id, on: false }, d.entity_id)}>Desligar</button>
                    </>
                  )}
                  {["scene", "script"].includes(d.domain) && <button className="btn small" onClick={() => command("home_scene", { name: d.name }, d.entity_id)}>Executar</button>}
                  {d.domain === "lock" && <span className="muted small">controle por voz/chat com confirmação</span>}
                </div>
                {d.domain === "climate" && <ClimateControl device={d} onSet={(t) => command("climate_set", { target: d.entity_id, temperature: t }, d.entity_id)} />}
              </div>
            ))}
          </div>
        </Card>
      ))}
      {devices.data && !devices.data.length && st?.configured && <Empty>Nenhum dispositivo em cache. Clique em “Sincronizar dispositivos”.</Empty>}
      <Modal open={!!edit} onClose={() => setEdit(null)} title={`Nomes de ${edit?.name ?? ""}`}>
        {edit && <AliasForm device={edit} onSaved={() => { setEdit(null); void devices.reload(); }} />}
      </Modal>
    </div>
  );
}

function ClimateControl({ device, onSet }: { device: Device; onSet: (t: number) => void }) {
  const a = device.attributes as { temperature?: number; current_temperature?: number; min_temp?: number; max_temp?: number };
  const [t, setT] = useState<number>(a.temperature ?? 23);
  return (
    <div className="row small" style={{ marginTop: 8 }}>
      <span className="muted">ambiente {a.current_temperature ?? "?"} °C</span>
      <label className="inline">
        <span className="sr-only">Temperatura alvo</span>
        <input type="number" min={a.min_temp ?? 16} max={a.max_temp ?? 31} step={0.5} value={t} onChange={(e) => setT(Number(e.target.value))} style={{ width: 80 }} />
      </label>
      <button className="btn small primary" onClick={() => onSet(t)}>Ajustar</button>
    </div>
  );
}

function AliasForm({ device, onSaved }: { device: Device; onSaved: () => void }) {
  const [name, setName] = useState(device.name);
  const [room, setRoom] = useState(device.room ?? "");
  const [aliases, setAliases] = useState(device.aliases.join(", "));
  async function save() {
    await api.patch(`/api/home/devices/${encodeURIComponent(device.entity_id)}`, { name, room, aliases: aliases.split(",").map((x) => x.trim()).filter(Boolean) });
    onSaved();
  }
  return (
    <div className="stack">
      <label>Nome amigável<input value={name} onChange={(e) => setName(e.target.value)} /></label>
      <label>Cômodo<input value={room} onChange={(e) => setRoom(e.target.value)} /></label>
      <label>Apelidos para voz (separados por vírgula)<input value={aliases} onChange={(e) => setAliases(e.target.value)} placeholder="ex.: ar, ar do quarto, tcl" /></label>
      <button className="btn primary" onClick={save}>Salvar</button>
    </div>
  );
}
