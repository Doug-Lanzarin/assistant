"""Motores de voz locais (opcionais).

* STT: faster-whisper (CTranslate2, int8 em CPU). Modelos: tiny/base/small.
  Em CPU de notebook sem GPU, ``base`` é o equilíbrio recomendado; ``small``
  é mais preciso e ~3x mais lento.
* TTS: Piper (ONNX, voz pt_BR). Alternativas sem instalação: voz do navegador
  (Web Speech API, usa as vozes do Windows) e SAPI no agente.

Nada de áudio é enviado para a nuvem e nada é gravado em disco permanentemente
(arquivos temporários são apagados após a transcrição).
"""

from __future__ import annotations

import io
import logging
import tempfile
import threading
import time
import wave
from pathlib import Path
from typing import Any

log = logging.getLogger("jarvis.voice")


class VoiceUnavailable(RuntimeError):
    pass


class STTEngine:
    def __init__(self, models_dir: Path):
        self.models_dir = models_dir
        self._model = None
        self._model_name: str | None = None
        self._lock = threading.Lock()

    @staticmethod
    def installed() -> bool:
        try:
            import faster_whisper  # noqa: F401
        except ImportError:
            return False
        return True

    def _load(self, name: str):
        with self._lock:
            if self._model is not None and self._model_name == name:
                return self._model
            try:
                from faster_whisper import WhisperModel
            except ImportError as e:
                raise VoiceUnavailable("faster-whisper não instalado (pip install -r requirements-voice.txt)") from e
            t0 = time.perf_counter()
            self._model = WhisperModel(name, device="cpu", compute_type="int8",
                                       download_root=str(self.models_dir / "whisper"), cpu_threads=0)
            self._model_name = name
            log.info("Modelo Whisper '%s' carregado em %.1fs", name, time.perf_counter() - t0)
            return self._model

    def transcribe_file(self, path: Path, model: str = "base", language: str = "pt", prompt: str | None = None,
                        hotwords: str | None = "Jarvis") -> dict[str, Any]:
        m = self._load(model)
        t0 = time.perf_counter()
        segments, info = m.transcribe(str(path), language=language, vad_filter=True, beam_size=1,
                                      condition_on_previous_text=False, initial_prompt=prompt or None,
                                      hotwords=hotwords or None)
        text = " ".join(s.text.strip() for s in segments).strip()
        return {"text": text, "language": info.language, "duration_s": round(info.duration, 2),
                "processing_s": round(time.perf_counter() - t0, 2), "model": model}

    def transcribe_bytes(self, data: bytes, suffix: str = ".webm", **kw) -> dict[str, Any]:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            f.write(data)
            tmp = Path(f.name)
        try:
            return self.transcribe_file(tmp, **kw)
        finally:
            tmp.unlink(missing_ok=True)


class PiperTTS:
    def __init__(self, models_dir: Path):
        self.models_dir = models_dir / "piper"
        self._voice = None
        self._voice_path: Path | None = None

    def available_voices(self) -> list[str]:
        if not self.models_dir.exists():
            return []
        return sorted(p.stem for p in self.models_dir.glob("*.onnx"))

    @staticmethod
    def installed() -> bool:
        try:
            import piper  # noqa: F401
        except ImportError:
            return False
        return True

    def synthesize(self, text: str, voice: str | None = None, rate: float = 1.0) -> bytes:
        try:
            from piper import PiperVoice, SynthesisConfig
        except ImportError as e:
            raise VoiceUnavailable("piper-tts não instalado (pip install -r requirements-voice.txt)") from e
        voices = self.available_voices()
        if not voices:
            raise VoiceUnavailable("Nenhuma voz Piper em data/models/piper (rode scripts/download_voice_models.py)")
        name = voice if voice in voices else voices[0]
        path = self.models_dir / f"{name}.onnx"
        if self._voice is None or self._voice_path != path:
            self._voice = PiperVoice.load(str(path))
            self._voice_path = path
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            cfg = SynthesisConfig(length_scale=1.0 / max(0.5, min(2.0, rate)))
            self._voice.synthesize_wav(text, wf, syn_config=cfg)
        return buf.getvalue()
