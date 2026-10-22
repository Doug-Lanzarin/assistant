"""Adaptador WhatsApp Web contra uma página LOCAL que imita a estrutura do site.

Teste SIMULADO: valida a lógica de automação (detecção de não lidas, busca de
contato, envio e verificação). Não comprova compatibilidade com o WhatsApp Web
real, cujo HTML muda sem aviso.
"""

import json
import os
from pathlib import Path

import pytest

pytest.importorskip("playwright")
CHROME = Path(os.environ.get("PLAYWRIGHT_CHROMIUM", "/opt/pw-browsers/chromium"))
if not CHROME.exists():
    pytest.skip("Chromium não disponível", allow_module_level=True)

from jarvis_agent.whatsapp_web import WhatsAppWeb  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "fake_whatsapp.html"


@pytest.fixture
async def wa(tmp_path, monkeypatch):
    sel = tmp_path / "sel.json"
    sel.write_text(json.dumps({"url": FIXTURE.as_uri(), "qr": "#nao-existe"}))
    w = WhatsAppWeb(tmp_path / "profile", sel)
    from playwright.async_api import async_playwright

    async def ensure(self):
        if self.page and not self.page.is_closed():
            return self.page
        self._pw = await async_playwright().start()
        self._ctx = await self._pw.chromium.launch_persistent_context(
            str(self.profile_dir), headless=True, executable_path=str(CHROME))
        self.page = self._ctx.pages[0] if self._ctx.pages else await self._ctx.new_page()
        await self.page.goto(self.sel["url"])
        return self.page

    monkeypatch.setattr(WhatsAppWeb, "_ensure", ensure)
    yield w
    await w.close()


async def test_status_unread_search_and_send(wa):
    st = await wa.status()
    assert st["logged_in"] is True
    unread = await wa.unread()
    assert [c["name"] for c in unread] == ["João Silva", "João Pereira"]
    found = await wa.search_contact("João")
    assert {f["name"] for f in found} == {"João Silva", "João Pereira"}
    res = await wa.send("João Silva", "Estou chegando")
    assert res["ok"] is True and "enviada" in res["verified"]


async def test_send_failure_is_reported(wa):
    res = await wa.send("Maria", "oi")
    assert res["ok"] is False and "confirmar" in res["error"]
    res = await wa.send("Inexistente", "oi")
    assert res["ok"] is False and "não encontrada" in res["error"]
