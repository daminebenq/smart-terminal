"""Shell execution helpers for the interactive REPL.

Keeps a persistent working directory (so `cd` works between commands),
captures output for /fix while still streaming it live, and leaves
full-screen / interactive programs attached to the real TTY.
"""
from __future__ import annotations

import os
import re
import shlex
import subprocess
import time
from dataclasses import dataclass, field
from typing import List, Optional

from smart_terminal.platform_compat import user_shell_argv

# Programs that need a real TTY; we don't capture their output.
_INTERACTIVE = {
    'vim', 'vi', 'nvim', 'nano', 'emacs', 'less', 'more', 'man', 'top', 'htop', 'btop',
    'ssh', 'mosh', 'tmux', 'screen', 'python', 'python3', 'ipython', 'node', 'irb',
    'psql', 'mysql', 'sqlite3', 'watch', 'fzf', 'lazygit', 'tig', 'docker-compose',
}

MAX_CAPTURE = 8000


@dataclass
class ShellResult:
    command: str
    code: int
    output: str = ''
    seconds: float = 0.0
    captured: bool = True


@dataclass
class ShellState:
    cwd: str = field(default_factory=os.getcwd)
    prev_cwd: Optional[str] = None
    last: Optional[ShellResult] = None
    history: List[ShellResult] = field(default_factory=list)

    @property
    def last_code(self) -> int:
        return self.last.code if self.last else 0

    def last_failed(self) -> Optional[ShellResult]:
        for r in reversed(self.history):
            if r.code != 0:
                return r
        return None


def _is_interactive(command: str) -> bool:
    try:
        parts = shlex.split(command)
    except ValueError:
        return False
    if not parts:
        return False
    i = 0
    while i < len(parts) and (parts[i] in ('sudo', 'env', 'time', 'nohup') or '=' in parts[i]):
        i += 1
    prog = os.path.basename(parts[i]) if i < len(parts) else ''
    if prog in ('python', 'python3', 'node') and len(parts) > i + 1:
        return False  # running a script, not a REPL
    if prog == 'docker' and len(parts) > i + 1 and '-it' in parts:
        return True
    return prog in _INTERACTIVE


def try_builtin_cd(command: str, state: ShellState) -> Optional[ShellResult]:
    """Handle a bare `cd …` so the directory persists. Returns None if not a cd."""
    m = re.match(r'^\s*cd(?:\s+(.*))?\s*$', command)
    if not m or any(ch in command for ch in ';&|'):
        return None
    target = (m.group(1) or '~').strip()
    try:
        target = shlex.split(target)[0] if target else '~'
    except ValueError:
        pass
    if target == '-':
        target = state.prev_cwd or state.cwd
    path = os.path.abspath(os.path.join(state.cwd, os.path.expandvars(os.path.expanduser(target))))
    if not os.path.isdir(path):
        res = ShellResult(command, 1, f'cd: no such directory: {target}')
        print(res.output)
    else:
        state.prev_cwd, state.cwd = state.cwd, path
        res = ShellResult(command, 0, '')
    state.last = res
    state.history.append(res)
    return res


def run(command: str, state: ShellState, capture: Optional[bool] = None) -> ShellResult:
    """Run *command* in the user's shell inside state.cwd, streaming output."""
    cd = try_builtin_cd(command, state)
    if cd is not None:
        return cd
    if capture is None:
        capture = not _is_interactive(command)
    t0 = time.time()
    argv = user_shell_argv(command)
    if not capture:
        try:
            code = subprocess.run(argv, cwd=state.cwd).returncode
        except KeyboardInterrupt:
            code = 130
        res = ShellResult(command, code, '', time.time() - t0, captured=False)
    else:
        buf: List[str] = []
        size = 0
        try:
            proc = subprocess.Popen(argv, cwd=state.cwd, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, bufsize=1,
                                    errors='replace')
            assert proc.stdout is not None
            for line in proc.stdout:
                print(line, end='', flush=True)
                if size < MAX_CAPTURE:
                    buf.append(line)
                    size += len(line)
            code = proc.wait()
        except KeyboardInterrupt:
            proc.terminate()
            code = 130
        except FileNotFoundError as e:
            print(e)
            code = 127
        out = ''.join(buf)
        if size >= MAX_CAPTURE:
            out = out[:MAX_CAPTURE] + '\n… (output truncated)'
        res = ShellResult(command, code, out, time.time() - t0)
    state.last = res
    state.history.append(res)
    del state.history[:-50]
    return res


def git_branch(cwd: str) -> str:
    """Return the current git branch for *cwd* without spawning git (fast)."""
    d = cwd
    for _ in range(40):
        head = os.path.join(d, '.git', 'HEAD')
        if os.path.isfile(head):
            try:
                with open(head, 'r', encoding='utf-8') as f:
                    ref = f.read().strip()
                return ref.rsplit('/', 1)[-1] if ref.startswith('ref:') else ref[:7]
            except OSError:
                return ''
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return ''


def pretty_cwd(cwd: str) -> str:
    home = os.path.expanduser('~')
    if cwd == home:
        return '~'
    if cwd.startswith(home + os.sep):
        return '~' + cwd[len(home):]
    return cwd
