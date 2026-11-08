"""`smart-term doctor`: check configuration, connectivity and optional deps."""
from __future__ import annotations

import importlib
import os
import shutil
import sys
import time

from smart_terminal.ui import C


def _line(ok_: bool, label: str, detail: str = '', warn_only: bool = False) -> None:
    if ok_:
        mark = f'{C.ok}✓{C.reset}'
    else:
        mark = f'{C.warn}!{C.reset}' if warn_only else f'{C.err}✗{C.reset}'
    print(f'  {mark} {label:<26} {C.dim}{detail}{C.reset}')


def run_doctor(agent=None) -> int:
    """Print a health report. Returns the number of hard failures."""
    from smart_terminal import __version__
    from smart_terminal.setup import CONFIG_FILE, is_configured
    failures = 0
    print(f'{C.hdr}Smart Terminal doctor{C.reset} {C.dim}v{__version__}{C.reset}\n')

    print(f'{C.bold}Environment{C.reset}')
    _line(sys.version_info >= (3, 9), 'python', sys.version.split()[0])
    _line(True, 'executable', sys.executable)
    _line(bool(os.getenv('VIRTUAL_ENV')) or '.venv' in sys.executable, 'virtualenv',
          os.getenv('VIRTUAL_ENV') or sys.prefix, warn_only=True)
    shell = os.getenv('SHELL', '')
    _line(bool(shell), 'shell', shell or 'unknown', warn_only=True)

    print(f'\n{C.bold}Configuration{C.reset}')
    configured = is_configured()
    _line(configured, 'config file', CONFIG_FILE if configured else 'missing — run: smart-term configure')
    if not configured:
        failures += 1

    if agent is None and configured:
        try:
            from smart_terminal.settings import SettingsManager
            from smart_terminal.agent import TerminalAgent
            s = SettingsManager()
            agent = TerminalAgent(api_base=s.get('OLLAMA_API_BASE') or '', model=s.get('OLLAMA_MODEL') or '')
        except Exception as e:
            _line(False, 'agent init', str(e))
            failures += 1

    if agent is not None:
        _line(bool(agent.api_base), 'api base', agent.api_base or 'not set')
        _line(bool(agent.model), 'model', agent.model or 'not set')
        _line(True, 'provider', getattr(agent, 'provider', '?'))
        print(f'\n{C.bold}Connectivity{C.reset}')
        t0 = time.time()
        try:
            names = agent.list_models()
            ms = int((time.time() - t0) * 1000)
            _line(True, 'model server', f'reachable in {ms} ms, {len(names)} model(s)')
            if names and agent.model:
                _line(agent.model in names, 'model available', agent.model, warn_only=True)
        except Exception as e:
            _line(False, 'model server', f'{type(e).__name__}: {str(e)[:80]}')
            failures += 1

    print(f'\n{C.bold}Python packages{C.reset}')
    for mod, label, required in [
        ('requests', 'requests', True), ('prompt_toolkit', 'prompt_toolkit', True),
        ('dotenv', 'python-dotenv', True), ('rich', 'rich (markdown)', False),
        ('ddgs', 'ddgs (web search)', False), ('trafilatura', 'trafilatura', False),
        ('bs4', 'beautifulsoup4', False), ('diskcache', 'diskcache', False),
        ('playwright', 'playwright', False), ('selenium', 'selenium', False),
        ('flask', 'flask (web UI)', False),
    ]:
        try:
            importlib.import_module(mod)
            _line(True, label)
        except Exception:
            _line(False, label, 'missing' + ('' if required else ' (optional)'), warn_only=not required)
            if required:
                failures += 1

    print(f'\n{C.bold}Tools{C.reset}')
    for tool in ('git', 'docker', 'pbcopy', 'xclip', 'wl-copy'):
        path = shutil.which(tool)
        if path or tool in ('git', 'docker'):
            _line(bool(path), tool, path or 'not found', warn_only=True)

    print()
    if failures:
        print(f'{C.err}{failures} problem(s) found.{C.reset}')
    else:
        print(f'{C.ok}All good.{C.reset}')
    return failures
