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
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.key_binding import KeyBindings

from smart_terminal.platform_compat import user_shell_argv

from smart_terminal.agent import TerminalAgent
from smart_terminal.conversation import Conversation, SESSIONS_DIR

# ── ANSI palette ──────────────────────────────────────────────────────────────
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

# ── Slash-command list (drives Tab completion) ─────────────────────────────────
_SLASH_CMDS = [
    '/help', '/new', '/clear', '/compact', '/history', '/tokens',
    '/sessions', '/load', '/save', '/rename', '/delete', '/export',
    '/model', '/models', '/system', '/reset', '/exec', '/exit', '/quit',
    '/continue', '/memory', '/search', '/remember', '/pin', '/unpin',
    '/forget', '/forget-all',
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

{C_HDR}Actions:{C_RESET}
  /exec                 Extract shell commands from last response & run them
  /exit or /quit        Exit (auto-saves)

{C_HDR}Keyboard:{C_RESET}
  Tab                  Complete slash commands
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
        print(f'  {C_DIM}$ {c}{C_RESET}')
        try:
            result = subprocess.run(user_shell_argv(c), check=False)
            if result.returncode != 0:
                print(f'  {C_WARN}↳ exit {result.returncode}{C_RESET}')
        except Exception as exc:
            print(f'  {C_WARN}↳ error: {exc}{C_RESET}')
    print()


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
        import requests as _req
        url = f'{agent.api_base}/api/tags'
        try:
            r = _req.get(url, timeout=10)
            r.raise_for_status()
            data = r.json()
            models = data.get('models') or []
            if not models:
                print(f'{C_DIM}No models returned from {url}{C_RESET}')
                return None
            print(f'{C_HDR}Available models at {agent.api_base}:{C_RESET}')
            for m in models:
                name = m.get('name', '?')
                size = m.get('size', 0)
                size_str = f'{size / 1e9:.1f} GB' if size else ''
                active = f'  {C_OK}← current{C_RESET}' if name == agent.model else ''
                print(f'  {C_DIM}•{C_RESET} {name:<40} {C_DIM}{size_str}{C_RESET}{active}')
            print(f'\n  Use /model <name> to switch.')
        except Exception as exc:
            print(f'{C_WARN}Failed to fetch models: {exc}{C_RESET}')
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

    print(f"{C_WARN}Unknown command: {head}. Type /help.{C_RESET}")
    return None


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
    print(f"""
{C_HDR}╔══════════════════════════════════════════╗
║     Smart Terminal — Chat Mode           ║
╚══════════════════════════════════════════╝{C_RESET}
{C_DIM}Model  : {agent.model}
Session: {conv.session_id}
Tip    : Tab completes /commands · Alt+Enter for newline · Ctrl+L clears screen{C_RESET}
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

    completer = WordCompleter(
        _SLASH_CMDS,
        pattern=re.compile(r'(/\w*)'),
        sentence=True,
    )

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
            f'<style fg="ansigray">· {model_short}  · /help</style>'
        )

    pt_session = PromptSession(
        history=FileHistory(history_file),
        completer=completer,
        complete_while_typing=False,   # Tab-only, no distracting pop-up while typing
        key_bindings=kb,
        bottom_toolbar=_toolbar,
        wrap_lines=True,
    )

    last_response: list[str] = ['']

    while True:
        # ── Prompt ───────────────────────────────────────────────────────────
        try:
            with patch_stdout():
                user_input = pt_session.prompt(ANSI(f'\n{C_USER}❯{C_RESET} '))
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

        # ── Slash commands ────────────────────────────────────────────────────
        if user_input.startswith('/'):
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
        conv.add_user(user_input)

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
