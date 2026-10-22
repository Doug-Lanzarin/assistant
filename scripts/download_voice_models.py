#!/usr/bin/env python3
"""Baixa os modelos de voz locais (uma única vez, ~200 MB no total).

* Piper pt_BR (voz "faber", qualidade média) → data/models/piper/
* faster-whisper ``base`` (ou o indicado em --whisper) → data/models/whisper/
* openWakeWord "hey_jarvis" + modelos de base → cache do pacote

Uso: python scripts/download_voice_models.py [--whisper base|small|tiny] [--skip-wake]
"""

from __future__ import annotations

import argparse
import os
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PIPER_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main/pt/pt_BR/faber/medium/"
PIPER_FILES = ["pt_BR-faber-medium.onnx", "pt_BR-faber-medium.onnx.json"]


def download(url: str, dest: Path) -> None:
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  já existe: {dest.name}")
        return
    print(f"  baixando {url}")
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url, timeout=60) as r, open(tmp, "wb") as f:  # noqa: S310 - URL fixa (HTTPS)
        while chunk := r.read(1 << 20):
            f.write(chunk)
    os.replace(tmp, dest)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--whisper", default="base", choices=["tiny", "base", "small"])
    ap.add_argument("--skip-wake", action="store_true")
    ap.add_argument("--data-dir", default=os.environ.get("JARVIS_DATA_DIR", str(REPO / "data")))
    a = ap.parse_args()
    models = Path(a.data_dir) / "models"
    (models / "piper").mkdir(parents=True, exist_ok=True)
    print("Piper (voz pt-BR):")
    for f in PIPER_FILES:
        download(PIPER_BASE + f, models / "piper" / f)
    print(f"faster-whisper ({a.whisper}):")
    try:
        from faster_whisper import WhisperModel

        WhisperModel(a.whisper, device="cpu", compute_type="int8", download_root=str(models / "whisper"))
        print("  ok")
    except ImportError:
        print("  faster-whisper não instalado (pip install -r backend/requirements-voice.txt)")
    if not a.skip_wake:
        print("openWakeWord (hey_jarvis):")
        try:
            sys.path.insert(0, str(REPO / "desktop"))
            from jarvis_agent.voice import load_wake_model

            load_wake_model("hey_jarvis")
            print("  ok")
        except Exception as e:  # noqa: BLE001
            print(f"  falhou: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
