# Smart Terminal

AI-powered CLI that turns natural-language instructions into shell commands with risk assessment, web search with AI-synthesized answers, and an agentic loop that can diagnose your system, research solutions, and execute fixes — all with human approval.

## Quick Start

```bash
pip3 install -r requirements.txt
smart-term configure        # first-run setup wizard
smart-term 'update nodejs'  # go
```

## First-Run Setup

On first use, Smart Terminal requires a one-time configuration. Run any command or explicitly:

```bash
smart-term configure
```

The setup wizard lets you pick a provider and model:

| # | Provider | Default API URL |
|---|----------|----------------|
| 1 | Ollama | `http://localhost:11434` |
| 2 | OpenAI | `https://api.openai.com/v1` |
| 3 | Anthropic (Claude) | `https://api.anthropic.com` |
| 4 | Groq | `https://api.groq.com/openai/v1` |
| 5 | Custom / Self-hosted | (you provide the URL) |

Configuration is saved at `~/.smart-terminal-config/config.json` and locked (immutable flag) to prevent accidental deletion.

To change settings later:

```bash
smart-term reconfigure
```

## Commands

### `term` — Natural-language → shell commands

Describe what you want in plain English. The agent proposes commands, shows a risk score, and waits for `[y/N]` approval before executing.

```bash
smart-term term install htop and run it
term install the latest version of python
```

### `do` — Auto-approve mode

Same as `term` but with auto-approval enabled for low-risk commands.

```bash
smart-term do list all docker containers
```

### Smart instructions (default fallback)

Any input that doesn't match a known command triggers the **agentic instruction handler** — a multi-step loop:

1. **Diagnose** — asks the LLM for diagnostic shell commands, runs them, captures output
2. **Research** — gathers web context (Wikipedia + DuckDuckGo) for the latest info
3. **Plan** — LLM synthesizes a status report and proposes exact shell commands
4. **Confirm** — shows proposed commands with risk score, waits for `[y/N]`
5. **Execute** — runs commands only after approval

```bash
smart-term update nodejs
smart-term check disk space
smart-term is my firewall configured correctly
```

### `web_search` — AI-synthesized web answers

Searches Wikipedia and DuckDuckGo, fetches and filters content from top results, then asks the LLM to synthesize a clean, direct answer.

```bash
web_search how many egyptian pyramids are there
web_search what is quantum computing
```

### `web_fetch` — Fetch and extract page content

Downloads a URL and extracts the main text content using trafilatura/BeautifulSoup.

```bash
web_fetch https://example.com/article
```

### `web_scrape` — Browser-based scraping

Uses Playwright or Selenium to scrape JavaScript-heavy pages.

```bash
web_scrape https://example.com/spa-page
```

### `agent` — Run agent templates

Runs a built-in agent template (diagnose, explain, fix, plan, or agent-manager) against a question.

```bash
smart-term agent diagnose why is my API returning 500
smart-term agent explain what does this cron expression mean
smart-term agent fix the build is failing with error X
smart-term agent plan migrate from MySQL to PostgreSQL
```

### `configure` / `reconfigure`

Works from any command position:

```bash
smart-term configure
term configure
web_search reconfigure
```

## Installation

### Dependencies

```bash
pip3 install -r requirements.txt
```

Core dependencies: `requests`, `prompt_toolkit`, `python-dotenv`, `ddgs`, `diskcache`, `beautifulsoup4`, `trafilatura`

Optional (for browser-based scraping): `playwright`, `selenium`

Minimal install (no web features):

```bash
pip3 install requests prompt_toolkit python-dotenv
```

### Wrappers

Install convenience commands to `/usr/local/bin`:

```bash
sudo ./install_smart_term.sh
```

This creates: `smart-term`, `term`, `do`, `web_search`, `web_fetch`, `web_scrape`.

The `st` wrapper provides a compact launcher:

```bash
st                                # interactive REPL
st web_search how old is Twitter
st term install htop
st update nodejs                  # smart instruction (default)
```

### Optional: zsh bang widget

Intercept `!`-prefixed lines at your zsh prompt:

```bash
bash install_bang_widget.sh
source ~/.zshrc
```

> **Note:** Some zsh configurations expand `!` for history, causing `event not found` errors. The installed wrappers are more reliable.

## Interactive Mode

Run without arguments for an interactive REPL:

```bash
smart-term
```

Shortcuts in interactive mode:
- **Ctrl+P** — toggle auto-approve for low-risk commands
- **Ctrl+O** — toggle auto-approve for all commands
- **Ctrl+C** — exit gracefully

Meta commands: `:models`, `:settings`, `:set model <name>`

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

## Project Structure

```
smart_terminal/
  agent.py       — core agent: model calls, web helpers, agentic loop
  settings.py    — settings manager with JSON persistence
  setup.py       — first-run setup wizard and config management
  agents/        — built-in agent templates (diagnose, explain, fix, plan)
cli.py           — CLI entrypoint (single-shot and REPL)
smart-term       — wrapper script
st               — compact launcher
tests/           — pytest test suite
```

## Security

This is an experimental tool. Always review commands before approving. The agent uses heuristics to flag high-risk commands (`rm -rf`, `dd`, `mkfs`, `sudo`, etc.) but it is not foolproof. The config file is locked with OS-level immutability flags to prevent accidental deletion.

## License

MIT
