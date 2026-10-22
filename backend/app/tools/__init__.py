"""Ferramentas registradas do JARVIS (a única forma de o sistema agir)."""

from __future__ import annotations

from app.orchestrator.registry import ToolRegistry


def register_all(reg: ToolRegistry) -> None:
    from . import brain_tools, clipboard_tools, core_tools, home_tools, whatsapp_tools, windows_tools

    for mod in (core_tools, brain_tools, clipboard_tools, windows_tools, home_tools, whatsapp_tools):
        mod.register(reg)
