"""Adaptador do WhatsApp Web via Playwright (opcional, isolado).

* Abre um navegador VISÍVEL com perfil dedicado (``data/whatsapp-session``),
  onde o próprio usuário escaneia o QR code. O JARVIS nunca contorna
  autenticação, CAPTCHA ou mecanismos de segurança.
* Lê apenas o que está visível na interface (conversas não lidas, últimas
  mensagens da conversa aberta).
* Envia UMA mensagem por vez, somente após confirmação no JARVIS, e verifica
  que a mensagem apareceu como enviada.

RISCOS: automação de interface depende do HTML do WhatsApp Web, que muda sem
aviso (os seletores ficam em ``whatsapp_selectors.json`` para ajuste rápido),
e pode contrariar os Termos de Serviço do WhatsApp. Use por sua conta, em
volume pessoal. Para uso empresarial, prefira a Cloud API oficial.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger("jarvis_agent.whatsapp")

DEFAULT_SELECTORS = {
    "url": "https://web.whatsapp.com/",
    "logged_in": "#pane-side",
    "qr": "canvas[aria-label], div[data-ref]",
    "chat_rows": "#pane-side div[role='listitem'], #pane-side div[role='row']",
    "unread_badge": "span[aria-label*='não lida'], span[aria-label*='unread'], span[aria-label*='mensagens não lidas']",
    "row_title": "span[title]",
    "row_preview": "span[dir='ltr'], span[dir='auto']",
    "search_box": "div[contenteditable='true'][data-tab='3'], div[role='textbox'][aria-label*='Pesquisar'], div[role='textbox'][aria-label*='Search']",
    "composer": "footer div[contenteditable='true']",
    "message_in": "div.message-in",
    "message_out": "div.message-out",
    "message_text": "span.selectable-text",
    "sent_marker": "span[data-icon='msg-check'], span[data-icon='msg-dblcheck'], span[data-icon='msg-time']",
}


class WhatsAppWeb:
    def __init__(self, profile_dir: Path, selectors_file: Path | None = None):
        self.profile_dir = profile_dir
        self.sel = dict(DEFAULT_SELECTORS)
        if selectors_file and selectors_file.exists():
            self.sel.update(json.loads(selectors_file.read_text("utf-8")))
        self._pw = None
        self._ctx = None
        self.page = None
        self._lock = asyncio.Lock()

    @staticmethod
    def installed() -> bool:
        try:
            import playwright  # noqa: F401
        except ImportError:
            return False
        return True

    async def _ensure(self):
        if self.page and not self.page.is_closed():
            return self.page
        from playwright.async_api import async_playwright

        self._pw = await async_playwright().start()
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self._ctx = await self._pw.chromium.launch_persistent_context(
            str(self.profile_dir), headless=False, locale="pt-BR", viewport={"width": 1200, "height": 850},
        )
        self.page = self._ctx.pages[0] if self._ctx.pages else await self._ctx.new_page()
        await self.page.goto(self.sel["url"])
        return self.page

    async def status(self) -> dict[str, Any]:
        async with self._lock:
            page = await self._ensure()
            try:
                await page.wait_for_selector(f"{self.sel['logged_in']}, {self.sel['qr']}", timeout=20000)
            except Exception:  # noqa: BLE001
                return {"logged_in": False, "detail": "WhatsApp Web ainda carregando"}
            logged = await page.locator(self.sel["logged_in"]).count() > 0
            return {"logged_in": logged,
                    "detail": "Conectado ao WhatsApp Web" if logged else "Escaneie o QR code na janela do navegador aberta pelo JARVIS"}

    async def unread(self, limit: int = 20) -> list[dict[str, Any]]:
        async with self._lock:
            page = await self._ensure()
            await page.wait_for_selector(self.sel["logged_in"], timeout=30000)
            rows = page.locator(self.sel["chat_rows"])
            out = []
            for i in range(min(await rows.count(), 60)):
                row = rows.nth(i)
                if await row.locator(self.sel["unread_badge"]).count() == 0:
                    continue
                title = row.locator(self.sel["row_title"]).first
                name = await title.get_attribute("title") if await title.count() else None
                previews = row.locator(self.sel["row_preview"])
                preview = (await previews.last.inner_text()) if await previews.count() else ""
                out.append({"name": name or "?", "preview": preview.strip(),
                            "messages": [{"sender": name or "?", "text": preview.strip()}]})
                if len(out) >= limit:
                    break
            return out

    async def _open_chat(self, page, query: str) -> bool:
        box = page.locator(self.sel["search_box"]).first
        await box.click()
        await box.fill("")
        await box.type(query, delay=30)
        await page.wait_for_timeout(1200)
        rows = page.locator(self.sel["chat_rows"])
        for i in range(min(await rows.count(), 10)):
            t = rows.nth(i).locator(self.sel["row_title"]).first
            if await t.count() and (await t.get_attribute("title") or "").strip().lower() == query.strip().lower():
                await rows.nth(i).click()
                return True
        return False

    async def search_contact(self, query: str) -> list[dict[str, Any]]:
        async with self._lock:
            page = await self._ensure()
            await page.wait_for_selector(self.sel["logged_in"], timeout=30000)
            box = page.locator(self.sel["search_box"]).first
            await box.click()
            await box.fill("")
            await box.type(query, delay=30)
            await page.wait_for_timeout(1200)
            rows = page.locator(self.sel["chat_rows"])
            names = []
            for i in range(min(await rows.count(), 8)):
                t = rows.nth(i).locator(self.sel["row_title"]).first
                if await t.count():
                    n = (await t.get_attribute("title") or "").strip()
                    if n and query.lower().split()[0] in n.lower() and n not in names:
                        names.append(n)
            await box.fill("")
            return [{"name": n} for n in names]

    async def send(self, chat: str, text: str) -> dict[str, Any]:
        async with self._lock:
            page = await self._ensure()
            await page.wait_for_selector(self.sel["logged_in"], timeout=30000)
            if not await self._open_chat(page, chat):
                return {"ok": False, "error": f"Conversa '{chat}' não encontrada no WhatsApp Web"}
            composer = page.locator(self.sel["composer"]).first
            await composer.click()
            await composer.type(text, delay=15)
            before = await page.locator(self.sel["message_out"]).count()
            await page.keyboard.press("Enter")
            for _ in range(20):
                await page.wait_for_timeout(500)
                outs = page.locator(self.sel["message_out"])
                if await outs.count() > before:
                    last = outs.last
                    body = (await last.inner_text()).strip()
                    has_marker = await last.locator(self.sel["sent_marker"]).count() > 0
                    if text.strip()[:40] in body and has_marker:
                        return {"ok": True, "chat": chat, "verified": "mensagem visível como enviada na conversa"}
            return {"ok": False, "error": "Não consegui confirmar o envio na interface do WhatsApp Web"}

    async def close(self) -> None:
        if self._ctx:
            await self._ctx.close()
        if self._pw:
            await self._pw.stop()
