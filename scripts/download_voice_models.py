#!/usr/bin/env python3
"""Baixa os modelos de voz locais (uma única vez, ~200 MB no total).

* Piper pt_BR (voz "cadu", qualidade média; --piper cadu,faber,jeff) → data/models/piper/
* faster-whisper ``small`` (ou o indicado em --whisper) → data/models/whisper/
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
PIPER_HF = "https://huggingface.co/rhasspy/piper-voices/resolve/main/pt/pt_BR/"
# Vozes pt-BR oficiais do Piper. "cadu" é a padrão (ritmo de conversa); as outras podem ser
# baixadas também aqui ou em Configurações → Voz.
PIPER_VOICES = {"cadu": "cadu/medium/pt_BR-cadu-medium", "faber": "faber/medium/pt_BR-faber-medium",
                "jeff": "jeff/medium/pt_BR-jeff-medium"}


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
    ap.add_argument("--whisper", default="small", choices=["tiny", "base", "small"])
    ap.add_argument("--skip-wake", action="store_true")
    ap.add_argument("--piper", default="cadu", help="vozes Piper separadas por vírgula (cadu,faber,jeff)")
    ap.add_argument("--data-dir", default=os.environ.get("JARVIS_DATA_DIR", str(REPO / "data")))
    a = ap.parse_args()
    models = Path(a.data_dir) / "models"
    (models / "piper").mkdir(parents=True, exist_ok=True)
    for name in [v.strip() for v in a.piper.split(",") if v.strip()]:
        if name not in PIPER_VOICES:
            print(f"  voz desconhecida: {name}")
            continue
        print(f"Piper (voz pt-BR {name}):")
        for ext in (".onnx", ".onnx.json"):
            rel = PIPER_VOICES[name] + ext
            download(PIPER_HF + rel, models / "piper" / rel.rsplit("/", 1)[1])
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
