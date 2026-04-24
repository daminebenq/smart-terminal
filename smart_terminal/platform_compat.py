"""Cross-platform helpers (shell selection, file locking).

Centralizes OS-specific code so the rest of the codebase stays portable.
"""
from __future__ import annotations
import os
import sys
import shutil
import subprocess
import platform
from typing import List


def user_shell_argv(command: str) -> List[str]:
    """Return an argv list to run *command* in the user's shell.

    - Windows  → cmd.exe /c
    - macOS    → $SHELL or /bin/zsh, with -lc
    - Linux    → $SHELL or /bin/bash (or sh fallback), with -lc / -c

    Falls back gracefully if the preferred shell isn't installed.
    """
    if sys.platform == 'win32':
        # Prefer pwsh if available, else PowerShell, else cmd
        if shutil.which('pwsh'):
            return ['pwsh', '-NoLogo', '-Command', command]
        if shutil.which('powershell'):
            return ['powershell', '-NoLogo', '-Command', command]
        return ['cmd', '/c', command]

    sh = os.environ.get('SHELL') or ''
    if not sh or not os.path.exists(sh):
        for candidate in ('/bin/zsh', '/bin/bash', '/bin/sh'):
            if os.path.exists(candidate):
                sh = candidate
                break
        else:
            sh = '/bin/sh'

    name = os.path.basename(sh)
    # -lc gives a login shell so PATH/aliases match the user's interactive env.
    # POSIX sh doesn't reliably accept -l everywhere, so use -c there.
    if name in ('zsh', 'bash'):
        return [sh, '-lc', command]
    return [sh, '-c', command]


def lock_file(path: str) -> bool:
    """Best-effort make *path* immutable. Returns True on success."""
    if not os.path.isfile(path):
        return False
    try:
        sysname = platform.system()
        if sysname == 'Darwin':
            subprocess.run(['chflags', 'uchg', path],
                           capture_output=True, timeout=5)
            return True
        if sysname == 'Linux':
            subprocess.run(['chattr', '+i', path],
                           capture_output=True, timeout=5)
            return True
        if sysname == 'Windows':
            # Make read-only via attrib; not truly immutable but best on Windows
            subprocess.run(['attrib', '+R', path],
                           capture_output=True, timeout=5, shell=False)
            return True
    except Exception:
        return False
    return False


def unlock_file(path: str) -> bool:
    """Best-effort remove immutability from *path*."""
    if not os.path.isfile(path):
        return False
    try:
        sysname = platform.system()
        if sysname == 'Darwin':
            subprocess.run(['chflags', 'nouchg', path],
                           capture_output=True, timeout=5)
            return True
        if sysname == 'Linux':
            subprocess.run(['chattr', '-i', path],
                           capture_output=True, timeout=5)
            return True
        if sysname == 'Windows':
            subprocess.run(['attrib', '-R', path],
                           capture_output=True, timeout=5, shell=False)
            return True
    except Exception:
        return False
    return False
