"""Métricas do sistema (CPU, RAM, disco, rede) e diagnóstico do ambiente."""

from __future__ import annotations

import os
import platform
import shutil
import socket
import sys
import time
from pathlib import Path
from typing import Any

import psutil

_START = time.time()


def system_status(data_dir: Path) -> dict[str, Any]:
    vm = psutil.virtual_memory()
    disk = psutil.disk_usage(str(data_dir.anchor if data_dir.anchor else "/"))
    proc = psutil.Process(os.getpid())
    return {
        "cpu_percent": psutil.cpu_percent(interval=0.3),
        "cpu_count": psutil.cpu_count(logical=True),
        "ram_total_gb": round(vm.total / 1e9, 1),
        "ram_used_percent": vm.percent,
        "ram_available_gb": round(vm.available / 1e9, 1),
        "disk_total_gb": round(disk.total / 1e9, 1),
        "disk_free_gb": round(disk.free / 1e9, 1),
        "disk_used_percent": disk.percent,
        "jarvis_rss_mb": round(proc.memory_info().rss / 1e6, 1),
        "jarvis_uptime_s": int(time.time() - _START),
        "internet": check_internet(),
    }


def check_internet(host: str = "1.1.1.1", port: int = 443, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def environment_report() -> dict[str, Any]:
    vm = psutil.virtual_memory()
    freq = psutil.cpu_freq()
    report: dict[str, Any] = {
        "os": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
        "processor": platform.processor() or _cpu_model(),
        "cpu_physical": psutil.cpu_count(logical=False),
        "cpu_logical": psutil.cpu_count(logical=True),
        "cpu_max_mhz": round(freq.max) if freq and freq.max else None,
        "ram_total_gb": round(vm.total / 1e9, 1),
        "python": sys.version.split()[0],
        "tools": {name: shutil.which(name) is not None for name in ("node", "npm", "git", "ollama", "ffmpeg")},
    }
    if sys.platform == "win32":
        report["windows_build"] = platform.win32_ver()
    return report


def _cpu_model() -> str:
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as f:
            for line in f:
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return "desconhecido"
