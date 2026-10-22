// Voz no navegador: gravação manual (botão) → transcrição LOCAL no backend
// (faster-whisper) e fala via Web Speech API (vozes do Windows) ou Piper.
import { useCallback, useEffect, useRef, useState } from "react";
import { api, auth } from "../services/api";

export type VoiceState = "idle" | "listening" | "transcribing" | "speaking" | "error";

export interface VoiceSettings {
  tts_engine?: string;
  rate?: number;
  volume?: number;
  tts_voice?: string;
  speak_responses?: boolean;
}

export function speechSupported(): boolean {
  return typeof window !== "undefined" && "speechSynthesis" in window;
}

export function useVoice(settings: VoiceSettings | null) {
  const [state, setState] = useState<VoiceState>("idle");
  const [error, setError] = useState<string | null>(null);
  const recRef = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const stopSpeaking = useCallback(() => {
    if (speechSupported()) window.speechSynthesis.cancel();
    audioRef.current?.pause();
    audioRef.current = null;
    setState((s) => (s === "speaking" ? "idle" : s));
  }, []);

  const speak = useCallback(
    async (text: string) => {
      if (!text.trim()) return;
      stopSpeaking();
      const clean = text.replace(/```[\s\S]*?```/g, " ").replace(/\[[^\]]{0,80}\]/g, "").replace(/[•*#>`_]/g, " ").slice(0, 900);
      if (settings?.tts_engine === "piper") {
        try {
          const res = await fetch("/api/voice/tts", {
            method: "POST",
            headers: { "Content-Type": "application/json", Authorization: `Bearer ${auth.token}` },
            body: JSON.stringify({ text: clean }),
          });
          if (!res.ok) throw new Error((await res.json()).detail ?? "falha no TTS");
          const url = URL.createObjectURL(await res.blob());
          const audio = new Audio(url);
          audio.volume = Number(settings?.volume ?? 1);
          audioRef.current = audio;
          setState("speaking");
          audio.onended = () => setState("idle");
          await audio.play();
          return;
        } catch (e) {
          setError(`Piper indisponível (${(e as Error).message}); usando a voz do navegador.`);
        }
      }
      if (!speechSupported()) return;
      const u = new SpeechSynthesisUtterance(clean);
      u.lang = "pt-BR";
      u.rate = Number(settings?.rate ?? 1);
      u.volume = Number(settings?.volume ?? 1);
      const voices = window.speechSynthesis.getVoices();
      const wanted = (settings?.tts_voice ?? "").toLowerCase();
      const v = voices.find((x) => wanted && x.name.toLowerCase().includes(wanted)) ?? voices.find((x) => x.lang?.toLowerCase().startsWith("pt-br"));
      if (v) u.voice = v;
      u.onstart = () => setState("speaking");
      u.onend = () => setState("idle");
      u.onerror = () => setState("idle");
      window.speechSynthesis.speak(u);
    },
    [settings, stopSpeaking],
  );

  const startListening = useCallback(async () => {
    setError(null);
    stopSpeaking();
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      setError("Este navegador não permite gravar áudio. Use o agente local ou digite.");
      setState("error");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { noiseSuppression: true, echoCancellation: true } });
      const rec = new MediaRecorder(stream);
      chunks.current = [];
      rec.ondataavailable = (e) => e.data.size && chunks.current.push(e.data);
      rec.start();
      recRef.current = rec;
      setState("listening");
    } catch (e) {
      setError(`Microfone indisponível: ${(e as Error).message}`);
      setState("error");
    }
  }, [stopSpeaking]);

  const stopListening = useCallback(async (): Promise<string | null> => {
    const rec = recRef.current;
    if (!rec) return null;
    const done = new Promise<void>((r) => (rec.onstop = () => r()));
    rec.stop();
    rec.stream.getTracks().forEach((t) => t.stop());
    await done;
    recRef.current = null;
    setState("transcribing");
    try {
      const blob = new Blob(chunks.current, { type: rec.mimeType || "audio/webm" });
      const form = new FormData();
      form.append("file", blob, "fala.webm");
      const res = await api.upload<{ text: string }>("/api/voice/transcribe", form);
      setState("idle");
      if (!res.text) {
        setError("Não entendi o áudio. Tente de novo, falando mais perto do microfone.");
        return null;
      }
      return res.text;
    } catch (e) {
      setError((e as Error).message);
      setState("error");
      return null;
    }
  }, []);

  useEffect(() => () => stopSpeaking(), [stopSpeaking]);

  return { state, error, speak, stopSpeaking, startListening, stopListening, setError };
}
