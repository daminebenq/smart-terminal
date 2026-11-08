# Smart Terminal

AI-powered CLI that turns natural-language instructions into shell commands with risk assessment, web search with AI-synthesized answers, and an agentic loop that can diagnose your system, research solutions, and execute fixes — all with human approval.

## Install (one command)

```bash
curl -fsSL https://raw.githubusercontent.com/daminebenq/smart-terminal/main/install.sh | bash
```

Or from a checkout: `./install.sh`. The installer:

- finds Python 3.9+ and builds a private virtualenv (no system packages touched, PEP 668 safe)
- installs `smart-term`, `st`, `term`, `do`, `web_search`, `web_fetch`, `web_scrape` into `~/.local/bin`
- adds tab completion, a **Ctrl+G** widget and an `ai` helper for zsh, bash and fish
- runs the setup wizard (or configures non-interactively from flags)

Every option is a flag on the same script:

| Option | What it does |
|---|---|
| `--minimal` / `--standard` / `--full` | Core only · core + web search (default) · everything |
| `--with-web` | Flask web UI (`make web-ui`) |
| `--with-browser` | Playwright + Selenium, downloads Chromium |
| `--with-dev` | pytest |
| `--macos-app [--launch-agent]` | Build the native macOS app (optionally start at login) |
| `--system` | Launchers in `/usr/local/bin` (sudo if needed) |
| `--dir DIR` / `--bin-dir DIR` | Code location / launcher location |
| `--python PATH` · `--branch` · `--repo` | Interpreter and source to use |
| `--provider P --model M [--api-url U]` | Configure without prompts; key from `$SMART_TERM_API_KEY` |
| `--configure` / `--skip-config` | Force the wizard / skip configuration |
| `--no-shell-integration` · `--no-aliases` | Skip rc-file hooks · only install `smart-term` and `st` |
| `--update` · `--uninstall [--purge]` | Upgrade in place · remove (and optionally delete config/sessions) |
| `-y` · `-q` · `-h` | Non-interactive · quiet · help |

Examples:

```bash
curl -fsSL .../install.sh | bash -s -- --full
SMART_TERM_API_KEY=sk-... ./install.sh --provider openai --model gpt-4o-mini -y
./install.sh --provider ollama --model llama3.2:3b -y
./install.sh --uninstall --purge
```

Shell rc files get a single marked block (`# >>> smart-terminal >>>`) that `--uninstall` removes cleanly.
Re-running the installer is safe.

## What it feels like

```
~/code/api  main ✗1
❯ !npm test                       # run any shell command; cd persists
  ↳ exit 1 · 4.2s  (type /fix to let the AI repair it)
❯ /fix                            # AI reads the failing command + output
● The test runner can't find jest. Install it:
╭─ Commands found ─────────────────────────────╮
│ [1] npm i -D jest                            │
╰──────────────────────────────────────────────╯
  [y] run all  [n] skip  [e] edit  [#] single  →
❯ review @src/server.ts for bugs  # @file attaches file contents
```

From your normal shell:

```bash
smart-term ask "how do I undo the last git commit"
git diff | smart-term ask "write a commit message"     # pipes work
smart-term explain "tar -xzvf a.tgz -C /tmp"
smart-term fix npm run build        # runs it; on failure proposes a fix
smart-term doctor                   # config, connectivity, deps
# type "find files bigger than 1GB here" at the prompt, press Ctrl+G → real command
```

## First-Run Setup

The installer runs the wizard for you. To change settings later:

```bash
smart-term reconfigure
```

| # | Provider | Default API URL |
|---|----------|----------------|
| 1 | Ollama | `http://localhost:11434` |
| 2 | OpenAI | `https://api.openai.com/v1` |
| 3 | Anthropic (Claude) | `https://api.anthropic.com` |
| 4 | Groq | `https://api.groq.com/openai/v1` |
| 5 | Custom / Self-hosted | (you provide the URL; OpenAI-compatible if it ends in `/v1`) |

All five providers are supported end to end (chat, streaming, `models`). Configuration is saved at
`~/.smart-terminal-config/config.json` and locked with an immutable flag.

## Commands

```
smart-term [options] [command] [args...]

  (none) | chat | resume   Interactive chat
  ask <question>           One-shot answer (reads piped stdin)
  term <instruction>       Natural language → shell commands, with approval
  do <instruction>         Same, auto-approve if AUTO_APPROVE_ALL / -y
  explain <command>        Explain a shell command
  suggest <request>        Print one shell command (powers Ctrl+G)
  fix <command>            Run a command, propose a fix if it fails
  web_search | web_fetch | web_scrape
  agent <template> <q>     diagnose · explain · fix · plan · agent-manager
  models · sessions · doctor · configure · reconfigure
  completion <bash|zsh|fish> · update · uninstall · version
  <anything else>          Smart instruction: diagnose → research → plan → confirm

Options: -m/--model NAME  -y/--yes  -n/--dry-run  --sandbox  --no-color  --clear-cache  -v  -h
```

### Smart instructions (default)

Any input that doesn't match a command triggers the agentic loop:

1. **Diagnose**: the LLM proposes read-only checks, which run and are captured
2. **Research**: Wikipedia + DuckDuckGo context
3. **Plan**: status report plus exact commands
4. **Confirm**: commands shown in a box with a risk badge, `[y/N]`
5. **Execute**: only after approval

```bash
smart-term update nodejs
smart-term is my firewall configured correctly
```

## Interactive Mode

`smart-term` with no arguments opens the chat REPL:

- **Prompt** shows the working directory, git branch and last exit code
- **`!cmd`** runs a shell command; `cd` persists; editors/pagers get the real TTY
- **`/fix`** sends the last failing command and its output to the model
- **`@path`** attaches a file (Tab completes paths)
- **Commands in replies** are detected and offered: `[y]` all, `[n]`, `[e]` edit, `[#]` one
- Fuzzy **Tab** completion for `/commands`, grey **history suggestions** (→ or Ctrl+E to accept)
- Bottom toolbar with session, context usage, model and cwd
- Long-term memory and automatic context compaction

Slash commands: `/help /new /continue /clear /compact /history /tokens /sessions /load /save /rename
/delete /export /memory /search /remember /pin /unpin /forget /forget-all /models /model /system
/reset /exec /run /cd /pwd /fix /explain /retry /undo /copy /md /stats /doctor /config /version /exit`

Keys: `Alt+Enter`/`Ctrl+J` newline · `Ctrl+L` clear · `Ctrl+R` history search · `Ctrl+D` exit

Set `NO_COLOR=1` to disable colours and `SMART_TERM_NO_BANNER=1` to hide the banner.

## Native macOS App

```bash
./install.sh --macos-app --launch-agent     # builds SmartTerminalApp, serves http://smartterminal:5001
```

## Configuration

### Environment variables (`.env`)

Copy `.env.example` to `.env` to override settings:

```
OLLAMA_API_BASE=https://your-ollama-proxy.example.com
OLLAMA_MODEL=llama3.2:3b
OLLAMA_API_KEY=
```

The global config (`~/.smart-terminal-config/config.json`) takes precedence for provider settings. Environment variables and `.env` can still override individual values.

### Settings

Additional toggles available via `.env` or SettingsManager:

- `DRY_RUN` — print commands without executing
- `AUTO_APPROVE_ZERO_RISK` — auto-approve risk-0 commands (default: true)
- `AUTO_APPROVE_LOW_RISK_THRESHOLD` — risk score threshold for auto-approve (default: 20)
- `SANDBOX` / `SANDBOX_IMAGE` — run commands in a Docker container
- `LOG_LEVEL` — logging verbosity (default: INFO)
- `WEB_MIN_INTERVAL` — minimum seconds between web requests (default: 0.5)
- `WIKI_CACHE_TTL` — Wikipedia cache TTL in seconds (default: 86400)

## Web UI

```bash
./install.sh --with-web     # once
make web-ui                 # http://localhost:5001
```

The web UI provides:
- **Dashboard**: View all saved conversations with search capabilities
- **Chat Interface**: Interactive chat for each conversation
- **Session Management**: Create, rename, delete, and export conversations
- **Real-time Messaging**: Send messages and get responses from the AI
- **Export to Markdown**: Download conversations as formatted markdown files

### Web UI Features
- 🎨 Modern, responsive interface with Bootstrap
- 🔍 Search conversations by content
- 💬 Interactive chat interface with syntax highlighting
- 📱 Mobile-friendly design
- 🔄 Real-time message sending
- 📊 Token usage tracking
- 🗂️ Session organization and management

### Web UI API Endpoints
- `/api/sessions` - List all conversations
- `/api/sessions/<id>` - Get specific conversation
- `/api/chat/<id>/message` - Send a message
- `/api/sessions/new` - Create new conversation
- `/api/sessions/<id>/export` - Export conversation as markdown

## Project Structure

```
smart_terminal/
  agent.py       — core agent: model calls, web helpers, agentic loop
  settings.py    — settings manager with JSON persistence
  setup.py       — first-run setup wizard and config management
  agents/        — built-in agent templates (diagnose, explain, fix, plan)
  providers.py   — Ollama / OpenAI-compatible / Anthropic adapters
  shell.py       — REPL shell execution (persistent cwd, output capture)
  ui.py          — colors, spinner, command boxes
  doctor.py      — `smart-term doctor` health checks
  conversation.py — conversation persistence and management
  chat.py        — CLI chat REPL
install.sh       — one-shot installer / updater / uninstaller
cli.py           — CLI entrypoint (subcommands, global options)
web_app.py       — Flask web application for conversation management
templates/       — HTML templates for web UI
  base.html      — base template
  index.html     — dashboard page
  chat.html      — chat interface
static/          — CSS and JavaScript assets
  style.css      — custom styles
  app.js         — JavaScript utilities
smart-term       — wrapper script
st               — compact launcher
start_web_ui.sh  — web UI launcher script
tests/           — pytest test suite
```

## Security

This is an experimental tool. Always review commands before approving. The agent uses heuristics to flag high-risk commands (`rm -rf`, `dd`, `mkfs`, `sudo`, etc.) but it is not foolproof. The config file is locked with OS-level immutability flags to prevent accidental deletion.

## License

MIT
