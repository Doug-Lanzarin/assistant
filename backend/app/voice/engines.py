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
import os
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
        self.loading: str | None = None  # modelo sendo carregado agora (1ª vez pode levar ~20 s)

    @property
    def ready_model(self) -> str | None:
        return self._model_name if self._model is not None else None

    def warm(self, name: str) -> None:
        """Carrega o modelo antes do primeiro uso (chamado em segundo plano na inicialização)."""
        try:
            self._load(name)
        except Exception:  # noqa: BLE001
            log.exception("Falha ao pré-carregar o Whisper '%s'", name)

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
            self.loading = name
            try:
                kw = {"device": "cpu", "compute_type": "int8", "download_root": str(self.models_dir / "whisper"), "cpu_threads": 0}
                try:  # já baixado: carrega sem consultar a internet (funciona offline)
                    self._model = WhisperModel(name, local_files_only=True, **kw)
                except Exception:  # noqa: BLE001 - ainda não baixado → baixa uma vez
                    self._model = WhisperModel(name, **kw)
            finally:
                self.loading = None
            self._model_name = name
            log.info("Modelo Whisper '%s' carregado em %.1fs", name, time.perf_counter() - t0)
            return self._model

    def transcribe_file(self, path: Path, model: str = "small", language: str = "pt", prompt: str | None = None,
                        hotwords: str | None = "Jarvis", beam_size: int = 5) -> dict[str, Any]:
        m = self._load(model)
        t0 = time.perf_counter()
        segments, info = m.transcribe(str(path), language=language, vad_filter=True, beam_size=max(1, int(beam_size)),
                                      condition_on_previous_text=False, initial_prompt=prompt or None,
                                      without_timestamps=True,  # mesma precisão, ~20% mais rápido (medido)
                                      hotwords=hotwords or None)
        text = " ".join(s.text.strip() for s in segments).strip()
        log.info("Transcrição: %.1f s de áudio em %.2f s (%s)", info.duration, time.perf_counter() - t0, model)
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


_HF = "https://huggingface.co/rhasspy/piper-voices/resolve/main/pt/pt_BR"
# Vozes pt-BR OFICIAIS do Piper (repositório rhasspy/piper-voices). Só estas podem ser baixadas pela interface.
PIPER_CATALOG: dict[str, dict[str, str]] = {
    "pt_BR-cadu-medium": {"label": "Cadu", "about": "masculina, ritmo de conversa (padrão)", "url": f"{_HF}/cadu/medium/pt_BR-cadu-medium"},
    "pt_BR-faber-medium": {"label": "Faber", "about": "masculina, fala mais rápida", "url": f"{_HF}/faber/medium/pt_BR-faber-medium"},
    "pt_BR-jeff-medium": {"label": "Jeff", "about": "masculina, grave e pausada", "url": f"{_HF}/jeff/medium/pt_BR-jeff-medium"},
}
DEFAULT_VOICE_ORDER = ["pt_BR-cadu-medium", "pt_BR-faber-medium", "pt_BR-jeff-medium"]


class PiperTTS:
    def __init__(self, models_dir: Path):
        self.models_dir = models_dir / "piper"
        self._voice = None
        self._voice_path: Path | None = None
        self._lock = threading.Lock()  # pré-carregamento e pedidos podem chegar ao mesmo tempo

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
        name = self.pick(voice)
        path = self.models_dir / f"{name}.onnx"
        with self._lock:
            if self._voice is None or self._voice_path != path:
                self._voice = PiperVoice.load(str(path))
                self._voice_path = path
            buf = io.BytesIO()
            with wave.open(buf, "wb") as wf:
                cfg = SynthesisConfig(length_scale=1.0 / max(0.5, min(2.0, rate)))
                self._voice.synthesize_wav(text, wf, syn_config=cfg)
        return buf.getvalue()

    def pick(self, voice: str | None = None) -> str:
        """Voz escolhida, se instalada; senão a preferida entre as instaladas."""
        voices = self.available_voices()
        if voice in voices:
            return voice
        for name in DEFAULT_VOICE_ORDER:
            if name in voices:
                return name
        return voices[0]

    def download(self, name: str) -> Path:
        """Baixa uma voz do catálogo oficial (HTTPS fixo). Idempotente."""
        import urllib.request

        if name not in PIPER_CATALOG:
            raise ValueError("Voz fora do catálogo oficial")
        self.models_dir.mkdir(parents=True, exist_ok=True)
        base = PIPER_CATALOG[name]["url"]
        for ext in (".onnx.json", ".onnx"):
            dest = self.models_dir / f"{name}{ext}"
            if dest.exists() and dest.stat().st_size > 0:
                continue
            tmp = dest.with_suffix(dest.suffix + ".part")
            with urllib.request.urlopen(base + ext, timeout=60) as r, open(tmp, "wb") as f:  # noqa: S310 - URL fixa (HTTPS)
                while chunk := r.read(1 << 20):
                    f.write(chunk)
            if tmp.stat().st_size < (1_000 if ext == ".onnx.json" else 1_000_000):
                tmp.unlink(missing_ok=True)
                raise VoiceUnavailable(f"Download incompleto de {name}{ext}")
            os.replace(tmp, dest)
        return self.models_dir / f"{name}.onnx"
