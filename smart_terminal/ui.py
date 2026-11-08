"""Terminal UI helpers: colors (NO_COLOR aware), spinner, boxes, status lines."""
from __future__ import annotations

import os
import shutil
import sys
import threading
import time
from typing import Iterable, Optional


def color_enabled(stream=None) -> bool:
    stream = stream or sys.stdout
    if os.getenv('NO_COLOR') or os.getenv('SMART_TERM_NO_COLOR'):
        return False
    if os.getenv('FORCE_COLOR'):
        return True
    return hasattr(stream, 'isatty') and stream.isatty()


class _Palette:
    _codes = {
        'hdr': '\033[1;34m', 'ok': '\033[1;32m', 'warn': '\033[1;33m', 'err': '\033[1;31m',
        'dim': '\033[2m', 'bold': '\033[1m', 'user': '\033[1;36m', 'ai': '\033[1;35m',
        'code': '\033[0;32m', 'reset': '\033[0m', 'cyan': '\033[0;36m',
    }

    def __getattr__(self, name):
        if name.startswith('_'):
            raise AttributeError(name)
        return self._codes.get(name, '') if color_enabled() else ''


C = _Palette()


def term_width(default: int = 80) -> int:
    try:
        return max(40, min(shutil.get_terminal_size((default, 24)).columns, 120))
    except Exception:
        return default


def ok(msg: str) -> None:
    print(f'{C.ok}✓{C.reset} {msg}')


def warn(msg: str) -> None:
    print(f'{C.warn}!{C.reset} {msg}')


def err(msg: str) -> None:
    print(f'{C.err}✗{C.reset} {msg}', file=sys.stderr)


def info(msg: str) -> None:
    print(f'{C.dim}{msg}{C.reset}')


def header(title: str) -> None:
    w = term_width() - 2
    print(f'{C.hdr}╭{"─" * w}╮{C.reset}')
    print(f'{C.hdr}│{C.reset} {C.bold}{title}{C.reset}{" " * max(0, w - len(title) - 1)}{C.hdr}│{C.reset}')
    print(f'{C.hdr}╰{"─" * w}╯{C.reset}')


def risk_badge(risk: int) -> str:
    if risk <= 0:
        return f'{C.ok}● safe (0){C.reset}'
    if risk < 30:
        return f'{C.ok}● low ({risk}){C.reset}'
    if risk < 60:
        return f'{C.warn}● medium ({risk}){C.reset}'
    return f'{C.err}● HIGH ({risk}){C.reset}'


def command_box(commands: Iterable[str], title: str = 'Proposed commands', risk: Optional[int] = None) -> None:
    cmds = list(commands)
    w = term_width() - 2
    t = f' {title} '
    print(f'\n{C.hdr}╭─{t}{"─" * max(0, w - len(t) - 1)}╮{C.reset}')
    for i, c in enumerate(cmds, 1):
        prefix = f'[{i}] '
        room = w - len(prefix) - 2
        disp = c if len(c) <= room else c[:room - 1] + '…'
        pad = w - len(prefix) - len(disp) - 1
        print(f'{C.hdr}│{C.reset} {C.dim}{prefix}{C.reset}{C.code}{disp}{C.reset}{" " * max(0, pad)}{C.hdr}│{C.reset}')
    print(f'{C.hdr}╰{"─" * w}╯{C.reset}')
    if risk is not None:
        print(f'  Risk: {risk_badge(risk)}')


class Spinner:
    """Context-manager spinner printed to stderr so stdout stays pipe-clean."""

    FRAMES = '⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'

    def __init__(self, label: str = 'thinking…'):
        self.label = label
        self._stop = threading.Event()
        self._thr: Optional[threading.Thread] = None
        self._enabled = sys.stderr.isatty() and not os.getenv('SMART_TERM_NO_SPINNER')
        self._t0 = 0.0

    def _run(self):
        i = 0
        while not self._stop.is_set():
            el = time.time() - self._t0
            sys.stderr.write(f'\r{C.ai}{self.FRAMES[i % len(self.FRAMES)]}{C.reset} '
                             f'{C.dim}{self.label} {el:4.1f}s{C.reset}')
            sys.stderr.flush()
            time.sleep(0.08)
            i += 1

    def start(self):
        self._t0 = time.time()
        if self._enabled:
            self._stop.clear()
            self._thr = threading.Thread(target=self._run, daemon=True)
            self._thr.start()
        return self

    def stop(self):
        if self._thr:
            self._stop.set()
            self._thr.join(timeout=0.5)
            self._thr = None
            sys.stderr.write('\r\033[K')
            sys.stderr.flush()

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()
        return False
