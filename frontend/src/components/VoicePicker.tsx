// Escolha da voz de resposta: ouvir uma amostra, baixar vozes oficiais do Piper
// e escolher entre as vozes locais (Piper) e as do navegador.
import { useEffect, useRef, useState } from "react";
import { api, auth } from "../services/api";
import { useApi } from "../hooks/useApi";
import { useToast } from "./Toasts";
import { Pill } from "./ui";

const SAMPLE = "Boa noite! Agora são vinte e uma horas e trinta minutos. Desliguei as luzes da sala. Quer que eu faça mais alguma coisa?";

interface PiperVoiceInfo { name: string; label: string; about: string; installed: boolean; current: boolean }

/** Vozes neurais "Natural" do Microsoft Edge: muito mais naturais, mas processadas online pela Microsoft. */
export function isOnlineNatural(v: SpeechSynthesisVoice): boolean {
  return /natural|online/i.test(v.name) || v.localService === false;
}

export function VoicePicker({ values, onSaved }: { values: Record<string, unknown>; onSaved: () => void }) {
  const toast = useToast();
  const catalog = useApi<PiperVoiceInfo[]>("/api/voice/piper/catalog");
  const [browserVoices, setBrowserVoices] = useState<SpeechSynthesisVoice[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const audio = useRef<HTMLAudioElement | null>(null);
  const engine = String(values.tts_engine ?? "auto");
  const chosen = String(values.tts_voice ?? "");

  useEffect(() => {
    if (!("speechSynthesis" in window)) return;
    const load = () => setBrowserVoices(window.speechSynthesis.getVoices().filter((v) => v.lang.toLowerCase().startsWith("pt")));
    load();
    window.speechSynthesis.addEventListener?.("voiceschanged", load);
    return () => window.speechSynthesis.removeEventListener?.("voiceschanged", load);
  }, []);

  function stop() {
    audio.current?.pause();
    audio.current = null;
    if ("speechSynthesis" in window) window.speechSynthesis.cancel();
  }

  async function previewPiper(name: string) {
    stop();
    setBusy(`ouvir:${name}`);
    try {
      const res = await fetch("/api/voice/tts", {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${auth.token}` },
        body: JSON.stringify({ text: SAMPLE, voice: name }),
      });
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `HTTP ${res.status}`);
      const url = URL.createObjectURL(await res.blob());
      const a = new Audio(url);
      a.onended = () => URL.revokeObjectURL(url);
      audio.current = a;
      await a.play();
    } catch (e) {
      toast(`Não foi possível tocar a amostra: ${(e as Error).message}`, "error");
    } finally {
      setBusy(null);
    }
  }

  function previewBrowser(v: SpeechSynthesisVoice) {
    stop();
    const u = new SpeechSynthesisUtterance(SAMPLE);
    u.voice = v;
    u.lang = v.lang;
    window.speechSynthesis.speak(u);
  }

  async function download(name: string) {
    setBusy(`baixar:${name}`);
    try {
      await api.post("/api/voice/piper/download", { name }, 300_000);
      toast("Voz baixada.", "ok");
      catalog.reload();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(null);
    }
  }

  async function use(engineName: string, voice: string) {
    await api.patch("/api/settings/voice", { tts_engine: engineName, tts_voice: voice });
    toast("Voz de resposta alterada.", "ok");
    onSaved();
    catalog.reload();
  }

  const piperActive = engine === "auto" || engine === "piper";
  return (
    <div className="stack voice-picker">
      <p className="muted small">Ouça as amostras e escolha a voz das respostas. As vozes Piper rodam no seu PC (privadas e offline).</p>
      <ul className="list">
        {(catalog.data ?? []).map((v) => (
          <li key={v.name} className="voice-row">
            <div>
              <strong>{v.label}</strong> <span className="muted small">Piper · {v.about}</span>
              {v.current && piperActive && <> <Pill kind="ok">em uso</Pill></>}
            </div>
            <div className="row">
              {v.installed ? (
                <>
                  <button className="btn small" disabled={busy !== null} onClick={() => previewPiper(v.name)}>
                    {busy === `ouvir:${v.name}` ? "Gerando…" : "Ouvir"}
                  </button>
                  <button className="btn small primary" disabled={v.current && piperActive} onClick={() => use("auto", v.name)}>Usar</button>
                </>
              ) : (
                <button className="btn small" disabled={busy !== null} onClick={() => download(v.name)}>
                  {busy === `baixar:${v.name}` ? "Baixando (~63 MB)…" : "Baixar (~63 MB)"}
                </button>
              )}
            </div>
          </li>
        ))}
        {browserVoices.map((v) => {
          const online = isOnlineNatural(v);
          const inUse = engine === "browser" && chosen && v.name.toLowerCase().includes(chosen.toLowerCase());
          return (
            <li key={v.name} className="voice-row">
              <div>
                <strong>{v.name.replace(/^Microsoft\s+/, "").replace(/\s*-\s*Portuguese.*$/i, "")}</strong>{" "}
                <span className="muted small">navegador · {online ? "neural online (Microsoft): o texto da resposta é enviado à Microsoft" : "voz do Windows, local"}</span>
                {inUse && <> <Pill kind="ok">em uso</Pill></>}
              </div>
              <div className="row">
                <button className="btn small" onClick={() => previewBrowser(v)}>Ouvir</button>
                <button className="btn small primary" disabled={Boolean(inUse)} onClick={() => use("browser", v.name)}>Usar</button>
              </div>
            </li>
          );
        })}
      </ul>
      {!browserVoices.some(isOnlineNatural) && (
        <p className="muted small">
          Quer uma voz ainda mais natural? Abra o JARVIS no <strong>Microsoft Edge</strong>: ele oferece as vozes neurais
          "Francisca" e "Antonio" (Natural), que aparecem nesta lista. Elas funcionam online pela Microsoft.
        </p>
      )}
      <div className="row"><button className="btn small" onClick={stop}>Parar amostra</button></div>
    </div>
  );
}
