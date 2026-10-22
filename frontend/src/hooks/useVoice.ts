// Voz no navegador: gravação → transcrição LOCAL no backend (faster-whisper) e
// fala via Piper (backend) ou Web Speech API. Expõe medidores de áudio REAIS
// para o orb: microfone durante a escuta e o áudio do TTS durante a fala.
import { useCallback, useEffect, useRef, useState } from "react";
import { AudioMeter, silentFrame, unlockAudio, WordEnvelope, type AudioFrame } from "../orb/audio";
import { api, auth } from "../services/api";

export type VoiceState = "idle" | "listening" | "transcribing" | "speaking" | "error";

export interface VoiceSettings {
  tts_engine?: string; // auto | piper | browser | sapi
  rate?: number;
  volume?: number;
  tts_voice?: string;
  speak_responses?: boolean;
}

export interface ListenOptions {
  /** Encerra sozinho após silêncio e entrega o texto transcrito. */
  onUtterance?: (text: string | null) => void;
  maxSeconds?: number;
}

/** Eventos funcionais reais da voz (alimentam a máquina de estados do orb). */
export type VoiceEvent =
  | { type: "mic_started" }
  | { type: "mic_stopped" }
  | { type: "transcribing" }
  | { type: "transcribed"; text: string | null }
  | { type: "tts_started"; engine: "piper" | "browser" }
  | { type: "tts_ended" }
  | { type: "error"; reason: string };

export function speechSupported(): boolean {
  return typeof window !== "undefined" && "speechSynthesis" in window;
}

const VAD_SPEECH = 0.42; // nível (0..1) considerado fala
const VAD_SILENCE = 0.28;
const SILENCE_MS = 1100;

export function useVoice(settings: VoiceSettings | null, onEvent?: (e: VoiceEvent) => void) {
  const [state, setState] = useState<VoiceState>("idle");
  const [error, setErrorState] = useState<string | null>(null);
  const eventRef = useRef(onEvent);
  eventRef.current = onEvent;
  const emit = useCallback((e: VoiceEvent) => eventRef.current?.(e), []);
  /** Registra o erro na tela e emite o evento de falha. */
  const setError = useCallback((msg: string | null) => {
    setErrorState(msg);
    if (msg) eventRef.current?.({ type: "error", reason: msg });
  }, []);
  const [ttsSource, setTtsSource] = useState<"piper" | "browser" | null>(null);
  const recRef = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const micMeter = useRef<AudioMeter | null>(null);
  const ttsMeter = useRef<AudioMeter | null>(null);
  const words = useRef(new WordEnvelope());
  const vadTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  const piperBroken = useRef(false);
  const stateRef = useRef<VoiceState>("idle");
  stateRef.current = state;

  /** Quadro de áudio real do momento (microfone ou TTS). */
  const readAudio = useCallback((): AudioFrame => {
    if (stateRef.current === "listening" && micMeter.current) return micMeter.current.read();
    if (stateRef.current === "speaking") {
      if (ttsMeter.current) return ttsMeter.current.read();
      return words.current.read();
    }
    return silentFrame();
  }, []);

  const cleanupTts = useCallback(() => {
    ttsMeter.current?.disconnect();
    ttsMeter.current = null;
    words.current.stop();
  }, []);

  const stopSpeaking = useCallback(() => {
    const wasSpeaking = stateRef.current === "speaking";
    if (speechSupported()) window.speechSynthesis.cancel();
    audioRef.current?.pause();
    audioRef.current = null;
    cleanupTts();
    setState((s) => (s === "speaking" ? "idle" : s));
    if (wasSpeaking) emit({ type: "tts_ended" });
  }, [cleanupTts, emit]);

  const speakBrowser = useCallback(
    (clean: string) =>
      new Promise<void>((resolve) => {
        if (!speechSupported()) return resolve();
        const u = new SpeechSynthesisUtterance(clean);
        u.lang = "pt-BR";
        u.rate = Number(settings?.rate ?? 1);
        u.volume = Number(settings?.volume ?? 1);
        const voices = window.speechSynthesis.getVoices();
        const wanted = (settings?.tts_voice ?? "").toLowerCase();
        const v = voices.find((x) => wanted && x.name.toLowerCase().includes(wanted)) ?? voices.find((x) => x.lang?.toLowerCase().startsWith("pt-br"));
        if (v) u.voice = v;
        u.onstart = () => {
          words.current.start();
          setTtsSource("browser");
          stateRef.current = "speaking";
          setState("speaking");
          emit({ type: "tts_started", engine: "browser" });
        };
        u.onboundary = () => words.current.word();
        let finished = false;
        const done = (failed?: string) => {
          if (finished) return;
          finished = true;
          words.current.stop();
          const was = stateRef.current === "speaking";
          stateRef.current = "idle";
          setState((s) => (s === "speaking" ? "idle" : s));
          if (failed) setError(failed);
          else if (was) emit({ type: "tts_ended" });
          resolve();
        };
        u.onend = () => done();
        u.onerror = (ev) => {
          const err = (ev as SpeechSynthesisErrorEvent).error;
          done(err === "interrupted" || err === "canceled" ? undefined : `Falha na síntese de voz (${err ?? "desconhecida"}).`);
        };
        window.speechSynthesis.speak(u);
      }),
    [settings, emit, setError],
  );

  const speak = useCallback(
    async (text: string): Promise<void> => {
      if (!text.trim()) return;
      stopSpeaking();
      const clean = text.replace(/```[\s\S]*?```/g, " ").replace(/\[[^\]]{0,80}\]/g, "").replace(/[•*#>`_]/g, " ").slice(0, 900);
      const engine = settings?.tts_engine ?? "auto";
      const tryPiper = engine === "piper" || ((engine === "auto" || engine === "sapi") && !piperBroken.current);
      if (tryPiper) {
        try {
          const res = await fetch("/api/voice/tts", {
            method: "POST",
            headers: { "Content-Type": "application/json", Authorization: `Bearer ${auth.token}` },
            body: JSON.stringify({ text: clean }),
          });
          if (!res.ok) {
            if (res.status === 501) piperBroken.current = true;
            throw new Error((await res.json().catch(() => ({}))).detail ?? `HTTP ${res.status}`);
          }
          const url = URL.createObjectURL(await res.blob());
          const audio = new Audio(url);
          audio.volume = Number(settings?.volume ?? 1);
          audioRef.current = audio;
          await unlockAudio();
          ttsMeter.current = AudioMeter.fromElement(audio);
          setTtsSource("piper");
          await new Promise<void>((resolve) => {
            let finished = false;
            const done = (failed?: string) => {
              if (finished) return;
              finished = true;
              URL.revokeObjectURL(url);
              cleanupTts();
              const was = stateRef.current === "speaking";
              stateRef.current = "idle";
              setState((s) => (s === "speaking" ? "idle" : s));
              if (failed) setError(failed);
              else if (was) emit({ type: "tts_ended" });
              resolve();
            };
            // "playing" = o áudio REALMENTE começou a tocar → SPEAKING
            audio.onplaying = () => {
              if (stateRef.current === "speaking") return;
              stateRef.current = "speaking";
              setState("speaking");
              emit({ type: "tts_started", engine: "piper" });
            };
            audio.onended = () => done();
            audio.onpause = () => done();
            audio.onerror = () => done("Falha ao reproduzir o áudio da resposta.");
            audio.play().catch((err: Error) => done(`O navegador bloqueou a reprodução do áudio (${err.name}).`));
          });
          return;
        } catch (e) {
          if (engine === "piper") setErrorState(`Piper indisponível (${(e as Error).message}); usando a voz do navegador.`);
        }
      }
      await speakBrowser(clean);
    },
    [settings, stopSpeaking, speakBrowser, cleanupTts, emit, setError],
  );

  const stopListening = useCallback(async (deferIdle = false): Promise<string | null> => {
    if (vadTimer.current) clearInterval(vadTimer.current);
    vadTimer.current = null;
    const rec = recRef.current;
    if (!rec) return null;
    const done = new Promise<void>((r) => (rec.onstop = () => r()));
    rec.stop();
    rec.stream.getTracks().forEach((t) => t.stop());
    await done;
    recRef.current = null;
    micMeter.current?.disconnect();
    micMeter.current = null;
    stateRef.current = "transcribing";
    setState("transcribing");
    emit({ type: "transcribing" });
    try {
      const blob = new Blob(chunks.current, { type: rec.mimeType || "audio/webm" });
      const form = new FormData();
      form.append("file", blob, "fala.webm");
      const res = await api.upload<{ text: string }>("/api/voice/transcribe", form);
      // deferIdle: quem chamou segue para "processando" sem passar por "repouso".
      if (!deferIdle) setState("idle");
      if (!res.text) {
        setError("Não entendi o áudio. Tente de novo, falando mais perto do microfone.");
        return null;
      }
      emit({ type: "transcribed", text: res.text });
      return res.text;
    } catch (e) {
      setError(`Falha na transcrição: ${(e as Error).message}`);
      setState("error");
      return null;
    }
  }, [emit, setError]);

  const startListening = useCallback(
    async (opts: ListenOptions = {}) => {
      setErrorState(null);
      stopSpeaking();
      await unlockAudio();
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
        rec.start(250);
        recRef.current = rec;
        micMeter.current = AudioMeter.fromStream(stream);
        stateRef.current = "listening";
        setState("listening");
        // o microfone está realmente captando → LISTENING
        emit({ type: "mic_started" });
        if (opts.onUtterance && micMeter.current) {
          // Detecção de fim de fala pela energia real do microfone.
          const started = performance.now();
          let heard = false;
          let quietSince = 0;
          vadTimer.current = setInterval(() => {
            const lvl = micMeter.current?.read().level ?? 0;
            const now = performance.now();
            if (lvl > VAD_SPEECH) {
              heard = true;
              quietSince = 0;
            } else if (heard && lvl < VAD_SILENCE) {
              quietSince ||= now;
            }
            const tooLong = now - started > (opts.maxSeconds ?? 15) * 1000;
            const noSpeech = !heard && now - started > 6000;
            if ((heard && quietSince && now - quietSince > SILENCE_MS) || tooLong || noSpeech) {
              if (vadTimer.current) clearInterval(vadTimer.current);
              vadTimer.current = null;
              if (noSpeech && !tooLong) {
                // nada foi dito: encerra sem transcrever
                rec.onstop = null;
                rec.stop();
                stream.getTracks().forEach((t) => t.stop());
                recRef.current = null;
                micMeter.current?.disconnect();
                micMeter.current = null;
                stateRef.current = "idle";
                setState("idle");
                emit({ type: "mic_stopped" });
                opts.onUtterance?.(null);
                return;
              }
              void stopListening(true).then((t) => {
                opts.onUtterance?.(t);
                setState((st) => (st === "transcribing" ? "idle" : st));
              });
            }
          }, 50);
        }
      } catch (e) {
        setError(`Microfone indisponível: ${(e as Error).message}`);
        setState("error");
      }
    },
    [stopSpeaking, stopListening, emit, setError],
  );

  const cancelListening = useCallback(() => {
    if (vadTimer.current) clearInterval(vadTimer.current);
    vadTimer.current = null;
    const rec = recRef.current;
    if (rec) {
      rec.onstop = null;
      rec.stop();
      rec.stream.getTracks().forEach((t) => t.stop());
    }
    recRef.current = null;
    micMeter.current?.disconnect();
    micMeter.current = null;
    const was = stateRef.current === "listening";
    setState((s) => (s === "listening" ? "idle" : s));
    if (was) emit({ type: "mic_stopped" });
  }, [emit]);

  useEffect(() => () => {
    stopSpeaking();
    cancelListening();
  }, [stopSpeaking, cancelListening]);

  const markIdle = useCallback(() => setState((st) => (st === "transcribing" ? "idle" : st)), []);

  return { state, error, ttsSource, speak, stopSpeaking, startListening, stopListening, cancelListening, markIdle, setError, readAudio };
}
