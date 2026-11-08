"""Continuous chat REPL — Claude CLI / Codex CLI style.

Features:
- Persistent multi-turn conversation with the model
- Streaming responses with a spinner while waiting for the first token
- Auto-detect shell commands in responses → prompt [y]es / [n]o / [e]dit / [#]
- Tab-completion for all slash commands (press Tab)
- Bottom toolbar with live session / token-budget info
- Alt+Enter / Ctrl+J to add a newline in the input (multiline paste works too)
- Ctrl+L to clear the screen
- Auto-compaction + long-term memorization when context fills up
- Slash commands: /help /new /clear /compact /history /tokens /sessions
                  /load /save /rename /delete /export /model /system /reset
                  /exec /memory /search /remember /pin /unpin /forget /forget-all
                  /continue /exit /quit
- Shell passthrough: `!<cmd>` runs a command directly (cd persists),
  /fix sends the last failing command + output to the model
- `@path/to/file` in a message attaches that file's contents
- Prompt shows cwd, git branch and last exit code (fish/zsh style)
"""

from __future__ import annotations
import os
import re
import sys
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.formatted_text import ANSI, HTML
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.completion import (WordCompleter, PathCompleter, FuzzyCompleter,
                                       Completer, Completion)
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.key_binding import KeyBindings

from smart_terminal.platform_compat import user_shell_argv
from smart_terminal import shell as _shell
from smart_terminal.ui import color_enabled as _color_enabled

from smart_terminal.agent import TerminalAgent
from smart_terminal.conversation import Conversation, SESSIONS_DIR

# ── ANSI palette ──────────────────────────────────────────────────────────────
_COL = _color_enabled()
C_HDR   = '\033[1;34m'   # bold blue
C_OK    = '\033[1;32m'   # bold green
C_WARN  = '\033[1;33m'   # bold yellow
C_ERR   = '\033[1;31m'   # bold red
C_DIM   = '\033[2m'      # dim
C_RESET = '\033[0m'
C_USER  = '\033[1;36m'   # bold cyan  (user prompt)
C_AI    = '\033[1;35m'   # bold magenta (AI bullet)
C_CODE  = '\033[0;32m'   # dark green (inline code)
C_BOLD  = '\033[1m'
if not _COL:  # honour NO_COLOR / non-TTY output
    C_HDR = C_OK = C_WARN = C_ERR = C_DIM = C_RESET = C_USER = C_AI = C_CODE = C_BOLD = ''

# Shared shell state for the REPL: persistent cwd, last exit code, history.
_STATE = _shell.ShellState()

# ── Slash-command list (drives Tab completion) ─────────────────────────────────
_SLASH_CMDS = [
    '/help', '/new', '/clear', '/compact', '/history', '/tokens',
    '/sessions', '/load', '/save', '/rename', '/delete', '/export',
    '/model', '/models', '/system', '/reset', '/exec', '/exit', '/quit',
    '/continue', '/memory', '/search', '/remember', '/pin', '/unpin',
    '/forget', '/forget-all',
    '/fix', '/explain', '/run', '/cd', '/pwd', '/copy', '/retry', '/undo',
    '/stats', '/doctor', '/config', '/version', '/clear-screen', '/md',
]

HELP_TEXT = f"""{C_HDR}Smart Terminal — Chat Mode{C_RESET}
Type naturally to chat. The assistant remembers the full conversation
AND persistent facts from prior sessions (long-term memory).

{C_HDR}Session:{C_RESET}
  /help                 Show this help
  /new                  Start a new conversation (saves current)
  /continue             Resume the most recently updated session
  /clear                Clear current conversation (keep session id)
  /compact              Force summarize + memorize older messages
  /history              List messages in current session
  /tokens               Show estimated token usage & budget
  /sessions             List saved sessions
  /load <id|#>          Resume a saved session by id or list number
  /save                 Save current session now
  /rename <name>        Rename current session
  /delete <id|#>        Delete a saved session
  /export [path]        Export current session to a file (default: md)

{C_HDR}Memory (long-term, cross-session):{C_RESET}
  /memory               List stored long-term memories
  /search <query>       Search memories by substring
  /remember <text>      Manually add a fact to long-term memory
  /pin <id>             Pin a memory (always included in prompt)
  /unpin <id>           Unpin a memory
  /forget <id>          Delete a specific memory
  /forget-all           Delete all unpinned memories

{C_HDR}Model & prompt:{C_RESET}
  /models               List all available models on the server
  /model <name>         Switch model (e.g. /model gemma4:31b-cloud)
  /system <text>        Replace the system prompt
  /reset                Reset system prompt to default

{C_HDR}Shell:{C_RESET}
  !<command>            Run a shell command directly (e.g. !git status)
  /run <command>        Same as !<command>
  /cd <dir> · /pwd      Change / show the working directory (persists)
  /fix                  Ask the AI to fix the last failing command
  /explain <command>    Explain what a shell command does
  @path/to/file         Attach a file's contents to your message

{C_HDR}Actions:{C_RESET}
  /exec                 Extract shell commands from last response & run them
  /retry                Re-send your last message
  /undo                 Remove the last user/assistant exchange
  /copy                 Copy the last response to the clipboard
  /md                   Re-render the last response as Markdown (needs rich)
  /stats                Session statistics
  /doctor               Check config, connectivity and dependencies
  /config               Show active configuration (secrets masked)
  /version              Show version
  /exit or /quit        Exit (auto-saves)

{C_HDR}Keyboard:{C_RESET}
  Tab                  Complete /commands (fuzzy), paths after ! and @
  →  / Ctrl+E          Accept the grey history suggestion
  Ctrl+R               Reverse-search input history
  Alt+Enter / Ctrl+J   Add a newline (multi-line input)
  Ctrl+L               Clear screen
  Ctrl+C               Cancel current input line
  Ctrl+D               Exit
  ↑ / ↓               Browse input history

{C_HDR}After a response with shell commands:{C_RESET}
  y / yes              Run all detected commands
  n / no               Skip
  e                    Edit each command before running
  <number>             Run only that numbered command (e.g. 2)
"""


_CODE_BLOCK = re.compile(r'```(?:bash|sh|shell|zsh)?\n([\s\S]*?)```', re.IGNORECASE)


def _extract_shell_commands(text: str) -> list[str]:
    """Extract shell commands from fenced bash/sh blocks in assistant output."""
    cmds: list[str] = []
    for m in _CODE_BLOCK.finditer(text or ''):
        block = m.group(1)
        for line in block.splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            cmds.append(line)
    return cmds


class _Spinner:
    """Animated spinner shown in stdout while waiting for the first streaming token."""

    _CHARS = '⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'

    def __init__(self, prefix: str = ''):
        self._prefix = prefix
        self._stop = threading.Event()
        self._thr: Optional[threading.Thread] = None

    def start(self):
        self._stop.clear()
        self._thr = threading.Thread(target=self._run, daemon=True)
        self._thr.start()

    def _run(self):
        i = 0
        while not self._stop.is_set():
            ch = self._CHARS[i % len(self._CHARS)]
            sys.stdout.write(f'\r{self._prefix}{C_AI}{ch}{C_RESET} {C_DIM}thinking…{C_RESET}')
            sys.stdout.flush()
            time.sleep(0.08)
            i += 1

    def stop(self):
        """Stop the spinner and erase its line."""
        self._stop.set()
        if self._thr:
            self._thr.join(timeout=0.5)
        sys.stdout.write('\r\033[K')
        sys.stdout.flush()


def _offer_run_commands(cmds: list[str]) -> None:
    """Show detected shell commands in a visual box and ask the user what to do."""
    W = 58
    fill = W - 15
    print(f'\n{C_HDR}┌─ Commands found {"─" * fill}┐{C_RESET}')
    for i, c in enumerate(cmds, 1):
        disp = c if len(c) <= W - 8 else c[:W - 11] + '…'
        pad = W - len(disp) - 6
        print(f'{C_HDR}│{C_RESET}  {C_DIM}[{i}]{C_RESET} {disp}{" " * max(0, pad)}{C_HDR}│{C_RESET}')
    print(f'{C_HDR}└{"─" * (W + 1)}┘{C_RESET}')
    print(f'  {C_DIM}[y] run all  [n] skip  [e] edit  [#] single  → {C_RESET}', end='', flush=True)

    try:
        ans = input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return

    if not ans or ans in ('n', 'no'):
        return

    if ans in ('y', 'yes'):
        to_run = list(cmds)
    elif ans.isdigit():
        idx = int(ans) - 1
        if 0 <= idx < len(cmds):
            to_run = [cmds[idx]]
        else:
            print(f'{C_WARN}  Index out of range.{C_RESET}')
            return
    elif ans == 'e':
        to_run = []
        for c in cmds:
            try:
                edited = input(f'  {C_DIM}Edit →{C_RESET} {c}\n        ').strip()
                to_run.append(edited if edited else c)
            except (EOFError, KeyboardInterrupt):
                break
    else:
        return

    print()
    for c in to_run:
        _run_shell(c)
    print()


def _run_shell(c: str) -> '_shell.ShellResult':
    """Run one command in the REPL's shell state and print a status line."""
    print(f'  {C_DIM}$ {c}{C_RESET}')
    try:
        res = _shell.run(c, _STATE)
    except Exception as exc:
        print(f'  {C_WARN}↳ error: {exc}{C_RESET}')
        return _shell.ShellResult(c, 1, str(exc))
    if res.code != 0:
        hint = '  (type /fix to let the AI repair it)' if res.captured else ''
        print(f'  {C_ERR}↳ exit {res.code}{C_RESET}{C_DIM} · {res.seconds:.1f}s{hint}{C_RESET}')
    elif res.seconds >= 2:
        print(f'  {C_DIM}↳ done in {res.seconds:.1f}s{C_RESET}')
    return res


def _print_status(conv: Conversation, model: str):
    tokens = conv.estimate_total_tokens()
    pct = int(100 * tokens / conv.max_context_tokens) if conv.max_context_tokens else 0
    bar_color = C_OK if pct < 60 else (C_WARN if pct < 85 else '\033[1;31m')
    print(f"{C_DIM}session {conv.session_id} · model {model} · "
          f"{len(conv.messages)} msgs · "
          f"{bar_color}{tokens}/{conv.max_context_tokens} tok ({pct}%){C_RESET}")


def _auto_compact_if_needed(agent: TerminalAgent, conv: Conversation):
    if not conv.should_compact():
        return
    print(f"\n{C_WARN}⚡ Context {conv.estimate_total_tokens()}/{conv.max_context_tokens} — auto-compacting & memorizing…{C_RESET}")

    def _memorize(msgs):
        from smart_terminal.memory import memorize_from_messages
        added = memorize_from_messages(
            msgs,
            chat_fn=lambda m: agent.chat_with_history(m, stream=False),
            source=conv.session_id,
        )
        if added:
            print(f"{C_OK}✓ Memorized {len(added)} fact(s):{C_RESET}")
            for e in added:
                print(f"  {C_DIM}• {e.get('text','')[:120]}{C_RESET}")

    try:
        summary = conv.compact(
            lambda msgs: agent.summarize_messages(msgs),
            keep_recent=4,
            memorizer=_memorize,
        )
        if summary:
            print(f"{C_OK}✓ Compacted. New size: {conv.estimate_total_tokens()} tokens{C_RESET}")
        else:
            print(f"{C_WARN}Compaction produced no summary; older messages dropped.{C_RESET}")
    except Exception as e:
        print(f"{C_WARN}Compaction failed: {e}. Continuing without compaction.{C_RESET}")


def _handle_slash(cmd: str, agent: TerminalAgent, conv: Conversation,
                  last_response: list[str]) -> Optional[Conversation]:
    """Handle a /command. Returns a new Conversation if switched, else None.
    Raises SystemExit on /exit.
    """
    parts = cmd.strip().split(maxsplit=1)
    head = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ''

    if head in ('/exit', '/quit'):
        try:
            conv.save()
            print(f"{C_DIM}Session saved. Bye.{C_RESET}")
        except Exception:
            pass
        raise SystemExit(0)

    if head == '/help':
        print(HELP_TEXT)
        return None

    if head == '/new':
        try:
            conv.save()
        except Exception:
            pass
        new_conv = Conversation(
            system_prompt=conv.system_prompt,
            max_context_tokens=conv.max_context_tokens,
            compact_threshold=conv.compact_threshold,
        )
        print(f"{C_OK}✓ New session: {new_conv.session_id}{C_RESET}")
        return new_conv

    if head == '/clear':
        conv.clear()
        print(f"{C_OK}✓ Conversation cleared (session {conv.session_id} kept){C_RESET}")
        return None

    if head == '/compact':
        if not conv.messages:
            print(f"{C_DIM}Nothing to compact.{C_RESET}")
            return None
        summary = conv.compact(lambda msgs: agent.summarize_messages(msgs), keep_recent=2)
        if summary:
            print(f"{C_OK}✓ Compacted.{C_RESET}\n{C_DIM}{summary[:400]}{C_RESET}")
        else:
            print(f"{C_WARN}No summary produced.{C_RESET}")
        return None

    if head == '/history':
        print(f"{C_HDR}Messages ({len(conv.messages)}):{C_RESET}")
        for i, m in enumerate(conv.messages, 1):
            role = m.get('role', '?')
            content = (m.get('content') or '').replace('\n', ' ')
            preview = content[:100] + ('…' if len(content) > 100 else '')
            tag = C_USER if role == 'user' else C_AI
            print(f"  {i:>3}. {tag}{role}{C_RESET} {preview}")
        if conv.compacted_summary:
            print(f"\n{C_DIM}[compacted summary: {len(conv.compacted_summary)} chars]{C_RESET}")
        return None

    if head == '/tokens':
        _print_status(conv, agent.model)
        return None

    if head == '/sessions':
        sessions = Conversation.list_sessions()
        if not sessions:
            print(f"{C_DIM}No saved sessions.{C_RESET}")
            return None
        print(f"{C_HDR}Saved sessions:{C_RESET}")
        for i, s in enumerate(sessions[:20], 1):
            active = ' (active)' if s['session_id'] == conv.session_id else ''
            print(f"  {i:>2}. {s['session_id']}{active} · "
                  f"{s['msg_count']} msgs · {s['preview']}")
        return None

    if head == '/load':
        if not arg:
            print(f"{C_WARN}Usage: /load <session_id or number from /sessions>{C_RESET}")
            return None
        sessions = Conversation.list_sessions()
        target = None
        # numeric index
        if arg.isdigit():
            idx = int(arg) - 1
            if 0 <= idx < len(sessions):
                target = sessions[idx]['path']
        if target is None:
            for s in sessions:
                if s['session_id'] == arg or s['session_id'].endswith(arg):
                    target = s['path']
                    break
        if target is None:
            print(f"{C_WARN}Session not found: {arg}{C_RESET}")
            return None
        try:
            conv.save()
        except Exception:
            pass
        try:
            new_conv = Conversation.load(target)
            print(f"{C_OK}✓ Loaded {new_conv.session_id} ({len(new_conv.messages)} messages){C_RESET}")
            return new_conv
        except Exception as e:
            print(f"{C_WARN}Failed to load: {e}{C_RESET}")
            return None

    if head == '/save':
        try:
            path = conv.save()
            print(f"{C_OK}✓ Saved to {path}{C_RESET}")
        except Exception as e:
            print(f"{C_WARN}Save failed: {e}{C_RESET}")
        return None
    if head == '/models':
        try:
            names = agent.list_models()
        except Exception as exc:
            print(f'{C_WARN}Failed to fetch models: {exc}{C_RESET}')
            return None
        if not names:
            print(f'{C_DIM}No models returned from {agent.api_base}{C_RESET}')
            return None
        print(f'{C_HDR}Available models at {agent.api_base}:{C_RESET}')
        for name in names:
            active = f'  {C_OK}← current{C_RESET}' if name == agent.model else ''
            print(f'  {C_DIM}•{C_RESET} {name}{active}')
        print(f'\n  Use /model <name> to switch.')
        return None
    if head == '/model':
        if not arg:
            print(f"Current model: {agent.model}")
            return None
        agent.model = arg
        print(f"{C_OK}✓ Model set to {arg}{C_RESET}")
        return None

    if head == '/system':
        if not arg:
            print(f"{C_HDR}Current system prompt:{C_RESET}\n{conv.system_prompt}")
            return None
        conv.system_prompt = arg
        print(f"{C_OK}✓ System prompt updated{C_RESET}")
        return None

    if head == '/reset':
        from smart_terminal.conversation import DEFAULT_SYSTEM_PROMPT
        conv.system_prompt = DEFAULT_SYSTEM_PROMPT
        print(f"{C_OK}✓ System prompt reset to default{C_RESET}")
        return None

    if head == '/exec':
        if not last_response or not last_response[-1]:
            print(f"{C_DIM}No previous response to extract commands from.{C_RESET}")
            return None
        cmds = _extract_shell_commands(last_response[-1])
        if not cmds:
            print(f"{C_DIM}No shell commands found in last response.{C_RESET}")
            return None
        _offer_run_commands(cmds)
        return None

    # ── Session management (new) ──

    if head == '/continue':
        try:
            conv.save()
        except Exception:
            pass
        latest = Conversation.latest()
        if latest is None:
            print(f"{C_DIM}No saved sessions to continue.{C_RESET}")
            return None
        print(f"{C_OK}✓ Continued {latest.session_id} ({len(latest.messages)} messages){C_RESET}")
        return latest

    if head == '/rename':
        if not arg:
            print(f"{C_WARN}Usage: /rename <new-name>{C_RESET}")
            return None
        # sanitize: keep it filesystem-safe
        new_id = re.sub(r'[^A-Za-z0-9._-]+', '-', arg).strip('-')
        if not new_id:
            print(f"{C_WARN}Invalid name.{C_RESET}")
            return None
        old_id = conv.session_id
        conv.session_id = new_id
        try:
            conv.save()
            # remove old session file if it existed
            old_path = SESSIONS_DIR / f"{old_id}.json"
            if old_path.exists() and old_id != new_id:
                try:
                    old_path.unlink()
                except Exception:
                    pass
            print(f"{C_OK}✓ Session renamed to {new_id}{C_RESET}")
        except Exception as e:
            print(f"{C_WARN}Rename failed: {e}{C_RESET}")
        return None

    if head == '/delete':
        if not arg:
            print(f"{C_WARN}Usage: /delete <session_id or # from /sessions>{C_RESET}")
            return None
        sessions = Conversation.list_sessions()
        target = None
        if arg.isdigit():
            idx = int(arg) - 1
            if 0 <= idx < len(sessions):
                target = sessions[idx]
        if target is None:
            for s in sessions:
                if s['session_id'] == arg or s['session_id'].endswith(arg):
                    target = s
                    break
        if target is None:
            print(f"{C_WARN}Session not found: {arg}{C_RESET}")
            return None
        if target['session_id'] == conv.session_id:
            print(f"{C_WARN}Can't delete the active session. Use /new first.{C_RESET}")
            return None
        try:
            target['path'].unlink()
            print(f"{C_OK}✓ Deleted {target['session_id']}{C_RESET}")
        except Exception as e:
            print(f"{C_WARN}Delete failed: {e}{C_RESET}")
        return None

    if head == '/export':
        from pathlib import Path as _P
        default_name = f"{conv.session_id}.md"
        dest = _P(arg) if arg else _P.cwd() / default_name
        try:
            with open(dest, 'w', encoding='utf-8') as f:
                f.write(f"# Smart Terminal session — {conv.session_id}\n\n")
                f.write(f"_Model: {agent.model} · messages: {len(conv.messages)}_\n\n")
                if conv.compacted_summary:
                    f.write("## Earlier summary\n\n")
                    f.write(conv.compacted_summary + "\n\n")
                for m in conv.messages:
                    role = m.get('role', '?').capitalize()
                    f.write(f"## {role}\n\n{m.get('content','')}\n\n")
            print(f"{C_OK}✓ Exported to {dest}{C_RESET}")
        except Exception as e:
            print(f"{C_WARN}Export failed: {e}{C_RESET}")
        return None

    # ── Long-term memory ──

    if head == '/memory':
        from smart_terminal.memory import list_memories
        mems = list_memories()
        if not mems:
            print(f"{C_DIM}No memories yet. Facts will be memorized automatically "
                  f"when the session compacts, or add one with /remember <text>.{C_RESET}")
            return None
        print(f"{C_HDR}Long-term memory ({len(mems)}):{C_RESET}")
        for m in mems[:50]:
            tag = '📌 ' if m.get('pinned') else '  '
            mid = m.get('id', '?')
            text = (m.get('text') or '').strip()
            tags = m.get('tags') or []
            tag_str = f" {C_DIM}[{', '.join(tags)}]{C_RESET}" if tags else ''
            print(f"  {tag}{C_DIM}{mid}{C_RESET} {text}{tag_str}")
        return None

    if head == '/search':
        if not arg:
            print(f"{C_WARN}Usage: /search <query>{C_RESET}")
            return None
        from smart_terminal.memory import list_memories
        mems = list_memories(query=arg)
        if not mems:
            print(f"{C_DIM}No memories matching '{arg}'.{C_RESET}")
            return None
        print(f"{C_HDR}Memories matching '{arg}':{C_RESET}")
        for m in mems[:30]:
            tag = '📌 ' if m.get('pinned') else '  '
            print(f"  {tag}{C_DIM}{m.get('id','?')}{C_RESET} {m.get('text','')}")
        return None

    if head == '/remember':
        if not arg:
            print(f"{C_WARN}Usage: /remember <text to remember>{C_RESET}")
            return None
        from smart_terminal.memory import add_memory
        entry = add_memory(arg, source=conv.session_id, pinned=False)
        if entry:
            print(f"{C_OK}✓ Remembered ({entry.get('id')}): {entry.get('text')}{C_RESET}")
        return None

    if head == '/pin':
        if not arg:
            print(f"{C_WARN}Usage: /pin <memory-id>{C_RESET}")
            return None
        from smart_terminal.memory import pin_memory
        if pin_memory(arg, True):
            print(f"{C_OK}✓ Pinned memory {arg}{C_RESET}")
        else:
            print(f"{C_WARN}Memory {arg} not found.{C_RESET}")
        return None

    if head == '/unpin':
        if not arg:
            print(f"{C_WARN}Usage: /unpin <memory-id>{C_RESET}")
            return None
        from smart_terminal.memory import pin_memory
        if pin_memory(arg, False):
            print(f"{C_OK}✓ Unpinned memory {arg}{C_RESET}")
        else:
            print(f"{C_WARN}Memory {arg} not found.{C_RESET}")
        return None

    if head == '/forget':
        if not arg:
            print(f"{C_WARN}Usage: /forget <memory-id>  (or /forget-all){C_RESET}")
            return None
        from smart_terminal.memory import remove_memory
        if remove_memory(arg):
            print(f"{C_OK}✓ Forgot memory {arg}{C_RESET}")
        else:
            print(f"{C_WARN}Memory {arg} not found.{C_RESET}")
        return None

    if head == '/forget-all':
        from smart_terminal.memory import clear_memories
        n = clear_memories(pinned_too=False)
        print(f"{C_OK}✓ Forgot {n} unpinned memories (pinned kept){C_RESET}")
        return None

    if head in ('/run',):
        if not arg:
            print(f"{C_WARN}Usage: /run <command>{C_RESET}")
            return None
        _run_shell(arg)
        return None

    if head == '/cd':
        _shell.try_builtin_cd('cd ' + (arg or '~'), _STATE)
        print(f"{C_DIM}{_shell.pretty_cwd(_STATE.cwd)}{C_RESET}")
        return None

    if head == '/pwd':
        print(_STATE.cwd)
        return None

    if head == '/clear-screen':
        print('\033[2J\033[H', end='')
        return None

    if head == '/copy':
        text = last_response[-1] if last_response else ''
        if not text:
            print(f"{C_DIM}Nothing to copy yet.{C_RESET}")
            return None
        if _copy_to_clipboard(text):
            print(f"{C_OK}✓ Copied {len(text)} chars to clipboard{C_RESET}")
        else:
            print(f"{C_WARN}No clipboard tool found (pbcopy / wl-copy / xclip / xsel / clip).{C_RESET}")
        return None

    if head == '/md':
        text = last_response[-1] if last_response else ''
        if not text:
            print(f"{C_DIM}No response to render.{C_RESET}")
            return None
        try:
            from rich.console import Console
            from rich.markdown import Markdown
            Console().print(Markdown(text))
        except ImportError:
            print(f"{C_WARN}Install 'rich' for Markdown rendering (pip install rich).{C_RESET}")
        return None

    if head == '/undo':
        removed = 0
        while conv.messages and removed < 2:
            role = conv.messages[-1].get('role')
            conv.messages.pop()
            removed += 1
            if role == 'user':
                break
        print(f"{C_OK}✓ Removed {removed} message(s){C_RESET}")
        return None

    if head == '/stats':
        users = sum(1 for m in conv.messages if m.get('role') == 'user')
        bots = sum(1 for m in conv.messages if m.get('role') == 'assistant')
        ran = len(_STATE.history)
        failed = sum(1 for r in _STATE.history if r.code != 0)
        print(f"{C_HDR}Session stats{C_RESET}")
        print(f"  session   {conv.session_id}")
        print(f"  model     {agent.model} ({getattr(agent, 'provider', '?')})")
        print(f"  messages  {users} you · {bots} assistant")
        print(f"  tokens    ~{conv.estimate_total_tokens()} / {conv.max_context_tokens}")
        print(f"  commands  {ran} run · {failed} failed")
        print(f"  cwd       {_shell.pretty_cwd(_STATE.cwd)}")
        return None

    if head == '/config':
        from smart_terminal.settings import SettingsManager
        print(f"{C_HDR}Active configuration{C_RESET}")
        print(f"  provider  {getattr(agent, 'provider', '?')}")
        print(f"  api_base  {agent.api_base}")
        print(f"  model     {agent.model}")
        for k, v in SettingsManager().masked().items():
            if k not in ('OLLAMA_API_BASE', 'OLLAMA_MODEL'):
                print(f"  {k.lower():<9} {v}")
        return None

    if head == '/version':
        from smart_terminal import __version__
        print(f"smart-terminal {__version__}")
        return None

    if head == '/doctor':
        from smart_terminal.doctor import run_doctor
        run_doctor(agent)
        return None

    # /fix and /explain and /retry are handled in run_chat (they send messages)
    print(f"{C_WARN}Unknown command: {head}. Type /help.{C_RESET}")
    return None


def _copy_to_clipboard(text: str) -> bool:
    import shutil as _sh
    for cmd in (['pbcopy'], ['wl-copy'], ['xclip', '-selection', 'clipboard'],
                ['xsel', '--clipboard', '--input'], ['clip']):
        if _sh.which(cmd[0]):
            try:
                subprocess.run(cmd, input=text, text=True, check=True)
                return True
            except Exception:
                continue
    return False


_AT_FILE = re.compile(r'(?<![\w/])@((?:~|\.{1,2})?/?[\w.\-/~]+)')
_MAX_ATTACH = 20000


def _expand_file_refs(text: str) -> str:
    """Attach the contents of any @file references to the message."""
    blocks = []
    for m in _AT_FILE.finditer(text):
        raw = m.group(1)
        path = os.path.abspath(os.path.join(_STATE.cwd, os.path.expanduser(raw)))
        if not os.path.isfile(path):
            continue
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                body = f.read(_MAX_ATTACH + 1)
        except OSError:
            continue
        if len(body) > _MAX_ATTACH:
            body = body[:_MAX_ATTACH] + '\n… (truncated)'
        blocks.append(f"\n\n--- file: {raw} ---\n{body}\n--- end {raw} ---")
        print(f"{C_DIM}  📎 attached {raw} ({len(body)} chars){C_RESET}")
    return text + ''.join(blocks)


def _fix_prompt(res) -> str:
    out = (res.output or '').strip()[-4000:] or '(no output captured)'
    return (f"I ran this command in `{_shell.pretty_cwd(_STATE.cwd)}` and it failed with exit code {res.code}:\n\n"
            f"```bash\n{res.command}\n```\n\nOutput:\n```\n{out}\n```\n\n"
            "Explain the cause in one or two sentences, then give the corrected command(s) "
            "in a ```bash block.")


class _ReplCompleter(Completer):
    """Fuzzy /command completion, path completion after `!`, `/cd`, `/run` and `@`."""

    def __init__(self):
        self._slash = FuzzyCompleter(WordCompleter(_SLASH_CMDS, sentence=True))
        self._paths = PathCompleter(expanduser=True,
                                    get_paths=lambda: [_STATE.cwd])

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if text.startswith('/') and ' ' not in text:
            yield from self._slash.get_completions(document, complete_event)
            return
        word = document.get_word_before_cursor(WORD=True)
        if word.startswith('@'):
            from prompt_toolkit.document import Document
            sub = Document(word[1:], len(word) - 1)
            yield from self._paths.get_completions(sub, complete_event)
            return
        if text.startswith(('!', '/cd ', '/run ')) and ' ' in text.lstrip('!'):
            from prompt_toolkit.document import Document
            sub = Document(word, len(word))
            yield from self._paths.get_completions(sub, complete_event)


def run_chat(agent: TerminalAgent, conv: Optional[Conversation] = None,
             resume: bool = False) -> int:
    """Run the continuous chat REPL.

    Args:
        agent:  configured TerminalAgent
        conv:   existing Conversation to use (else new one created)
        resume: if True and conv is None, resume latest session
    """
    if conv is None:
        if resume:
            loaded = Conversation.latest()
            conv = loaded or Conversation()
            if loaded:
                print(f"{C_DIM}Resumed {conv.session_id} ({len(conv.messages)} messages){C_RESET}")
        else:
            conv = Conversation()

    # Allow env override of context window
    ctx_env = os.getenv('SMART_TERM_CONTEXT_TOKENS')
    if ctx_env and ctx_env.isdigit():
        conv.max_context_tokens = int(ctx_env)

    # ── Header ────────────────────────────────────────────────────────────────
    model_short = agent.model.split(':')[0]
    from smart_terminal import __version__
    if not os.getenv('SMART_TERM_NO_BANNER'):
        print(f"""
{C_AI}   ▄▄▄▄ ▄▄▄▄▄{C_RESET}   {C_BOLD}Smart Terminal{C_RESET} {C_DIM}v{__version__}{C_RESET}
{C_AI}   ▀▄▄▄   █  {C_RESET}   {C_DIM}model    {C_RESET}{agent.model} {C_DIM}({getattr(agent, 'provider', 'ollama')}){C_RESET}
{C_AI}   ▄▄▄▀   █  {C_RESET}   {C_DIM}session  {C_RESET}{conv.session_id}
               {C_DIM}/help commands · !cmd runs shell · @file attaches · /fix repairs failures{C_RESET}
""")

    # ── Prompt-toolkit setup ──────────────────────────────────────────────────
    history_file = os.path.join(os.path.expanduser('~'), '.smart_terminal_chat_history')

    kb = KeyBindings()

    @kb.add('c-l')
    def _clear_screen(event):
        """Ctrl+L — clear the terminal."""
        event.app.renderer.clear()

    @kb.add('escape', 'enter')
    @kb.add('c-j')
    def _newline(event):
        """Alt+Enter / Ctrl+J — insert a literal newline into the input buffer."""
        event.current_buffer.insert_text('\n')

    @kb.add('c-e')
    def _accept_suggestion(event):
        """Ctrl+E — accept the history auto-suggestion (or go to end of line)."""
        b = event.current_buffer
        if b.suggestion:
            b.insert_text(b.suggestion.text)
        else:
            b.cursor_position = len(b.text)

    completer = _ReplCompleter()

    # Bottom toolbar — closure captures `conv` by reference so it updates when
    # the session is switched inside the while-loop.
    def _toolbar():
        tokens = conv.estimate_total_tokens()
        pct = int(100 * tokens / conv.max_context_tokens) if conv.max_context_tokens else 0
        bar = '█' * (pct // 10) + '░' * (10 - pct // 10)
        color = 'ansigreen' if pct < 60 else ('ansiyellow' if pct < 85 else 'ansired')
        sid = conv.session_id[:24]
        return HTML(
            f'<b><style fg="ansiblue">{sid}</style></b>  '
            f'<style fg="{color}">{bar} {pct}%</style>  '
            f'<style fg="ansigray">· {model_short} · {_shell.pretty_cwd(_STATE.cwd)[-30:]} · /help · !cmd</style>'
        )

    pt_session = PromptSession(
        history=FileHistory(history_file),
        completer=completer,
        complete_while_typing=False,   # Tab-only, no distracting pop-up while typing
        auto_suggest=AutoSuggestFromHistory(),
        enable_history_search=False,
        key_bindings=kb,
        bottom_toolbar=_toolbar,
        wrap_lines=True,
    )

    last_response: list[str] = ['']
    last_user: list[str] = ['']

    def _prompt_text():
        cwd = _shell.pretty_cwd(_STATE.cwd)
        if len(cwd) > 40:
            cwd = '…' + cwd[-39:]
        branch = _shell.git_branch(_STATE.cwd)
        br = f' {C_AI}⎇ {branch}{C_RESET}' if branch and _COL else (f' ({branch})' if branch else '')
        code = _STATE.last_code
        st = f' {C_ERR}✗{code}{C_RESET}' if code else ''
        arrow = C_ERR if code else C_USER
        return ANSI(f'\n{C_HDR}{cwd}{C_RESET}{br}{st}\n{arrow}❯{C_RESET} ')

    while True:
        # ── Prompt ───────────────────────────────────────────────────────────
        try:
            with patch_stdout():
                user_input = pt_session.prompt(_prompt_text)
        except KeyboardInterrupt:
            print(f"\n{C_DIM}(Ctrl-C to cancel · /exit to quit){C_RESET}")
            continue
        except EOFError:
            break

        if user_input is None:
            break
        user_input = user_input.strip()
        if not user_input:
            continue

        # ── Shell passthrough: !cmd ───────────────────────────────────────────
        if user_input.startswith('!') and len(user_input) > 1:
            _run_shell(user_input[1:].strip())
            continue

        # ── Message-producing slash commands ─────────────────────────────────
        low = user_input.lower()
        if low == '/fix':
            failed = _STATE.last_failed()
            if not failed:
                print(f"{C_DIM}No failed command in this session.{C_RESET}")
                continue
            user_input = _fix_prompt(failed)
            print(f"{C_DIM}  🔧 asking the AI to fix: {failed.command}{C_RESET}")
        elif low.startswith('/explain'):
            what = user_input[len('/explain'):].strip()
            if not what:
                print(f"{C_WARN}Usage: /explain <command>{C_RESET}")
                continue
            user_input = (f"Explain this shell command piece by piece, briefly, and flag anything risky:\n"
                          f"```bash\n{what}\n```")
        elif low == '/retry':
            if not last_user[0]:
                print(f"{C_DIM}Nothing to retry.{C_RESET}")
                continue
            if conv.messages and conv.messages[-1].get('role') == 'assistant':
                conv.messages.pop()
            if conv.messages and conv.messages[-1].get('role') == 'user':
                conv.messages.pop()
            user_input = last_user[0]
            print(f"{C_DIM}  ↻ retrying{C_RESET}")

        # ── Slash commands ────────────────────────────────────────────────────
        elif user_input.startswith('/'):
            try:
                maybe_new = _handle_slash(user_input, agent, conv, last_response)
                if maybe_new is not None:
                    conv = maybe_new
            except SystemExit:
                return 0
            continue

        # ── Pre-send auto-compact ─────────────────────────────────────────────
        _auto_compact_if_needed(agent, conv)

        # ── Stream response ───────────────────────────────────────────────────
        last_user[0] = user_input
        conv.add_user(_expand_file_refs(user_input))

        print()  # blank line before response

        spinner = _Spinner(prefix='  ')
        spinner.start()

        accumulated: list[str] = []
        first_token = False
        full = ''

        def on_token(tok: str):
            nonlocal first_token
            if not first_token:
                spinner.stop()
                sys.stdout.write(f'{C_AI}●{C_RESET} ')
                sys.stdout.flush()
                first_token = True
            sys.stdout.write(tok)
            sys.stdout.flush()
            accumulated.append(tok)

        try:
            full = agent.chat_with_history(
                conv.to_api_messages(), stream=True, on_token=on_token,
            )
        except KeyboardInterrupt:
            full = ''.join(accumulated)
            print(f"\n{C_WARN}(interrupted){C_RESET}")
        except Exception as exc:
            full = ''.join(accumulated)
            print(f"\n{C_WARN}Model error: {exc}{C_RESET}")
        finally:
            spinner.stop()
            if not first_token:
                # Spinner ended without any tokens (error / empty) — print bullet anyway
                sys.stdout.write(f'{C_AI}●{C_RESET} ')
                sys.stdout.flush()

        print()  # newline after streamed content
        print(f"{C_DIM}{'─' * 58}{C_RESET}")  # visual separator between turns

        response_text = full or ''.join(accumulated)

        if response_text.strip():
            conv.add_assistant(response_text)
            last_response[0] = response_text
            try:
                conv.save()
            except Exception:
                pass

            # ── Auto-offer shell commands found in the response ───────────
            cmds = _extract_shell_commands(response_text)
            if cmds:
                _offer_run_commands(cmds)
        else:
            print(f"{C_WARN}(empty response — model may be unreachable){C_RESET}")
            # Remove the dangling user message so history stays consistent
            if conv.messages and conv.messages[-1].get('role') == 'user':
                conv.messages.pop()

    # ── Graceful exit ─────────────────────────────────────────────────────────
    try:
        conv.save()
    except Exception:
        pass
    print(f"\n{C_DIM}Session saved. Bye.{C_RESET}")
    return 0
