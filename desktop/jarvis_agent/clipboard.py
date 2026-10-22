"""Acesso real à área de transferência.

* Windows: API Win32 via ctypes (CF_UNICODETEXT, CF_HDROP), sem dependências.
* Linux (desenvolvimento): wl-paste/wl-copy, xclip ou xsel, se instalados.
* Memória: para testes automatizados.

O clipboard só é lido quando o backend pede (sem monitoramento contínuo).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
from typing import Any


class ClipboardBackend:
    name = "base"

    def read(self) -> dict[str, Any]:
        raise NotImplementedError

    def write(self, text: str) -> None:
        raise NotImplementedError


class MemoryClipboard(ClipboardBackend):
    name = "memory"

    def __init__(self) -> None:
        self.data: dict[str, Any] = {"format": "empty"}

    def read(self) -> dict[str, Any]:
        return dict(self.data)

    def write(self, text: str) -> None:
        self.data = {"format": "text", "text": text}

    # utilitários de teste
    def set_text(self, text: str) -> None:
        self.write(text)

    def set_other(self, fmt: str) -> None:
        self.data = {"format": fmt}


class Win32Clipboard(ClipboardBackend):
    name = "win32"
    CF_UNICODETEXT = 13
    CF_HDROP = 15
    CF_DIB = 8
    CF_BITMAP = 2
    GMEM_MOVEABLE = 0x0002

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        self.ctypes = ctypes
        u32 = ctypes.WinDLL("user32", use_last_error=True)
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        sh32 = ctypes.WinDLL("shell32", use_last_error=True)
        u32.OpenClipboard.argtypes = [wintypes.HWND]
        u32.OpenClipboard.restype = wintypes.BOOL
        u32.CloseClipboard.restype = wintypes.BOOL
        u32.EmptyClipboard.restype = wintypes.BOOL
        u32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
        u32.IsClipboardFormatAvailable.restype = wintypes.BOOL
        u32.GetClipboardData.argtypes = [wintypes.UINT]
        u32.GetClipboardData.restype = wintypes.HANDLE
        u32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
        u32.SetClipboardData.restype = wintypes.HANDLE
        u32.CountClipboardFormats.restype = ctypes.c_int
        k32.GlobalLock.argtypes = [wintypes.HGLOBAL]
        k32.GlobalLock.restype = wintypes.LPVOID
        k32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        k32.GlobalUnlock.restype = wintypes.BOOL
        k32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
        k32.GlobalAlloc.restype = wintypes.HGLOBAL
        k32.GlobalFree.argtypes = [wintypes.HGLOBAL]
        k32.GlobalFree.restype = wintypes.HGLOBAL
        sh32.DragQueryFileW.argtypes = [wintypes.HANDLE, wintypes.UINT, wintypes.LPWSTR, wintypes.UINT]
        sh32.DragQueryFileW.restype = wintypes.UINT
        self.u32, self.k32, self.sh32 = u32, k32, sh32

    def _open(self) -> None:
        for _ in range(20):  # outro programa pode estar segurando o clipboard
            if self.u32.OpenClipboard(None):
                return
            time.sleep(0.05)
        raise OSError("Não foi possível abrir a área de transferência (ocupada por outro programa)")

    def read(self) -> dict[str, Any]:
        ctypes = self.ctypes
        self._open()
        try:
            if self.u32.IsClipboardFormatAvailable(self.CF_UNICODETEXT):
                h = self.u32.GetClipboardData(self.CF_UNICODETEXT)
                if not h:
                    return {"format": "empty"}
                p = self.k32.GlobalLock(h)
                try:
                    text = ctypes.wstring_at(p)
                finally:
                    self.k32.GlobalUnlock(h)
                return {"format": "text", "text": text}
            if self.u32.IsClipboardFormatAvailable(self.CF_HDROP):
                h = self.u32.GetClipboardData(self.CF_HDROP)
                count = self.sh32.DragQueryFileW(h, 0xFFFFFFFF, None, 0)
                files = []
                for i in range(count):
                    size = self.sh32.DragQueryFileW(h, i, None, 0) + 1
                    buf = ctypes.create_unicode_buffer(size)
                    self.sh32.DragQueryFileW(h, i, buf, size)
                    files.append(buf.value)
                return {"format": "files", "files": files}
            if self.u32.IsClipboardFormatAvailable(self.CF_DIB) or self.u32.IsClipboardFormatAvailable(self.CF_BITMAP):
                return {"format": "image"}
            if self.u32.CountClipboardFormats() == 0:
                return {"format": "empty"}
            return {"format": "other"}
        finally:
            self.u32.CloseClipboard()

    def write(self, text: str) -> None:
        ctypes = self.ctypes
        data = text.encode("utf-16-le") + b"\x00\x00"
        self._open()
        try:
            if not self.u32.EmptyClipboard():
                raise OSError("EmptyClipboard falhou")
            h = self.k32.GlobalAlloc(self.GMEM_MOVEABLE, len(data))
            if not h:
                raise MemoryError("GlobalAlloc falhou")
            p = self.k32.GlobalLock(h)
            ctypes.memmove(p, data, len(data))
            self.k32.GlobalUnlock(h)
            if not self.u32.SetClipboardData(self.CF_UNICODETEXT, h):
                self.k32.GlobalFree(h)
                raise OSError("SetClipboardData falhou")
            # Após SetClipboardData o sistema é dono da memória: não liberar.
        finally:
            self.u32.CloseClipboard()


class CommandClipboard(ClipboardBackend):
    """Linux: usa utilitários de linha de comando, se disponíveis."""

    def __init__(self) -> None:
        if shutil.which("wl-paste") and shutil.which("wl-copy"):
            self.name, self.get, self.put = "wayland", ["wl-paste", "--no-newline"], ["wl-copy"]
        elif shutil.which("xclip"):
            self.name, self.get, self.put = "xclip", ["xclip", "-selection", "clipboard", "-o"], ["xclip", "-selection", "clipboard"]
        elif shutil.which("xsel"):
            self.name, self.get, self.put = "xsel", ["xsel", "--clipboard", "--output"], ["xsel", "--clipboard", "--input"]
        else:
            raise RuntimeError("Nenhum utilitário de clipboard encontrado (wl-clipboard, xclip ou xsel)")

    def read(self) -> dict[str, Any]:
        r = subprocess.run(self.get, capture_output=True, timeout=5, check=False)
        if r.returncode != 0 or not r.stdout:
            return {"format": "empty"}
        try:
            return {"format": "text", "text": r.stdout.decode("utf-8")}
        except UnicodeDecodeError:
            return {"format": "other"}

    def write(self, text: str) -> None:
        subprocess.run(self.put, input=text.encode("utf-8"), timeout=5, check=True)


def default_backend() -> ClipboardBackend:
    if sys.platform == "win32":
        return Win32Clipboard()
    try:
        return CommandClipboard()
    except RuntimeError:
        return MemoryClipboard()
