"""Testes do instalador (scripts/jarvis_setup.py) e do modo de primeiro plano (jarvisctl run)."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[2]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


js = _load("jarvis_setup")


def test_env_parser_comentarios_aspas_e_espacos(tmp_path):
    f = tmp_path / ".env"
    f.write_text(
        "\ufeff# comentário\n"
        "JARVIS_ENV=production            # development | production\n"
        'JARVIS_DATA_DIR="D:\\Meus Dados\\jarvis"\n'
        "export JARVIS_PORT=8790\n"
        "# ANTHROPIC_API_KEY=\n"
        "VAZIA=\n"
        "inválida linha\n",
        encoding="utf-8",
    )
    assert js.parse_env_file(f) == {"JARVIS_ENV": "production", "JARVIS_DATA_DIR": "D:\\Meus Dados\\jarvis",
                                    "JARVIS_PORT": "8790", "VAZIA": ""}


def test_load_env_nao_sobrescreve_variaveis_existentes(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text("JARVIS_PORT=9999\nJARVIS_TESTE_NOVA=1\n", encoding="utf-8")
    monkeypatch.setenv("JARVIS_PORT", "8765")
    monkeypatch.delenv("JARVIS_TESTE_NOVA", raising=False)
    js.load_env(f)
    import os

    assert os.environ["JARVIS_PORT"] == "8765"
    assert os.environ["JARVIS_TESTE_NOVA"] == "1"


def test_segredos_nunca_aparecem():
    assert js.mask("ANTHROPIC_API_KEY", "sk-ant-abc") == "definida (oculta)"
    assert js.mask("JARVIS_HA_TOKEN", "x") == "definida (oculta)"
    assert js.mask("JARVIS_PORT", "8765") == "8765"
    assert js.mask("OPENAI_API_KEY", "") == "não definida"


def test_modelo_env_example_sem_valores_de_chave():
    """O .env.example cita as chaves só comentadas e vazias (nada fictício)."""
    text = (REPO / ".env.example").read_text(encoding="utf-8")
    for line in text.splitlines():
        if any(s in line for s in ("_KEY=", "_TOKEN=")):
            assert line.lstrip().startswith("#") and line.strip().endswith("="), line
    keys = js.env_template_keys(REPO / ".env.example")
    assert {"JARVIS_PORT", "JARVIS_DATA_DIR", "ANTHROPIC_API_KEY"} <= set(keys)


def test_impressao_digital_muda_com_conteudo_e_ignora_node_modules(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.ts").write_text("1")
    (tmp_path / "src" / "node_modules").mkdir()
    (tmp_path / "src" / "node_modules" / "x.js").write_text("ignorado")
    a = js.fingerprint([tmp_path / "src"], tmp_path)
    (tmp_path / "src" / "node_modules" / "x.js").write_text("mudou")
    assert js.fingerprint([tmp_path / "src"], tmp_path) == a
    (tmp_path / "src" / "a.ts").write_text("2")
    assert js.fingerprint([tmp_path / "src"], tmp_path) != a


def test_linhas_de_requisitos_preservam_marcadores():
    lines = js.requirement_lines(REPO / "backend" / "requirements-voice.txt")
    assert "faster-whisper>=1.1" in lines
    assert "av>=12,<16" in lines  # comentário removido
    assert any(line.startswith("pyttsx3") and "sys_platform" in line for line in lines)
    assert not any(line.startswith("#") for line in lines)
    assert js.FALLBACKS["openwakeword"] == "openwakeword==0.4.0"


def test_requisitos_por_recurso():
    names = lambda f: [p.name for p in js.requirement_files(f)]  # noqa: E731
    assert names({"voice": False}) [0] == "requirements.txt"
    assert "requirements-voice.txt" in names({"voice": True})
    assert "requirements-whatsapp.txt" in names({"whatsapp": True})
    assert "requirements-dev.txt" in names({"tests": True})


def test_start_recusa_sem_configuracao_concluida(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_DATA_DIR", str(tmp_path))
    assert "execute setup.bat" in js.check_ready()[0]
    js.write_json(js.marker_file(), {"version": 1, "pip": "0" * 64, "features": {"voice": False}})
    problems = js.check_ready()
    assert any("dependências do projeto mudaram" in p for p in problems)
    fp = js.fingerprint(js.requirement_files({"voice": False}))
    js.write_json(js.marker_file(), {"version": 1, "pip": fp, "features": {"voice": False}})
    dist = REPO / "frontend" / "dist" / "index.html"
    assert js.check_ready() == ([] if dist.exists() else ["a interface não está compilada — execute setup.bat"])


def _opts(**kw):
    base = {"voice": False, "whatsapp": False, "ollama": False, "tests": False, "offline": True, "force": False, "log": None}
    base.update(kw)
    return SimpleNamespace(**base)


def test_falha_obrigatoria_remove_indicador_e_retorna_1(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("JARVIS_DATA_DIR", str(tmp_path))
    js.write_json(js.marker_file(), {"version": 1})
    rep = js.Report(tmp_path / "s.log", color=False)
    s = js.Setup(_opts(), rep)
    rep.fail("algo obrigatório", "como corrigir")
    assert s.finish() == 1
    assert not js.marker_file().exists()
    assert js.read_json(tmp_path / "setup-report.json")["ok"] is False
    rep.close()
    log = (tmp_path / "s.log").read_text(encoding="utf-8")
    assert "[FALHA]" in log and "como corrigir" in log


def test_sucesso_grava_indicador_e_lembra_recursos(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_DATA_DIR", str(tmp_path))
    rep = js.Report(tmp_path / "s.log", color=False)
    s = js.Setup(_opts(voice=True, whatsapp=True), rep)
    rep.ok("tudo certo", required=True)
    rep.warn("opcional")
    s.save_state()
    assert s.finish() == 0
    rep.close()
    assert js.read_json(js.marker_file())["features"]["whatsapp"] is True
    # Nova execução sem opções mantém os recursos já escolhidos (não desinstala nada).
    s2 = js.Setup(_opts(voice=None), js.Report(tmp_path / "s2.log", color=False))
    assert s2.features["voice"] is True and s2.features["whatsapp"] is True


def test_configuracao_preserva_arquivos_existentes(tmp_path, monkeypatch):
    """jarvis.toml e .env existentes nunca são sobrescritos."""
    repo = tmp_path / "repo"
    (repo / "config").mkdir(parents=True)
    (repo / "config" / "jarvis.example.toml").write_text('allowed_dirs = ["modelo"]\n', encoding="utf-8")
    (repo / "config" / "jarvis.toml").write_text('allowed_dirs = ["meu"]\n', encoding="utf-8")
    (repo / ".env.example").write_text("JARVIS_PORT=8765\n# ANTHROPIC_API_KEY=\n", encoding="utf-8")
    (repo / ".env").write_text("ANTHROPIC_API_KEY=sk-ant-minha-chave-real\n", encoding="utf-8")
    monkeypatch.setattr(js, "REPO", repo)
    rep = js.Report(tmp_path / "s.log", color=False)
    js.Setup(_opts(), rep).config_files()
    rep.close()
    assert (repo / "config" / "jarvis.toml").read_text(encoding="utf-8") == 'allowed_dirs = ["meu"]\n'
    assert (repo / ".env").read_text(encoding="utf-8") == "ANTHROPIC_API_KEY=sk-ant-minha-chave-real\n"
    assert "sk-ant-minha" not in (tmp_path / "s.log").read_text(encoding="utf-8")
    # Sem os arquivos, eles são criados a partir dos modelos.
    (repo / "config" / "jarvis.toml").unlink()
    (repo / ".env").unlink()
    rep = js.Report(tmp_path / "s2.log", color=False)
    js.Setup(_opts(), rep).config_files()
    rep.close()
    assert (repo / ".env").read_text(encoding="utf-8") == "JARVIS_PORT=8765\n# ANTHROPIC_API_KEY=\n"
    assert "modelo" in (repo / "config" / "jarvis.toml").read_text(encoding="utf-8")


@pytest.mark.parametrize("cmd", ["setup-status", "run"])
def test_jarvisctl_sem_setup_retorna_1(tmp_path, cmd):
    env = {"JARVIS_DATA_DIR": str(tmp_path), "PATH": "/usr/bin:/bin", "JARVIS_PORT": "18799"}
    r = subprocess.run([sys.executable, str(REPO / "scripts" / "jarvisctl.py"), cmd, *(["--no-browser"] if cmd == "run" else [])],
                       capture_output=True, text=True, env=env, timeout=60, check=False)
    assert r.returncode == 1
    assert "setup.bat" in r.stdout


def test_bat_crlf_ascii_e_ps1_com_bom():
    for name in ("setup.bat", "start.bat"):
        b = (REPO / name).read_bytes()
        assert all(c < 128 for c in b), f"{name} deve ser ASCII (cmd.exe lê na página de código OEM)"
        assert b.count(b"\n") == b.count(b"\r\n"), f"{name} deve usar CRLF"
    for ps1 in (REPO / "scripts").glob("*.ps1"):
        assert ps1.read_bytes().startswith(b"\xef\xbb\xbf"), f"{ps1.name} precisa de BOM UTF-8 (Windows PowerShell 5.1)"
