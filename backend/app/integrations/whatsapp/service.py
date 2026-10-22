"""WhatsApp: três canais independentes, todos opcionais.

1. ``notifications`` — o agente lê as notificações do Windows (WhatsApp Desktop)
   e as repassa. Somente leitura; vê apenas o que aparece na notificação
   (remetente + prévia). NÃO dá acesso ao histórico.
2. ``web`` — o agente controla o WhatsApp Web num navegador com perfil
   dedicado, autenticado pelo próprio usuário via QR code. Permite listar
   conversas não lidas visíveis e enviar mensagens após confirmação.
   Automação de interface: frágil a mudanças do site e sujeita aos termos
   de uso do WhatsApp — uso pessoal, um envio por vez, sem automação em massa.
3. ``business`` — WhatsApp Business Platform (Cloud API oficial da Meta).
   Exige conta Business, número dedicado e app na Meta. Só envia/recebe
   mensagens do número empresarial — não lê a conta pessoal.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from app.core.db import Database, from_json, to_json, utcnow
from app.integrations.agent_bridge import AgentBridge
from app.orchestrator.textnorm import normalize_key

log = logging.getLogger("jarvis.whatsapp")
GRAPH_URL = "https://graph.facebook.com"


class WhatsAppError(RuntimeError):
    pass


class WhatsAppService:
    def __init__(self, db: Database, settings_store, secrets, agent: AgentBridge, events=None,
                 transport: httpx.AsyncBaseTransport | None = None):
        self.db = db
        self.settings = settings_store
        self.secrets = secrets
        self.agent = agent
        self.events = events
        self._transport = transport

    @property
    def mode(self) -> str:
        return self.settings.get("whatsapp")["mode"]

    # -- estado -----------------------------------------------------------------------
    async def status(self) -> dict[str, Any]:
        mode = self.mode
        st: dict[str, Any] = {"mode": mode, "can_read": False, "can_send": False, "detail": ""}
        if mode == "disabled":
            st["detail"] = "Integração desativada. Escolha um modo em Configurações → WhatsApp."
        elif mode == "notifications":
            ok = self.agent.connected and self.agent.has_capability("notifications")
            st.update(can_read=ok, detail="Lendo notificações do Windows" if ok else
                      "Agente sem acesso às notificações (conecte o agente e permita o acesso às notificações).")
        elif mode == "web":
            if not self.agent.connected:
                st["detail"] = "Agente local não conectado."
            else:
                try:
                    info = await self.agent.call("whatsapp.status", {}, timeout=15)
                    st.update(can_read=bool(info.get("logged_in")), can_send=bool(info.get("logged_in")),
                              detail=info.get("detail", ""), web=info)
                except Exception as e:  # noqa: BLE001
                    st["detail"] = f"WhatsApp Web indisponível: {e}"
        elif mode == "business":
            cfg = self.settings.get("whatsapp")
            ok = bool(cfg.get("phone_number_id") and self.secrets.get("whatsapp_cloud_token"))
            st.update(can_read=ok, can_send=ok,
                      detail="Cloud API configurada" if ok else "Informe phone_number_id e o token da Cloud API.")
        st["stored_messages"] = self.db.scalar("SELECT COUNT(*) FROM whatsapp_messages")
        st["unread"] = self.db.scalar("SELECT COUNT(*) FROM whatsapp_messages WHERE is_read=0")
        return st

    # -- entrada ------------------------------------------------------------------------
    async def ingest(self, source: str, sender: str, text: str, chat: str | None = None,
                     ext_id: str | None = None, received_at: str | None = None) -> int | None:
        text = (text or "").strip()
        if not text:
            return None
        if ext_id and self.db.query_one("SELECT id FROM whatsapp_messages WHERE ext_id=?", (ext_id,)):
            return None
        mid = self.db.insert(
            "INSERT INTO whatsapp_messages(source, ext_id, chat, sender, text, received_at) VALUES (?,?,?,?,?,?)",
            (source, ext_id, chat or sender, sender, text[:4000], received_at or utcnow()),
        )
        if self.events:
            await self.events.publish("whatsapp_message", {"id": mid, "sender": sender, "preview": text[:120]})
        return mid

    async def handle_agent_event(self, event: str, data: dict) -> None:
        if event == "notification" and str(data.get("app", "")).lower().find("whatsapp") >= 0:
            await self.ingest("notification", data.get("title") or "Desconhecido", data.get("body") or "",
                              ext_id=data.get("id"), received_at=data.get("ts"))
        elif event == "whatsapp.message":
            await self.ingest("web", data.get("sender") or "?", data.get("text") or "", data.get("chat"),
                              data.get("id"), data.get("ts"))

    # -- leitura --------------------------------------------------------------------------
    async def read(self, only_unread: bool = True, limit: int = 20, mark_read: bool = True) -> list[dict]:
        if self.mode == "web" and self.agent.connected:
            try:
                chats = await self.agent.call("whatsapp.unread", {"limit": limit}, timeout=30)
                for c in chats or []:
                    for m in c.get("messages", []) or [{"text": c.get("preview", ""), "id": None}]:
                        await self.ingest("web", m.get("sender") or c.get("name", "?"), m.get("text", ""),
                                          c.get("name"), m.get("id") or "web:" + hashlib.sha256(f"{c.get('name')}|{m.get('text', '')}".encode()).hexdigest())
            except Exception as e:  # noqa: BLE001
                log.warning("Falha ao ler WhatsApp Web: %s", e)
        sql = "SELECT * FROM whatsapp_messages"
        if only_unread:
            sql += " WHERE is_read=0"
        rows = self.db.query(sql + " ORDER BY received_at DESC LIMIT ?", (limit,))
        if mark_read and rows:
            ids = [r["id"] for r in rows]
            self.db.execute(f"UPDATE whatsapp_messages SET is_read=1 WHERE id IN ({','.join('?' * len(ids))})", tuple(ids))
        return rows

    def search(self, query: str, limit: int = 30) -> list[dict]:
        like = f"%{query}%"
        return self.db.query(
            "SELECT * FROM whatsapp_messages WHERE text LIKE ? OR sender LIKE ? ORDER BY received_at DESC LIMIT ?",
            (like, like, limit),
        )

    # -- contatos ------------------------------------------------------------------------
    def add_contact(self, name: str, phone: str | None = None, aliases: list[str] | None = None) -> dict:
        if phone:
            phone = "".join(c for c in phone if c.isdigit())
            if not 10 <= len(phone) <= 15:
                raise WhatsAppError("Telefone inválido: use o formato internacional, ex.: 5511999998888")
        cid = self.db.insert(
            "INSERT INTO contacts(name, normalized, phone, aliases, created_at) VALUES (?,?,?,?,?)",
            (name.strip(), normalize_key(name), phone, to_json(aliases or []), utcnow()),
        )
        return self.db.query_one("SELECT * FROM contacts WHERE id=?", (cid,))  # type: ignore[return-value]

    def list_contacts(self) -> list[dict]:
        return self.db.query("SELECT * FROM contacts ORDER BY name")

    def delete_contact(self, cid: int) -> None:
        self.db.execute("DELETE FROM contacts WHERE id=?", (cid,))

    async def resolve_contact(self, name: str) -> list[dict]:
        key = normalize_key(name)
        out = []
        for c in self.list_contacts():
            names = [c["normalized"]] + [normalize_key(a) for a in from_json(c["aliases"], [])]
            if key in names or any(n.split()[0] == key for n in names if n) or any(key in n for n in names):
                out.append({"name": c["name"], "address": c["phone"], "source": "contatos"})
        if self.mode == "web" and self.agent.connected:
            try:
                found = await self.agent.call("whatsapp.search_contact", {"query": name}, timeout=20)
                known = {normalize_key(o["name"]) for o in out}
                for f in found or []:
                    if normalize_key(f["name"]) not in known:
                        out.append({"name": f["name"], "address": f.get("name"), "source": "whatsapp web"})
            except Exception as e:  # noqa: BLE001
                log.warning("Busca de contato no WhatsApp Web falhou: %s", e)
        exact = [o for o in out if normalize_key(o["name"]) == key]
        return exact if len(exact) == 1 else out

    # -- envio -----------------------------------------------------------------------------
    async def send(self, to_name: str, to_address: str | None, text: str) -> dict[str, Any]:
        mode = self.mode
        if mode not in {"web", "business"}:
            raise WhatsAppError("O modo atual do WhatsApp não permite envio (use 'web' ou 'business').")
        oid = self.db.insert(
            "INSERT INTO whatsapp_outbox(channel, to_name, to_address, text, status, created_at) VALUES (?,?,?,?,?,?)",
            (mode, to_name, to_address, text, "sending", utcnow()),
        )
        try:
            if mode == "business":
                evidence = await self._send_cloud(to_address or "", text)
            else:
                res = await self.agent.call("whatsapp.send", {"chat": to_address or to_name, "text": text}, timeout=60)
                if not (isinstance(res, dict) and res.get("ok")):
                    raise WhatsAppError((res or {}).get("error") or "O WhatsApp Web não confirmou o envio.")
                evidence = res
        except Exception as e:
            self.db.execute("UPDATE whatsapp_outbox SET status='failed', error=? WHERE id=?", (str(e)[:500], oid))
            raise
        self.db.execute(
            "UPDATE whatsapp_outbox SET status='sent', evidence=?, sent_at=? WHERE id=?", (to_json(evidence), utcnow(), oid)
        )
        return {"outbox_id": oid, "evidence": evidence}

    def outbox(self, limit: int = 50) -> list[dict]:
        return self.db.query("SELECT * FROM whatsapp_outbox ORDER BY id DESC LIMIT ?", (limit,))

    # -- Cloud API ------------------------------------------------------------------------
    async def _send_cloud(self, phone: str, text: str) -> dict:
        cfg = self.settings.get("whatsapp")
        token = self.secrets.get("whatsapp_cloud_token")
        if not (token and cfg.get("phone_number_id")):
            raise WhatsAppError("Cloud API não configurada (phone_number_id/token).")
        if not phone.isdigit():
            raise WhatsAppError("Contato sem telefone em formato internacional cadastrado.")
        url = f"{GRAPH_URL}/{cfg['api_version']}/{cfg['phone_number_id']}/messages"
        body = {"messaging_product": "whatsapp", "recipient_type": "individual", "to": phone,
                "type": "text", "text": {"preview_url": False, "body": text}}
        async with httpx.AsyncClient(timeout=20, transport=self._transport) as c:
            r = await c.post(url, json=body, headers={"Authorization": f"Bearer {token}"})
        data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        if r.status_code >= 400:
            err = (data.get("error") or {}) if isinstance(data, dict) else {}
            hint = ""
            if err.get("code") in (131047, 131026):
                hint = " (fora da janela de 24h: é preciso usar um template aprovado)"
            raise WhatsAppError(f"Cloud API recusou o envio: {err.get('message', r.text[:200])}{hint}")
        msgs = data.get("messages") or []
        if not msgs or not msgs[0].get("id"):
            raise WhatsAppError("Cloud API não retornou o ID da mensagem; envio não confirmado.")
        return {"message_id": msgs[0]["id"], "status": msgs[0].get("message_status", "accepted")}

    def verify_webhook(self, mode: str | None, token: str | None, challenge: str | None) -> str | None:
        expected = self.secrets.get("whatsapp_verify_token")
        if mode == "subscribe" and expected and token and hmac.compare_digest(token, expected):
            return challenge
        return None

    def check_signature(self, raw: bytes, header: str | None) -> bool:
        secret = self.secrets.get("whatsapp_app_secret")
        if not secret or not header or not header.startswith("sha256="):
            return False
        digest = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        return hmac.compare_digest(digest, header.split("=", 1)[1])

    async def ingest_webhook(self, payload: dict) -> int:
        n = 0
        for entry in payload.get("entry", []) or []:
            for change in entry.get("changes", []) or []:
                value = change.get("value") or {}
                names = {c.get("wa_id"): (c.get("profile") or {}).get("name") for c in value.get("contacts", []) or []}
                for m in value.get("messages", []) or []:
                    text = (m.get("text") or {}).get("body") or f"[{m.get('type', 'mensagem')}]"
                    ts = m.get("timestamp")
                    at = datetime.fromtimestamp(int(ts), UTC).isoformat(timespec="seconds") if ts else None
                    sender = names.get(m.get("from")) or m.get("from") or "?"
                    if await self.ingest("business", sender, text, sender, m.get("id"), at):
                        n += 1
                for s in value.get("statuses", []) or []:
                    self.db.execute(
                        "UPDATE whatsapp_outbox SET status=? WHERE json_extract(evidence, '$.message_id')=?",
                        (s.get("status", "unknown"), s.get("id")),
                    )
        return n
