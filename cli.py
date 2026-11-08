#!/usr/bin/env python3
"""Smart Terminal command-line entrypoint.

    smart-term [global options] [command] [args...]

With no command, starts the interactive chat REPL. Any text that isn't a
known command is treated as a smart instruction (diagnose → plan → confirm).
"""
from __future__ import annotations

import os
import shlex
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent

USAGE = """\
Usage: smart-term [options] [command] [args...]

Commands:
  (none)                 Interactive chat (shell passthrough, /help inside)
  chat | resume          Start a new chat / resume the latest session
  ask <question>         One-shot answer, no command execution (reads stdin if piped)
  term <instruction>     Natural language → shell commands, with approval
  do <instruction>       Same as term, auto-approves if AUTO_APPROVE_ALL
  explain <command>      Explain what a shell command does
  suggest <request>      Print a single shell command for the request (used by Ctrl+G)
  fix [command]          Run a command; if it fails, ask the AI for a fix
  web_search <query>     AI-synthesized web answer
  web_fetch <url>        Fetch and extract a page's text
  web_scrape <url>       Scrape a JS-heavy page (Playwright/Selenium)
  agent <name> <q>       Run an agent template (diagnose, explain, fix, plan)
  models                 List models from the configured provider
  sessions               List saved chat sessions
  doctor                 Check config, connectivity and dependencies
  configure|reconfigure  Run the setup wizard
  completion <bash|zsh|fish>  Print a shell completion script
  update                 git pull + reinstall dependencies
  uninstall              Remove launchers and shell integration
  version                Print the version
  <anything else>        Smart instruction: diagnose → research → plan → confirm

Options:
  -m, --model NAME       Override the model for this run
  -y, --yes              Auto-approve proposed commands (use with care)
  -n, --dry-run          Print commands instead of running them
      --sandbox          Run commands inside a Docker container
      --no-color         Disable colors (also: NO_COLOR=1)
      --clear-cache      Clear the web/wiki cache
  -v, --version          Print the version
  -h, --help             Show this help

Examples:
  smart-term                               # chat
  smart-term ask "what does chmod 640 mean"
  git diff | smart-term ask "write a commit message"
  smart-term term find files over 100MB in ~/Downloads
  smart-term fix npm run build
  smart-term update nodejs                 # smart instruction
"""

COMMANDS = [
    'chat', 'resume', 'ask', 'term', 'do', 'explain', 'suggest', 'fix', 'web_search', 'web_fetch',
    'web_scrape', 'agent', 'models', 'sessions', 'doctor', 'configure', 'reconfigure',
    'completion', 'update', 'uninstall', 'version', 'help', 'qa-run',
]


# ── helpers ──────────────────────────────────────────────────────────────────

def _parse_globals(argv: list[str]) -> tuple[dict, list[str]]:
    """Strip leading global options; stop at the first non-option word."""
    opts = {'model': None, 'yes': False, 'dry_run': False, 'sandbox': False,
            'clear_cache': False, 'help': False, 'version': False}
    rest = list(argv)
    while rest and rest[0].startswith('-'):
        a = rest.pop(0)
        if a in ('-h', '--help'):
            opts['help'] = True
        elif a in ('-v', '--version'):
            opts['version'] = True
        elif a in ('-y', '--yes'):
            opts['yes'] = True
        elif a in ('-n', '--dry-run'):
            opts['dry_run'] = True
        elif a == '--sandbox':
            opts['sandbox'] = True
        elif a == '--no-color':
            os.environ['NO_COLOR'] = '1'
        elif a == '--clear-cache':
            opts['clear_cache'] = True
        elif a in ('-m', '--model'):
            if not rest:
                sys.exit('error: --model needs a value')
            opts['model'] = rest.pop(0)
        elif a.startswith('--model='):
            opts['model'] = a.split('=', 1)[1]
        elif a == '--':
            break
        else:
            sys.exit(f'error: unknown option {a}\nTry: smart-term --help')
    # Also honour --clear-cache anywhere (backwards compatible)
    if '--clear-cache' in rest:
        rest.remove('--clear-cache')
        opts['clear_cache'] = True
    return opts, rest


def _read_stdin() -> str:
    if sys.stdin is None or sys.stdin.isatty():
        return ''
    try:
        data = sys.stdin.read()
    except Exception:
        return ''
    # Re-attach the terminal so later y/N prompts still work after a pipe.
    try:
        if os.name != 'nt' and os.path.exists('/dev/tty'):
            sys.stdin = open('/dev/tty')
    except OSError:
        pass
    return data[-20000:]


def _make_agent(opts: dict):
    from smart_terminal.agent import TerminalAgent
    from smart_terminal.settings import SettingsManager
    s = SettingsManager()
    base = s.get('OLLAMA_API_BASE') or os.getenv('OLLAMA_API_BASE') or ''
    model = opts.get('model') or s.get('OLLAMA_MODEL') or os.getenv('OLLAMA_MODEL') or ''
    if not (base and model):
        sys.exit('API base / model not configured. Run: smart-term configure')
    agent = TerminalAgent(api_base=base, model=model)
    if opts.get('dry_run'):
        agent.dry_run = True
    if opts.get('sandbox'):
        agent.sandbox_enabled = True
    return agent


def _require_configured() -> bool:
    from smart_terminal.setup import is_configured
    if is_configured() or (os.getenv('OLLAMA_API_BASE') and os.getenv('OLLAMA_MODEL')):
        return True
    from smart_terminal.ui import warn
    warn('Smart Terminal is not configured yet.')
    if sys.stdin.isatty():
        from smart_terminal.setup import run_setup
        run_setup()
        return True
    print('Run: smart-term configure')
    return False


def _stream_answer(agent, messages: list) -> str:
    from smart_terminal.ui import Spinner
    sp = Spinner().start()
    started = [False]

    def on_token(tok):
        if not started[0]:
            sp.stop()
            started[0] = True
        sys.stdout.write(tok)
        sys.stdout.flush()

    try:
        out = agent.chat_with_history(messages, stream=True, on_token=on_token)
    finally:
        sp.stop()
    if out and not out.endswith('\n'):
        print()
    return out


def _with_spinner(label: str, fn, *a):
    from smart_terminal.ui import Spinner
    with Spinner(label):
        return fn(*a)


def _run_qa_harness(slug: str | None = None, dry_run: bool = True) -> int:
    harness_path = REPO_ROOT / 'workshop' / 'qa-pipeline' / 'harness.py'
    if not harness_path.exists():
        print(f"harness.py not found at {harness_path}")
        return 1
    cmd = [sys.executable, str(harness_path)] + ([slug] if slug else [])
    log_dir = Path.home() / '.local' / 'share' / 'smart-terminal' / 'logs'
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f'qa-run-{datetime.now():%Y%m%d-%H%M%S}.log'
    print('QA run command:', ' '.join(shlex.quote(p) for p in cmd))
    print(f'Log file: {log_path}')
    if dry_run and input('Proceed to run QA pipeline? [y/N]: ').strip().lower() != 'y':
        print('Aborted by user.')
        return 0
    with open(log_path, 'w') as fh:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            for line in proc.stdout:
                print(line, end='')
                fh.write(line)
            proc.wait()
        except KeyboardInterrupt:
            proc.terminate()
            proc.wait()
    print(f"QA harness exited with code {proc.returncode}. Log: {log_path}")
    return proc.returncode


# ── command implementations ──────────────────────────────────────────────────

def cmd_ask(agent, question: str) -> int:
    piped = _read_stdin()
    if not question and not piped:
        sys.exit('Usage: smart-term ask <question>   (or pipe input into it)')
    content = question or 'Explain this input.'
    if piped:
        content += f"\n\nInput:\n```\n{piped}\n```"
    msgs = [{'role': 'system', 'content': 'You are a concise terminal assistant. Answer directly.'},
            {'role': 'user', 'content': content}]
    return 0 if _stream_answer(agent, msgs) else 1


def cmd_explain(agent, command: str) -> int:
    if not command:
        sys.exit('Usage: smart-term explain <command>')
    msgs = [{'role': 'system', 'content': 'You explain shell commands briefly, part by part, and flag risks.'},
            {'role': 'user', 'content': f'Explain:\n```bash\n{command}\n```'}]
    return 0 if _stream_answer(agent, msgs) else 1


def cmd_fix(agent, command: str, opts: dict) -> int:
    """Run *command* (or re-read the last failure); on failure ask for a fix."""
    from smart_terminal import shell
    from smart_terminal.ui import C, command_box, ok
    if not command:
        sys.exit('Usage: smart-term fix <command that fails>')
    state = shell.ShellState()
    res = shell.run(command, state, capture=True)
    if res.code == 0:
        ok(f'Command succeeded (exit 0) in {res.seconds:.1f}s; nothing to fix.')
        return 0
    print(f'\n{C.err}✗ exit {res.code}{C.reset} — asking the model for a fix…\n')
    prompt = (f"This command failed with exit code {res.code} on {agent.detected_os}:\n"
              f"```bash\n{command}\n```\nOutput:\n```\n{res.output[-4000:]}\n```\n"
              "Explain the cause in 1-2 sentences, then the corrected commands in one ```bash block.")
    answer = _stream_answer(agent, [{'role': 'user', 'content': prompt}])
    cmds = agent._extract_commands(answer or '')
    if not cmds:
        return res.code
    risk = agent._assess_risk(cmds)
    command_box(cmds, 'Suggested fix', risk)
    if opts.get('yes') or agent._interactive_approval(cmds, risk):
        agent._execute_commands(cmds)
        return 0
    print('Not applied.')
    return res.code


def cmd_suggest(agent, request: str) -> int:
    """Print exactly one shell command (no prose) for *request* to stdout."""
    if not request:
        return 2
    import re as _re
    prompt = (f"Target OS: {agent.detected_os}. Shell: {os.path.basename(os.getenv('SHELL', 'sh'))}. "
              f"Current directory: {os.getcwd()}\n"
              f"Write ONE shell command line that does: {request}\n"
              "Reply with only the command, no explanation, no code fences.")
    out = agent.chat_with_history([{'role': 'user', 'content': prompt}], stream=False) or ''
    m = _re.search(r'```(?:\w+)?\n(.*?)```', out, _re.S)
    if m:
        out = m.group(1)
    lines = [l.strip() for l in out.strip().splitlines() if l.strip() and not l.strip().startswith('#')]
    if not lines:
        return 1
    line = lines[0]
    if line.startswith('$ '):
        line = line[2:]
    print(line)
    return 0


def cmd_models(agent) -> int:
    try:
        names = _with_spinner('fetching models…', agent.list_models)
    except Exception as e:
        print(f'Failed to list models: {e}', file=sys.stderr)
        return 1
    for n in names:
        print(('* ' if n == agent.model else '  ') + n)
    return 0


def cmd_sessions() -> int:
    from smart_terminal.conversation import Conversation
    sessions = Conversation.list_sessions()
    if not sessions:
        print('No saved sessions.')
        return 0
    for i, s in enumerate(sessions[:30], 1):
        when = datetime.fromtimestamp(s['updated_at']).strftime('%Y-%m-%d %H:%M')
        print(f"{i:>3}. {when}  {s['session_id']:<36} {s['msg_count']:>3} msgs  {s['preview']}")
    return 0


def cmd_completion(shell_name: str) -> int:
    words = ' '.join(COMMANDS)
    opts = '-m --model -y --yes -n --dry-run --sandbox --no-color --clear-cache -v --version -h --help'
    if shell_name == 'bash':
        print(f'''_smart_term() {{
  local cur="${{COMP_WORDS[COMP_CWORD]}}"
  if [ "$COMP_CWORD" -eq 1 ] || [[ "$cur" == -* ]]; then
    COMPREPLY=( $(compgen -W "{words} {opts}" -- "$cur") )
  else
    COMPREPLY=( $(compgen -f -- "$cur") )
  fi
}}
complete -F _smart_term smart-term st''')
    elif shell_name == 'zsh':
        print(f'''#compdef smart-term st
_smart_term() {{
  if (( CURRENT == 2 )); then
    compadd -- {words} {opts}
  else
    _files
  fi
}}
compdef _smart_term smart-term st''')
    elif shell_name == 'fish':
        for w in COMMANDS:
            print(f"complete -c smart-term -n '__fish_use_subcommand' -a {w}")
        print("complete -c smart-term -s y -l yes -d 'Auto-approve'")
        print("complete -c smart-term -s n -l dry-run -d 'Do not execute'")
        print("complete -c smart-term -s m -l model -r -d 'Model override'")
    else:
        sys.exit('Usage: smart-term completion <bash|zsh|fish>')
    return 0


def cmd_update() -> int:
    script = REPO_ROOT / 'install.sh'
    if not (REPO_ROOT / '.git').exists():
        sys.exit(f'{REPO_ROOT} is not a git checkout; re-run the installer instead.')
    print(f'Updating {REPO_ROOT} …')
    r = subprocess.run(['git', '-C', str(REPO_ROOT), 'pull', '--ff-only'])
    if r.returncode != 0:
        return r.returncode
    if script.exists():
        return subprocess.run(['bash', str(script), '--update']).returncode
    return 0


def cmd_uninstall() -> int:
    script = REPO_ROOT / 'install.sh'
    if not script.exists():
        sys.exit('install.sh not found; cannot uninstall automatically.')
    return subprocess.run(['bash', str(script), '--uninstall']).returncode


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    load_dotenv()
    opts, args = _parse_globals(sys.argv[1:])

    from smart_terminal import __version__
    if opts['version']:
        print(f'smart-terminal {__version__}')
        return 0
    if opts['help']:
        print(USAGE)
        return 0

    cmd = args[0].lower().lstrip('!:') if args else ''
    rest_words = args[1:]
    rest = ' '.join(rest_words).strip()

    if opts['yes']:
        os.environ['AUTO_APPROVE_ALL'] = 'true'
    if opts['dry_run']:
        os.environ['DRY_RUN'] = 'true'

    # Commands that work without configuration
    if cmd in ('help',):
        print(USAGE)
        return 0
    if cmd == 'version':
        print(f'smart-terminal {__version__}')
        return 0
    if cmd == 'configure':
        from smart_terminal.setup import run_setup
        run_setup()
        return 0
    if cmd == 'reconfigure':
        from smart_terminal.setup import run_reconfigure
        run_reconfigure()
        return 0
    if cmd == 'completion':
        return cmd_completion(rest_words[0] if rest_words else '')
    if cmd == 'sessions':
        return cmd_sessions()
    if cmd == 'update':
        return cmd_update()
    if cmd == 'uninstall':
        return cmd_uninstall()
    if cmd == 'doctor':
        from smart_terminal.doctor import run_doctor
        return 1 if run_doctor() else 0
    if cmd in ('qa-run', 'qa_run'):
        return _run_qa_harness(slug=rest or None, dry_run=True)

    if not _require_configured():
        return 1
    agent = _make_agent(opts)

    if opts['clear_cache']:
        agent.clear_cache()
        if not cmd:
            return 0

    if not cmd or cmd in ('chat', 'resume'):
        if not sys.stdin.isatty() and not cmd:
            # `echo "question" | smart-term` → one-shot answer
            return cmd_ask(agent, '')
        from smart_terminal.chat import run_chat
        return run_chat(agent, resume=(cmd == 'resume'))

    if cmd == 'ask':
        return cmd_ask(agent, rest)
    if cmd == 'explain':
        return cmd_explain(agent, rest)
    if cmd == 'fix':
        return cmd_fix(agent, rest, opts)
    if cmd == 'models':
        return cmd_models(agent)
    if cmd == 'suggest':
        return cmd_suggest(agent, rest)

    if cmd in ('term', 'do'):
        if not rest:
            sys.exit(f'Usage: smart-term {cmd} <instruction>')
        agent.handle_instruction(rest, auto_mode=(cmd == 'do' or opts['yes']),
                                 session_auto_low=False, session_auto_all=opts['yes'])
        return 0

    if cmd in ('web_search', 'web_fetch', 'web_scrape'):
        if not rest:
            sys.exit(f'Usage: smart-term {cmd} <{"query" if cmd == "web_search" else "url"}>')
        label = {'web_search': 'searching…', 'web_fetch': 'fetching…', 'web_scrape': 'scraping…'}[cmd]
        _with_spinner(label, getattr(agent, f'handle_{cmd}'), rest)
        return 0

    if cmd == 'agent':
        if len(rest_words) < 2:
            names = ', '.join(sorted(getattr(agent, '_builtin_agents', {}).keys())) or 'none'
            sys.exit(f'Usage: smart-term agent <template> <question>\nTemplates: {names}')
        try:
            out = _with_spinner('thinking…', agent.run_coda_agent, rest_words[0], ' '.join(rest_words[1:]))
        except KeyError as e:
            sys.exit(str(e))
        if out:
            print(out)
        return 0

    # Fallback: whole argv is a smart instruction
    agent.handle_smart_instruction(' '.join(args))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main() or 0)
    except KeyboardInterrupt:
        print('\nCancelled.')
        sys.exit(130)
