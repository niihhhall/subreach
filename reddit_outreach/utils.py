# -*- coding: utf-8 -*-
"""Small cross-platform helpers for the manual send assistant."""

from __future__ import annotations

import shutil
import subprocess
import sys
import webbrowser


def copy_to_clipboard(text: str) -> bool:
    """Copy text to the OS clipboard. Returns True on success.

    Tries pyperclip first (if installed), then native tools:
    Windows ``clip``, macOS ``pbcopy``, Linux ``xclip``/``xsel``/``wl-copy``.
    """
    try:
        import pyperclip  # type: ignore
        pyperclip.copy(text)
        return True
    except Exception:
        pass

    data = text.encode("utf-8")
    candidates = []
    if sys.platform == "win32":
        candidates = [["clip"]]
    elif sys.platform == "darwin":
        candidates = [["pbcopy"]]
    else:
        candidates = [["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]]

    for cmd in candidates:
        if shutil.which(cmd[0]):
            try:
                subprocess.run(cmd, input=data, timeout=5, check=True)
                return True
            except Exception:
                continue
    return False


def open_in_browser(url: str) -> bool:
    """Open a URL in the default browser. Returns True if the call succeeded."""
    try:
        return webbrowser.open(url)
    except Exception:
        return False
