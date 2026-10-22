"""Agente local: lista fechada de métodos e validação defensiva das ações."""

import sys

import pytest

from jarvis_agent import actions
from jarvis_agent.clipboard import MemoryClipboard, default_backend
from jarvis_agent.rpc import Dispatcher, RpcError


async def test_unknown_method_rejected():
    d = Dispatcher(clipboard=MemoryClipboard())
    with pytest.raises(RpcError):
        await d.dispatch("os.system", {"cmd": "format c:"})
    with pytest.raises(RpcError):
        await d.dispatch("clipboard.write", {"text": 123})
    with pytest.raises(RpcError):
        await d.dispatch("clipboard.write", "não é objeto")


async def test_clipboard_roundtrip_unicode():
    d = Dispatcher(clipboard=MemoryClipboard())
    text = "linha 1\r\nlinha\t2 — ção 🚀\n"
    assert (await d.dispatch("clipboard.write", {"text": text}))["ok"]
    assert (await d.dispatch("clipboard.read", {})) == {"format": "text", "text": text}


@pytest.mark.parametrize("cmd", ["calc.exe & del *", "a;b", "$(whoami)", "x|y", "", "cmd`x`"])
def test_launch_rejects_shell_metachars(cmd):
    with pytest.raises(actions.ActionError):
        actions.launch(cmd, [])


def test_launch_rejects_bad_args():
    with pytest.raises(actions.ActionError):
        actions.launch(sys.executable, ["ok", 3])
    with pytest.raises(actions.ActionError):
        actions.launch(sys.executable, ["a\x00b"])


@pytest.mark.parametrize("url", ["file:///c:/windows", "javascript:alert(1)", "ftp://x", "http://a b"])
def test_open_url_only_http(url):
    with pytest.raises(actions.ActionError):
        actions.open_url(url)


def test_open_path_must_exist():
    with pytest.raises(actions.ActionError):
        actions.open_path("/caminho/que/nao/existe")


def test_run_process_no_shell(tmp_path):
    r = actions.run_process(sys.executable, ["-c", "print('ok')"], str(tmp_path), 20)
    assert r["returncode"] == 0 and r["stdout"].strip() == "ok"
    # argumentos com metacaracteres são passados literalmente (sem shell)
    r = actions.run_process(sys.executable, ["-c", "import sys; print(sys.argv[1])", "a && echo hacked"], None, 20)
    assert r["stdout"].strip() == "a && echo hacked"
    r = actions.run_process(sys.executable, ["-c", "import time; time.sleep(5)"], None, 0.5)
    assert r["returncode"] == -1


def test_launch_real_process():
    r = actions.launch(sys.executable, ["-c", "pass"])
    assert r["ok"] and r["pid"] > 0


def test_default_backend_available():
    b = default_backend()
    assert b.name in {"win32", "wayland", "xclip", "xsel", "memory"}


def test_info_capabilities():
    d = Dispatcher(clipboard=MemoryClipboard())
    info = d.info()
    assert {"clipboard", "apps", "notify", "process"} <= set(info["capabilities"])
    assert "voice" not in info["capabilities"]
