#!/usr/bin/env python3
import os
import sys
from dotenv import load_dotenv
from smart_terminal.agent import TerminalAgent
from smart_terminal.settings import SettingsManager
from smart_terminal.setup import is_configured, run_setup, run_reconfigure
import requests
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.patch_stdout import patch_stdout
import time
import threading
import subprocess
import shlex
from datetime import datetime
from pathlib import Path


def _run_qa_harness(slug: str | None = None, dry_run: bool = True):
    """Run the workshop QA harness in a subprocess with confirmation and logging.

    - slug: optional flow slug to run specific flow
    - dry_run: if True, prompt for confirmation before running
    Returns: subprocess exit code (or 0 on abort)
    """
    repo_root = Path(__file__).resolve().parent
    harness_path = repo_root / 'workshop' / 'qa-pipeline' / 'harness.py'
    if not harness_path.exists():
        print(f"harness.py not found at {harness_path}")
        return 1

    cmd = [sys.executable, str(harness_path)]
    if slug:
        cmd.append(slug)

    log_dir = Path.home() / '.local' / 'share' / 'smart-terminal' / 'logs'
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d-%H%M%S')
    log_path = log_dir / f'qa-run-{ts}.log'

    print('QA run command:')
    print(' '.join(shlex.quote(p) for p in cmd))
    print(f'Log file: {log_path}')

    if dry_run:
        try:
            ans = input('Proceed to run QA pipeline? [y/N]: ').strip().lower()
        except EOFError:
            ans = 'n'
        if ans != 'y':
            print('Aborted by user.')
            return 0

    # Stream subprocess output to log file and stdout
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
    cost_report = repo_root / 'workshop' / 'qa-pipeline' / 'output' / 'cost-report.json'
    if cost_report.exists():
        print(f'Cost report: {cost_report}')
    return proc.returncode


def _require_configured():
    """Check if smart-terminal is configured. If not, print a message and return False."""
    if is_configured():
        return True
    print('Smart Terminal is not configured yet.')
    print('Run: smart-term configure')
    return False


def main():
    load_dotenv()
    base = os.getenv("OLLAMA_API_BASE")
    model = os.getenv("OLLAMA_MODEL")

    # Handle 'configure' / 'reconfigure' as any argument position
    # e.g. smart-term configure, web_search configure, term reconfigure
    argv_lower = [a.lower().lstrip('!:') for a in sys.argv[1:]]
    if 'reconfigure' in argv_lower:
        run_reconfigure()
        return
    if 'configure' in argv_lower:
        run_setup()
        return

    # Support a simple maintenance flag to clear caches used by the agent
    if '--clear-cache' in sys.argv:
        if not _require_configured():
            return
        settings = SettingsManager()
        base = settings.get('OLLAMA_API_BASE') or base
        model = settings.get('OLLAMA_MODEL') or model
        agent = TerminalAgent(api_base=base or '', model=model or '')
        agent.clear_cache()
        return

    # Gate: require configuration for all other commands
    if not _require_configured():
        return

    settings = SettingsManager()

    # Only print the interactive header when running without single-shot args
    if len(sys.argv) == 1:
        print("Smart Terminal prototype — type '!term <instruction>' or '!do <instruction>'")
        print("Type ':models' to list available models from the Ollama API, ':settings' to view, ':set model <name>' to change model")
        print("Type 'exit' or Ctrl-C to quit.")

    # session-level auto-approve flags toggled by shortcuts
    session_auto_low = False
    session_auto_all = False

    # prompt_toolkit session with key bindings for Ctrl+P (toggle low-risk) and Ctrl+O (toggle all)
    kb = KeyBindings()

    @kb.add('c-p')
    def _(event):
        nonlocal session_auto_low
        session_auto_low = not session_auto_low
        print(f"\nSession auto-approve low-risk = {session_auto_low}")

    @kb.add('c-o')
    def _(event):
        nonlocal session_auto_all
        session_auto_all = not session_auto_all
        print(f"\nSession auto-approve all = {session_auto_all}")

    history_file = settings.get('HISTORY_FILE') or os.path.join(os.path.expanduser('~'), '.smart_terminal_history')
    session = PromptSession('> ', key_bindings=kb, history=FileHistory(history_file))

    # If CLI args provided, treat them as a single-shot instruction.
    if len(sys.argv) > 1:
        raw = ' '.join(sys.argv[1:]).strip()
        trigger = raw.split(' ', 1)[0]
        rest = raw.split(' ', 1)[1] if ' ' in raw else ''
        base = settings.get('OLLAMA_API_BASE') or base
        model = settings.get('OLLAMA_MODEL') or model
        agent = TerminalAgent(api_base=base, model=model)

        if trigger in ('!term', 'term', '!term'):
            instruction = rest
            if instruction:
                if not (base and model):
                    print('Please set OLLAMA_API_BASE and OLLAMA_MODEL (or use :set) to run model-based commands')
                    return
                agent.handle_instruction(instruction, auto_mode=False,
                                         session_auto_low=False, session_auto_all=False)
            else:
                print('Please provide an instruction after !term')
            return

        if trigger in ('!do', 'do', '!do'):
            instruction = rest
            if instruction:
                if not (base and model):
                    print('Please set OLLAMA_API_BASE and OLLAMA_MODEL (or use :set) to run model-based commands')
                    return
                agent.handle_instruction(instruction, auto_mode=True,
                                         session_auto_low=False, session_auto_all=False)
            else:
                print('Please provide an instruction after !do')
            return

        if trigger in ('!web_search', 'web_search', '!web_search'):
            if not rest:
                print('Usage: web_search <query>')
                return
            stop_event = threading.Event()

            def _spinner(ev):
                chars = '|/-\\'
                i = 0
                sys.stdout.write('Searching... ')
                sys.stdout.flush()
                while not ev.is_set():
                    sys.stdout.write(chars[i % len(chars)])
                    sys.stdout.flush()
                    time.sleep(0.12)
                    sys.stdout.write('\b')
                    i += 1
                sys.stdout.write('\n')

            t = threading.Thread(target=_spinner, args=(stop_event,), daemon=True)
            t.start()
            try:
                agent.handle_web_search(rest)
            finally:
                stop_event.set()
            return

        if trigger in ('!web_fetch', 'web_fetch', '!web_fetch'):
            if not rest:
                print('Usage: web_fetch <url>')
                return
            stop_event = threading.Event()

            def _spinner(ev):
                chars = '|/-\\'
                i = 0
                sys.stdout.write('Fetching... ')
                sys.stdout.flush()
                while not ev.is_set():
                    sys.stdout.write(chars[i % len(chars)])
                    sys.stdout.flush()
                    time.sleep(0.12)
                    sys.stdout.write('\b')
                    i += 1
                sys.stdout.write('\n')

            t = threading.Thread(target=_spinner, args=(stop_event,), daemon=True)
            t.start()
            try:
                agent.handle_web_fetch(rest)
            finally:
                stop_event.set()
            return

        if trigger in ('!web_scrape', 'web_scrape', '!web_scrape'):
            if not rest:
                print('Usage: web_scrape <url>')
                return
            stop_event = threading.Event()

            def _spinner(ev):
                chars = '|/-\\'
                i = 0
                sys.stdout.write('Scraping... ')
                sys.stdout.flush()
                while not ev.is_set():
                    sys.stdout.write(chars[i % len(chars)])
                    sys.stdout.flush()
                    time.sleep(0.12)
                    sys.stdout.write('\b')
                    i += 1
                sys.stdout.write('\n')

            t = threading.Thread(target=_spinner, args=(stop_event,), daemon=True)
            t.start()
            try:
                agent.handle_web_scrape(rest)
            finally:
                stop_event.set()
            return

        if trigger in ('qa-run', 'qa_run', '!qa-run', '!qa_run'):
            slug = rest or None
            _run_qa_harness(slug=slug, dry_run=True)
            return

        if trigger in ('!agent', 'agent', '!agent'):
            # usage: agent <template> <question>
            if not rest:
                print('Usage: agent <template> <question>')
                return
            parts = rest.split(' ', 1)
            if len(parts) < 2:
                print('Usage: agent <template> <question>')
                return
            name, question = parts[0], parts[1]
            try:
                out = agent.run_coda_agent(name, question)
                if out:
                    print(out)
            except KeyError as e:
                print(e)
            except Exception as e:
                print('Error running agent:', e)
            return

        # Fallback: treat entire argv as a smart instruction (diagnose → plan → confirm → execute)
        agent.handle_smart_instruction(raw)
        return

    # Interactive REPL
    while True:
        try:
            with patch_stdout():
                line = session.prompt().strip()
        except KeyboardInterrupt:
            print()
            break
        except EOFError:
            break

        if not line:
            continue
        if line.lower() in ("exit", "quit"):
            break

        if line.startswith(':'):
            parts = line[1:].split()
            if not parts:
                continue
            cmd = parts[0]
            if cmd == 'settings':
                print('Current settings:')
                for k, v in settings.masked().items():
                    print(f'{k} = {v}')
                continue
            if cmd == 'set' and len(parts) >= 3:
                key = parts[1]
                val = ' '.join(parts[2:])
                env_key = key.upper()
                if env_key == 'MODEL':
                    env_key = 'OLLAMA_MODEL'
                if env_key == 'BASE':
                    env_key = 'OLLAMA_API_BASE'
                if env_key == 'APIKEY':
                    env_key = 'OLLAMA_API_KEY'
                settings.set(env_key, val)
                print(f'Set {env_key} = {val}')
                continue
            if cmd == 'models':
                api_base = settings.get('OLLAMA_API_BASE')
                if not api_base:
                    print('Set OLLAMA_API_BASE first (use :set base <url>)')
                    continue
                try:
                    r = requests.get(api_base.rstrip('/') + '/api/tags', timeout=10)
                    r.raise_for_status()
                    j = r.json()
                    models = j.get('models') if isinstance(j, dict) else None
                    if not models:
                        print('No models field in response; raw:')
                        print(j)
                        continue
                    for m in models:
                        print(m.get('name'))
                except Exception as e:
                    print('Error fetching models:', e)
                continue
            print('Unknown :command')

        # Extended triggers
        if line.startswith('!term') or line.startswith('!do'):
            auto_mode = line.startswith('!do')
            instruction = line.split(' ', 1)[1] if ' ' in line else ''
            if not instruction:
                print('Please provide an instruction after the trigger word.')
                continue
            base = settings.get('OLLAMA_API_BASE') or base
            model = settings.get('OLLAMA_MODEL') or model
            agent = TerminalAgent(api_base=base, model=model)
            agent.handle_instruction(instruction, auto_mode=auto_mode,
                                     session_auto_low=session_auto_low,
                                     session_auto_all=session_auto_all)
            continue

        if line.startswith('!web_fetch') or line.startswith('!web_scrape') or line.startswith('!web_search'):
            parts = line.split(' ', 1)
            cmd = parts[0]
            arg = parts[1] if len(parts) > 1 else ''
            if not arg:
                print(f'Usage: {cmd} <url or query>')
                continue
            base = settings.get('OLLAMA_API_BASE') or base
            model = settings.get('OLLAMA_MODEL') or model
            agent = TerminalAgent(api_base=base, model=model)
            if cmd == '!web_fetch':
                agent.handle_web_fetch(arg)
            elif cmd == '!web_scrape':
                agent.handle_web_scrape(arg)
            else:
                agent.handle_web_search(arg)
            continue

        if line.startswith('!qa-run') or line.startswith('!qa_run') or line.startswith('qa-run'):
            parts = line.split(' ', 1)
            slug = parts[1] if len(parts) > 1 else None
            _run_qa_harness(slug=slug, dry_run=True)
            continue

        if line.startswith('!agent') or line.startswith('agent '):
            parts = line.split(' ', 2)
            if len(parts) < 3:
                print('Usage: !agent <template> <question>')
                continue
            _, name, question = parts
            try:
                ag = TerminalAgent(api_base=settings.get('OLLAMA_API_BASE') or base, model=settings.get('OLLAMA_MODEL') or model)
                out = ag.run_coda_agent(name, question)
                if out:
                    print(out)
            except KeyError as e:
                print(e)
            except Exception as e:
                print('Error running agent:', e)
            continue

        # Plain chat fallback — use smart instruction handler (diagnose → plan → confirm → execute)
        try:
            base = settings.get('OLLAMA_API_BASE') or base
            model = settings.get('OLLAMA_MODEL') or model
            agent = TerminalAgent(api_base=base, model=model)
            agent.handle_smart_instruction(line)
        except Exception as e:
            print('Error:', e)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\nCancelled.')
