"""Contêiner de serviços: monta e conecta todos os módulos do JARVIS."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.clipboard_memory.service import ClipboardMemory
from app.core.config import JarvisToml, Settings, load_toml
from app.core.db import Database
from app.core.events import EventBus
from app.integrations.agent_bridge import AgentBridge
from app.integrations.home_assistant.service import HomeService
from app.integrations.whatsapp.service import WhatsAppService
from app.memory.documents import Library
from app.memory.graph import Graph
from app.memory.index import Indexer
from app.memory.store import Brain
from app.orchestrator.executor import ToolExecutor
from app.orchestrator.registry import ToolRegistry
from app.providers.manager import ProviderManager
from app.security.auth import AuthService
from app.security.secrets import SecretStore
from app.services.files import FileGuard
from app.services.settings_store import SettingsStore

log = logging.getLogger("jarvis")


@dataclass
class Services:
    env: Settings
    toml: JarvisToml
    db: Database
    settings: SettingsStore
    secrets: SecretStore
    auth: AuthService
    events: EventBus
    registry: ToolRegistry
    agent: AgentBridge
    indexer: Indexer
    graph: Graph
    brain: Brain
    library: Library
    clipboard: ClipboardMemory
    providers: ProviderManager
    home: HomeService
    whatsapp: WhatsAppService
    files: FileGuard
    executor: ToolExecutor = field(init=False)
    orchestrator: Any = field(init=False)
    background: Any = field(init=False, default=None)
    voice: Any = field(init=False, default=None)
    conversation_state: dict[int, dict[str, Any]] = field(default_factory=dict)

    def reload_toml(self) -> None:
        self.toml = load_toml(self.env.config_file)
        self.files = FileGuard(self.toml.allowed_dirs)
        self.home.toml_devices = self.toml.devices

    def refresh_embedder(self) -> None:
        self.indexer.set_embedder(self.providers.embedder())

    def state_for(self, conversation_id: int | None) -> dict[str, Any]:
        if conversation_id is None:
            return {}
        return self.conversation_state.setdefault(conversation_id, {})


def build_services(env: Settings) -> Services:
    from app.orchestrator.orchestrator import Orchestrator
    from app.tools import register_all

    env.ensure_dirs()
    db = Database(env.db_path)
    db.migrate()
    toml = load_toml(env.config_file)
    settings = SettingsStore(db)
    secrets = SecretStore(env.secrets_dir)
    events = EventBus()
    agent = AgentBridge()
    providers = ProviderManager(db, settings, secrets, env)
    indexer = Indexer(db, providers.embedder())
    graph = Graph(db)
    brain = Brain(db, indexer, graph)
    library = Library(db, indexer, graph, env.library_dir)
    clipboard = ClipboardMemory(db, indexer, graph, secrets.cipher, agent, brain)
    home = HomeService(db, settings, secrets, toml.devices, env=env)
    whatsapp = WhatsAppService(db, settings, secrets, agent, events)
    s = Services(
        env=env, toml=toml, db=db, settings=settings, secrets=secrets,
        auth=AuthService(db, env.session_ttl_hours), events=events, registry=ToolRegistry(), agent=agent,
        indexer=indexer, graph=graph, brain=brain, library=library, clipboard=clipboard, providers=providers,
        home=home, whatsapp=whatsapp, files=FileGuard(toml.allowed_dirs),
    )
    s.executor = ToolExecutor(s)
    register_all(s.registry)
    s.orchestrator = Orchestrator(s)
    agent.on_event(whatsapp.handle_agent_event)
    agent.on_event(s.orchestrator.handle_agent_event)
    return s
