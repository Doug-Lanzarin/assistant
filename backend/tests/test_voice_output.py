"""Voz de resposta: texto falável, catálogo oficial do Piper, amostras e escolha da voz."""

from __future__ import annotations

import pytest

from app.voice.engines import DEFAULT_VOICE_ORDER, PIPER_CATALOG, PiperTTS
from app.voice.speech_text import to_speech


@pytest.mark.parametrize("raw,spoken", [
    ("Agora é sábado, 24 de outubro de 2026, 21:30.", "Agora é sábado, 24 de outubro de 2026, 21 e 30."),
    ("Reunião às 9h00.", "Reunião às 9 horas."),
    ("Ajustei o ar para 23 °C ✔", "Ajustei o ar para 23 graus."),
    ("A sala está a 24,5ºC e 60% de umidade.", "A sala está a 24,5 graus e 60 por cento de umidade."),
    ("Você gastou R$ 1.250,90 (segundo [memória #12]).", "Você gastou 1250 reais e 90 centavos (segundo)."),
    ("Custa R$ 1", "Custa 1 real."),
    ("Tarefas:\n- revisar o código\n- pagar a conta", "Tarefas: revisar o código. pagar a conta."),
    ("Veja https://exemplo.com 🎉", "Veja (link na tela)."),
    ("Uso de RAM: 7,1 GB", "Uso de RAM: 7,1 gigabytes."),
    ("```sql\nSELECT 1;\n```\nPronto", "(trecho de código na tela). Pronto."),
])
def test_texto_falado_soa_natural(raw, spoken):
    assert to_speech(raw) == spoken


def test_texto_longo_resume():
    t = to_speech("palavra " * 200, max_chars=100)
    assert len(t) < 140 and t.endswith("Os detalhes estão na tela.")


def test_catalogo_so_vozes_oficiais_https():
    assert set(PIPER_CATALOG) == {"pt_BR-cadu-medium", "pt_BR-faber-medium", "pt_BR-jeff-medium"}
    for meta in PIPER_CATALOG.values():
        assert meta["url"].startswith("https://huggingface.co/rhasspy/piper-voices/resolve/main/pt/pt_BR/")
    assert DEFAULT_VOICE_ORDER[0] == "pt_BR-cadu-medium"


def test_escolha_da_voz_preferida(tmp_path):
    tts = PiperTTS(tmp_path)
    (tmp_path / "piper").mkdir()
    for n in ("pt_BR-faber-medium", "pt_BR-jeff-medium"):
        (tmp_path / "piper" / f"{n}.onnx").write_bytes(b"x")
    assert tts.pick(None) == "pt_BR-faber-medium"  # cadu ausente → próxima da ordem
    assert tts.pick("pt_BR-jeff-medium") == "pt_BR-jeff-medium"
    assert tts.pick("inexistente") == "pt_BR-faber-medium"
    (tmp_path / "piper" / "pt_BR-cadu-medium.onnx").write_bytes(b"x")
    assert tts.pick(None) == "pt_BR-cadu-medium"
    with pytest.raises(ValueError):
        tts.download("../../etc/passwd")


def test_api_catalogo_e_download_restrito(client):
    r = client.get("/api/voice/piper/catalog")
    assert r.status_code == 200
    assert {v["name"] for v in r.json()} == set(PIPER_CATALOG)
    assert all({"label", "about", "installed", "current"} <= set(v) for v in r.json())
    assert "url" not in r.json()[0]
    r = client.post("/api/voice/piper/download", json={"name": "https://malicioso.example/voz"})
    assert r.status_code == 400


def test_api_amostra_aceita_voz_e_velocidade(client, monkeypatch):
    seen = {}

    def fake(text, voice=None, rate=1.0):
        seen.update(text=text, voice=voice, rate=rate)
        return b"RIFF....WAVE"

    monkeypatch.setattr(client.app.state.services.voice.tts, "synthesize", fake)
    r = client.post("/api/voice/tts", json={"text": "São 21:30 ✔", "voice": "pt_BR-jeff-medium", "rate": 0.9})
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav"
    assert seen == {"text": "São 21 e 30.", "voice": "pt_BR-jeff-medium", "rate": 0.9}
    assert client.post("/api/voice/tts", json={"text": "oi", "rate": 9}).status_code == 422


def test_status_informa_pre_carregamento(client):
    d = client.get("/api/voice/status").json()
    assert "stt_ready" in d and "stt_loading" in d
    assert d["settings"]["stt_model"] == "small" and d["settings"]["stt_beam_size"] == 5
