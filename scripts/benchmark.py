#!/usr/bin/env python3
"""Mede desempenho no hardware atual e grava data/benchmark-<data>.json.

Mede: inicialização, RAM, latência de comandos, busca na memória (1k/10k
itens), e — se os pacotes de voz estiverem instalados — síntese Piper,
transcrição faster-whisper (tiny/base/small) e custo da palavra de ativação.

Uso: python scripts/benchmark.py [--quick] [--data-dir DIR]
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import os
import platform
import re
import statistics
import sys
import tempfile
import time
import wave
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "backend"), str(REPO / "desktop")]


def rss_mb() -> float:
    import psutil

    return round(psutil.Process().memory_info().rss / 1e6, 1)


def timeit(fn, n=20):
    xs = []
    for _ in range(n):
        t = time.perf_counter()
        fn()
        xs.append((time.perf_counter() - t) * 1000)
    return {"p50_ms": round(statistics.median(xs), 2), "p95_ms": round(sorted(xs)[int(0.95 * (len(xs) - 1))], 2)}


async def atimeit(fn, n=20):
    xs = []
    for _ in range(n):
        t = time.perf_counter()
        await fn()
        xs.append((time.perf_counter() - t) * 1000)
    return {"p50_ms": round(statistics.median(xs), 2), "p95_ms": round(sorted(xs)[int(0.95 * (len(xs) - 1))], 2)}


def words(s: str) -> list[str]:
    import unicodedata

    s = "".join(c for c in unicodedata.normalize("NFKD", s.lower()) if not unicodedata.combining(c))
    return re.findall(r"[a-z0-9]+", s)


def wer(ref: str, hyp: str) -> float:
    r, h = words(ref), words(hyp)
    d = [[0] * (len(h) + 1) for _ in range(len(r) + 1)]
    for i in range(len(r) + 1):
        d[i][0] = i
    for j in range(len(h) + 1):
        d[0][j] = j
    for i in range(1, len(r) + 1):
        for j in range(1, len(h) + 1):
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (r[i - 1] != h[j - 1]))
    return round(d[len(r)][len(h)] / max(1, len(r)), 3)


async def core_bench(data_dir: Path, quick: bool) -> dict:
    os.environ["JARVIS_ENV"] = "test"
    out: dict = {}
    base_rss = rss_mb()
    t0 = time.perf_counter()
    from app.core.config import Settings
    from app.main import create_app
    from app.services.container import build_services

    env = Settings(env="test", data_dir=data_dir, config_file=REPO / "config" / "jarvis.example.toml")
    s = build_services(env)
    create_app(env, s)
    out["startup_ms"] = round((time.perf_counter() - t0) * 1000)
    out["rss_after_startup_mb"] = rss_mb()
    out["rss_python_baseline_mb"] = base_rss
    s.providers.set_override([])

    from app.orchestrator.intents import parse

    out["intent_parse"] = timeit(lambda: parse("Jarvis, ajuste o ar-condicionado para 23 graus"), 200)
    out["chat_rules_roundtrip"] = await atimeit(lambda: s.orchestrator.handle("que horas são?"), 30)

    for n in ([1000] if quick else [1000, 10000]):
        import random

        random.seed(1)
        vocab = ["projeto", "jarvis", "python", "sql", "docker", "voz", "memoria", "cliente", "coleta", "relatorio", "api", "teste", "banco", "dados", "ideia", "decisao", "tarefa", "reuniao", "contrato", "java", "react", "windows", "casa", "ar", "luz", "sala", "quarto"]
        t = time.perf_counter()
        existing = s.db.scalar("SELECT COUNT(*) FROM memories")
        for i in range(existing, n):
            txt = " ".join(random.choice(vocab) for _ in range(25)) + f" item {i}"
            await s.brain.add(txt, random.choice(["note", "idea", "decision"]))
        ins = time.perf_counter() - t
        add_n = max(1, n - existing)
        out[f"memory_insert_{n}"] = {"per_item_ms": round(ins / add_n * 1000, 2), "items": n}
        out[f"search_{n}"] = await atimeit(lambda: s.brain.search("decisão sobre banco de dados do projeto"), 30)
        out[f"rss_with_{n}_memories_mb"] = rss_mb()
    s.db.close()
    return out


def voice_bench(models: Path, quick: bool) -> dict:
    out: dict = {}
    try:
        import numpy as np

        from app.voice.engines import PiperTTS
    except ImportError as e:
        return {"skipped": str(e)}
    sentences = [
        "Jarvis, salve o que copiei como consulta SQL de coletas.",
        "Jarvis, ajuste o ar-condicionado para vinte e três graus.",
        "Jarvis, mande uma mensagem para o João dizendo que estou chegando.",
    ]
    tts = PiperTTS(models)
    if not PiperTTS.installed() or not tts.available_voices():
        return {"skipped": "Piper ou voz pt_BR ausentes (rode scripts/download_voice_models.py)"}
    wavs = []
    piper = []
    for s in sentences:
        t = time.perf_counter()
        w = tts.synthesize(s)
        el = time.perf_counter() - t
        with wave.open(io.BytesIO(w)) as wf:
            dur = wf.getnframes() / wf.getframerate()
        piper.append({"chars": len(s), "audio_s": round(dur, 2), "synth_s": round(el, 3), "rtf": round(el / dur, 3)})
        wavs.append(w)
    out["piper_tts"] = piper

    try:
        from app.voice.engines import STTEngine
    except ImportError:
        return out
    if STTEngine.installed():
        stt = STTEngine(models)
        out["whisper"] = {}
        for model in (["base"] if quick else ["tiny", "base", "small"]):
            t = time.perf_counter()
            stt._load(model)
            load_s = time.perf_counter() - t
            rows = []
            for ref, w in zip(sentences, wavs, strict=True):
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                    f.write(w)
                    path = Path(f.name)
                try:
                    r = stt.transcribe_file(path, model=model)
                finally:
                    path.unlink()
                rows.append({"ref": ref, "hyp": r["text"], "wer": wer(ref, r["text"]), "audio_s": r["duration_s"],
                             "proc_s": r["processing_s"], "rtf": round(r["processing_s"] / max(0.1, r["duration_s"]), 3)})
            out["whisper"][model] = {"load_s": round(load_s, 2), "rss_mb": rss_mb(), "samples": rows,
                                     "mean_wer": round(statistics.mean(x["wer"] for x in rows), 3),
                                     "mean_rtf": round(statistics.mean(x["rtf"] for x in rows), 3)}
            stt._model = None
    try:
        from jarvis_agent.voice import load_wake_model

        oww = load_wake_model("hey_jarvis")
        frame = np.zeros(1280, dtype=np.int16)
        for _ in range(10):
            oww.predict(frame)
        n = 200
        t = time.perf_counter()
        for _ in range(n):
            oww.predict(frame)
        per = (time.perf_counter() - t) / n
        out["wakeword"] = {"model": "hey_jarvis", "ms_per_80ms_frame": round(per * 1000, 2),
                           "cpu_fraction_one_core": round(per / 0.08, 3)}
        # Detecção em fala sintetizada ("Hey Jarvis")
        hey = tts.synthesize("Hey Jarvis!")
        with wave.open(io.BytesIO(hey)) as wf:
            sr = wf.getframerate()
            pcm = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
        if sr != 16000:
            idx = (np.arange(int(len(pcm) * 16000 / sr)) * sr / 16000).astype(int)
            pcm = pcm[idx]
        pcm = np.concatenate([np.zeros(16000, np.int16), pcm, np.zeros(16000, np.int16)])
        oww.reset()
        best = 0.0
        for i in range(0, len(pcm) - 1280, 1280):
            best = max(best, float(max(oww.predict(pcm[i:i + 1280]).values())))
        out["wakeword"]["synthetic_hey_jarvis_max_score"] = round(best, 3)
        oww.reset()
        noise = (np.random.default_rng(0).normal(0, 300, 16000 * 10)).astype(np.int16)
        fp = 0.0
        for i in range(0, len(noise) - 1280, 1280):
            fp = max(fp, float(max(oww.predict(noise[i:i + 1280]).values())))
        out["wakeword"]["noise_10s_max_score"] = round(fp, 3)
    except Exception as e:  # noqa: BLE001
        out["wakeword"] = {"skipped": str(e)}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--data-dir", default=None)
    ap.add_argument("--models-dir", default=str(REPO / "data" / "models"))
    a = ap.parse_args()
    from app.services.system_info import environment_report

    report = {"when": time.strftime("%Y-%m-%d %H:%M"), "environment": environment_report(), "platform": platform.platform()}
    with tempfile.TemporaryDirectory() as tmp:
        report["core"] = asyncio.run(core_bench(Path(a.data_dir or tmp) / "bench", a.quick))
    report["voice"] = voice_bench(Path(a.models_dir), a.quick)
    out = REPO / "data" / f"benchmark-{time.strftime('%Y%m%d-%H%M')}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), "utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"\nRelatório salvo em {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
