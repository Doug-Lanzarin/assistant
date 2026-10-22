"""Voz local no agente: microfone, palavra de ativação, transcrição e fala.

Dependências opcionais (requirements-voice.txt): sounddevice, numpy,
openwakeword, faster-whisper, pyttsx3 (SAPI no Windows) e/ou piper-tts.

Privacidade:
* o áudio do microfone é processado em memória, localmente;
* nada é enviado à nuvem e nada é gravado em disco;
* a escuta da palavra de ativação só roda quando habilitada (indicador na
  bandeja e no painel).

Sobre a palavra "Jarvis": o openWakeWord traz um modelo pré-treinado
``hey_jarvis`` (diga "Hey Jarvis"). Para ativar com "Jarvis" sozinho é preciso
treinar um modelo próprio (docs/VOZ.md); enquanto isso use "Hey Jarvis", o
atalho de teclado ou o botão do painel.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable
from typing import Any

log = logging.getLogger("jarvis_agent.voice")

SAMPLE_RATE = 16000
FRAME = 1280  # 80 ms, tamanho esperado pelo openWakeWord


def load_wake_model(name: str):
    """Carrega o modelo do openWakeWord nas APIs 0.4 (wheels com modelos) e 0.6+ (download)."""
    import inspect
    import os

    import openwakeword
    from openwakeword.model import Model

    params = inspect.signature(Model.__init__).parameters
    if "wakeword_models" in params:
        try:
            openwakeword.utils.download_models([name])
        except Exception:  # noqa: BLE001 - modelo pode já estar em cache
            pass
        return Model(wakeword_models=[name], inference_framework="onnx")
    paths = [p for p in openwakeword.get_pretrained_model_paths() if os.path.basename(p).startswith(name)]
    if not paths:
        raise RuntimeError(f"Modelo de ativação '{name}' não encontrado")
    return Model(wakeword_model_paths=paths)


def _try_import(name: str):
    try:
        return __import__(name)
    except Exception:  # noqa: BLE001 - dependência opcional
        return None


class VoiceEngine:
    def __init__(self, emit: Callable[[str, dict], None], models_dir: str | None = None):
        self.emit = emit
        self.models_dir = models_dir
        self.sd = _try_import("sounddevice")
        self.np = _try_import("numpy")
        self.settings: dict[str, Any] = {"wake_word_enabled": False, "wake_model": "hey_jarvis", "wake_threshold": 0.5,
                                         "stt_model": "base", "stt_language": "pt", "stt_prompt": "", "tts_engine": "sapi", "rate": 1.0,
                                         "volume": 1.0, "input_device": None, "output_device": None, "tts_voice": ""}
        self._wake_thread: threading.Thread | None = None
        self._stop_wake = threading.Event()
        self._speaking = threading.Event()
        self._tts_lock = threading.Lock()
        self._tts_engine = None
        self._whisper = None
        self._oww = None
        self.state = "idle"
        self._speak_q: queue.Queue[str | None] = queue.Queue()
        threading.Thread(target=self._speak_worker, daemon=True, name="tts").start()

    # -- capacidades -------------------------------------------------------------------
    def capabilities(self) -> dict[str, bool]:
        return {
            "microphone": bool(self.sd and self.np),
            "wake_word": bool(_try_import("openwakeword")) and bool(self.sd),
            "stt": bool(_try_import("faster_whisper")),
            "tts_sapi": bool(_try_import("pyttsx3")),
            "tts_piper": bool(_try_import("piper")) and bool(self.sd),
        }

    def available(self) -> bool:
        caps = self.capabilities()
        return caps["microphone"] and caps["stt"]

    def set_state(self, state: str, **extra: Any) -> None:
        self.state = state
        self.emit("voice.state", {"state": state, **extra})

    def devices(self) -> dict[str, Any]:
        if not self.sd:
            return {"inputs": [], "outputs": [], "error": "sounddevice não instalado"}
        devs = self.sd.query_devices()
        inputs = [{"index": i, "name": d["name"]} for i, d in enumerate(devs) if d["max_input_channels"] > 0]
        outputs = [{"index": i, "name": d["name"]} for i, d in enumerate(devs) if d["max_output_channels"] > 0]
        return {"inputs": inputs, "outputs": outputs, "default": list(self.sd.default.device)}

    def configure(self, settings: dict[str, Any]) -> dict[str, Any]:
        self.settings.update({k: v for k, v in settings.items() if k in self.settings or k in {"enabled"}})
        if self.settings.get("wake_word_enabled") and settings.get("enabled", True):
            self.start_wake()
        else:
            self.stop_wake()
        return {"ok": True, "wake_running": bool(self._wake_thread and self._wake_thread.is_alive())}

    # -- STT ---------------------------------------------------------------------------
    def _whisper_model(self):
        if self._whisper is None:
            from faster_whisper import WhisperModel

            self._whisper = WhisperModel(self.settings["stt_model"], device="cpu", compute_type="int8",
                                         download_root=self.models_dir)
        return self._whisper

    def transcribe(self, audio) -> str:
        model = self._whisper_model()
        segments, _ = model.transcribe(audio, language=self.settings["stt_language"], vad_filter=True, beam_size=1,
                                       condition_on_previous_text=False,
                                       initial_prompt=self.settings.get("stt_prompt") or None, hotwords="Jarvis")
        return " ".join(s.text.strip() for s in segments).strip()

    def record_utterance(self, max_seconds: float = 12.0, silence_s: float = 0.9, start_timeout: float = 5.0):
        """Grava até detectar silêncio após a fala (VAD simples por energia)."""
        np, sd = self.np, self.sd
        frames: list = []
        started = False
        silent_for = 0.0
        t0 = time.monotonic()
        noise = None
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16", blocksize=FRAME,
                            device=self.settings.get("input_device")) as stream:
            while time.monotonic() - t0 < max_seconds:
                block, _ = stream.read(FRAME)
                block = block[:, 0]
                rms = float(np.sqrt(np.mean(block.astype(np.float32) ** 2)))
                if noise is None:
                    noise = max(rms, 150.0)
                threshold = max(noise * 2.5, 400.0)
                if rms > threshold:
                    started = True
                    silent_for = 0.0
                elif started:
                    silent_for += FRAME / SAMPLE_RATE
                else:
                    noise = 0.95 * noise + 0.05 * rms
                    if time.monotonic() - t0 > start_timeout:
                        break
                if started:
                    frames.append(block.copy())
                    if silent_for >= silence_s:
                        break
        if not frames:
            return None
        return np.concatenate(frames).astype(np.float32) / 32768.0

    def listen_once(self) -> dict[str, Any]:
        if not self.available():
            return {"ok": False, "error": "Voz local indisponível (instale requirements-voice.txt)"}
        self.stop_speaking()
        self.set_state("listening")
        try:
            audio = self.record_utterance()
            if audio is None:
                self.set_state("idle")
                return {"ok": False, "error": "Não ouvi nada."}
            self.set_state("transcribing")
            t0 = time.perf_counter()
            text = self.transcribe(audio)
            ms = int((time.perf_counter() - t0) * 1000)
        except Exception as e:  # noqa: BLE001
            log.exception("Falha na escuta")
            self.set_state("error", error=str(e))
            return {"ok": False, "error": str(e)}
        self.set_state("idle")
        if not text:
            return {"ok": False, "error": "Não entendi o que foi dito."}
        self.emit("voice.command", {"text": text, "stt_ms": ms})
        return {"ok": True, "text": text, "stt_ms": ms}

    # -- palavra de ativação --------------------------------------------------------------
    def start_wake(self) -> None:
        if self._wake_thread and self._wake_thread.is_alive():
            return
        if not self.capabilities()["wake_word"]:
            self.set_state("error", error="openWakeWord/sounddevice não instalados")
            return
        self._stop_wake.clear()
        self._wake_thread = threading.Thread(target=self._wake_loop, daemon=True, name="wakeword")
        self._wake_thread.start()

    def stop_wake(self) -> None:
        self._stop_wake.set()

    def _wake_loop(self) -> None:
        np, sd = self.np, self.sd
        try:
            if self._oww is None:
                self._oww = load_wake_model(self.settings["wake_model"])
        except Exception as e:  # noqa: BLE001
            log.exception("Falha ao carregar modelo de ativação")
            self.set_state("error", error=f"modelo de ativação: {e}")
            return
        self.set_state("listening_wake")
        threshold = float(self.settings.get("wake_threshold", 0.5))
        cooldown_until = 0.0
        try:
            with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16", blocksize=FRAME,
                                device=self.settings.get("input_device")) as stream:
                while not self._stop_wake.is_set():
                    block, _ = stream.read(FRAME)
                    if self._speaking.is_set() or time.monotonic() < cooldown_until:
                        continue
                    scores = self._oww.predict(block[:, 0].astype(np.int16))
                    if max(scores.values()) >= threshold:
                        self.emit("voice.wake", {"score": round(float(max(scores.values())), 3)})
                        stream.stop()
                        self.listen_once()
                        self._oww.reset()
                        cooldown_until = time.monotonic() + 1.0
                        stream.start()
                        self.set_state("listening_wake")
        except Exception as e:  # noqa: BLE001
            log.exception("Laço de ativação falhou")
            self.set_state("error", error=str(e))
            return
        self.set_state("idle")

    # -- TTS ---------------------------------------------------------------------------
    def speak(self, text: str) -> dict[str, Any]:
        if not text.strip():
            return {"ok": False}
        self._speak_q.put(text)
        return {"ok": True, "queued": True}

    def stop_speaking(self) -> dict[str, Any]:
        while not self._speak_q.empty():
            try:
                self._speak_q.get_nowait()
            except queue.Empty:
                break
        if self._tts_engine is not None:
            try:
                self._tts_engine.stop()
            except Exception:  # noqa: BLE001
                pass
        if self.sd:
            try:
                self.sd.stop()
            except Exception:  # noqa: BLE001
                pass
        self._speaking.clear()
        return {"ok": True}

    def _speak_worker(self) -> None:
        while True:
            text = self._speak_q.get()
            if text is None:
                return
            self._speaking.set()
            self.set_state("speaking")
            try:
                if self.settings.get("tts_engine") == "piper" and self.capabilities()["tts_piper"]:
                    self._speak_piper(text)
                elif _try_import("pyttsx3"):
                    self._speak_sapi(text)
                else:
                    log.info("TTS indisponível; texto: %s", text)
            except Exception:  # noqa: BLE001
                log.exception("Falha na fala")
            finally:
                self._speaking.clear()
                self.set_state("listening_wake" if self._wake_thread and self._wake_thread.is_alive() else "idle")

    def _speak_sapi(self, text: str) -> None:
        import pyttsx3

        with self._tts_lock:
            if self._tts_engine is None:
                self._tts_engine = pyttsx3.init()
                wanted = (self.settings.get("tts_voice") or "").lower()
                for v in self._tts_engine.getProperty("voices"):
                    langs = " ".join(str(x) for x in getattr(v, "languages", []))
                    if (wanted and wanted in v.name.lower()) or (not wanted and ("pt" in langs.lower() or "brazil" in v.name.lower()
                                                                               or "maria" in v.name.lower())):
                        self._tts_engine.setProperty("voice", v.id)
                        break
            eng = self._tts_engine
            eng.setProperty("rate", int(180 * float(self.settings.get("rate", 1.0))))
            eng.setProperty("volume", float(self.settings.get("volume", 1.0)))
            eng.say(text)
            eng.runAndWait()

    def _speak_piper(self, text: str) -> None:
        import io
        import wave
        from pathlib import Path

        from piper import PiperVoice, SynthesisConfig

        np, sd = self.np, self.sd
        voices = sorted(Path(self.models_dir or ".").parent.joinpath("piper").glob("*.onnx"))
        if not voices:
            raise RuntimeError("Nenhuma voz Piper encontrada")
        voice = PiperVoice.load(str(voices[0]))
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            voice.synthesize_wav(text, wf, syn_config=SynthesisConfig(length_scale=1.0 / float(self.settings.get("rate", 1.0))))
        buf.seek(0)
        with wave.open(buf, "rb") as wf:
            data = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
            rate = wf.getframerate()
        sd.play((data * float(self.settings.get("volume", 1.0))).astype(np.int16), rate,
                device=self.settings.get("output_device"))
        sd.wait()
