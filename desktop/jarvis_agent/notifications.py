"""Leitura das notificações do Windows (UserNotificationListener, WinRT).

Requer: pacotes ``winrt-Windows.UI.Notifications.Management``,
``winrt-Windows.UI.Notifications`` e ``winrt-Windows.Foundation`` e a
permissão do usuário (Configurações → Privacidade → Notificações → permitir
que aplicativos acessem as notificações). Em algumas versões do Windows a API
exige identidade de pacote (MSIX) e retorna "negado" para scripts Python —
nesse caso este módulo reporta indisponível e o WhatsApp deve usar o modo
'web' ou 'business'.

Só repassa notificações de apps cujo nome contém "whatsapp" (filtro local).
"""

from __future__ import annotations

import asyncio
import logging
import sys
from collections.abc import Callable

log = logging.getLogger("jarvis_agent.notifications")


class NotificationWatcher:
    def __init__(self, emit: Callable[[str, dict], None], app_filter: str = "whatsapp", interval: float = 3.0):
        self.emit = emit
        self.filter = app_filter.lower()
        self.interval = interval
        self.seen: set[int] = set()
        self.status = "não iniciado"

    @staticmethod
    def supported() -> bool:
        if sys.platform != "win32":
            return False
        try:
            import winrt.windows.ui.notifications.management  # noqa: F401
        except ImportError:
            return False
        return True

    async def run(self) -> None:
        if not self.supported():
            self.status = "indisponível (somente Windows com pacotes winrt)"
            return
        from winrt.windows.ui.notifications import NotificationKinds
        from winrt.windows.ui.notifications.management import UserNotificationListener, UserNotificationListenerAccessStatus

        listener = UserNotificationListener.current
        access = await listener.request_access_async()
        if access != UserNotificationListenerAccessStatus.ALLOWED:
            self.status = "acesso negado às notificações (verifique a privacidade do Windows)"
            log.warning(self.status)
            return
        self.status = "ativo"
        first = True
        while True:
            try:
                items = await listener.get_notifications_async(NotificationKinds.TOAST)
                for n in items:
                    if n.id in self.seen:
                        continue
                    self.seen.add(n.id)
                    app = n.app_info.display_info.display_name if n.app_info else ""
                    if self.filter not in (app or "").lower() or first:
                        continue
                    binding = n.notification.visual.get_binding("ToastGeneric")
                    texts = [t.text for t in binding.get_text_elements()] if binding else []
                    title = texts[0] if texts else ""
                    body = "\n".join(texts[1:])
                    self.emit("notification", {"id": f"win:{n.id}", "app": app, "title": title, "body": body,
                                               "ts": n.creation_time.isoformat() if hasattr(n.creation_time, "isoformat") else None})
                first = False
            except Exception as e:  # noqa: BLE001
                log.warning("Falha ao ler notificações: %s", e)
            await asyncio.sleep(self.interval)
