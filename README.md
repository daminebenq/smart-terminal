# Smart Terminal — Prototype

Interactive CLI that turns natural-language "!term" requests into shell commands via an Ollama model, asks for per-command approval, performs risk assessment, and (with approval) executes commands in zsh on macOS.

Quick start

1. Copy `.env.example` to `.env` and set `OLLAMA_API_BASE` and `OLLAMA_MODEL`.
2. Install dependencies and run the CLI:

```bash
pip3 install -r requirements.txt
python3 cli.py
```

Usage

- Begin an input line with `!term` followed by your instruction. The agent will propose commands and ask for approval.
- Begin with `!do` to request auto-approval mode (you'll still be prompted unless you explicitly enable auto-approve via the interactive shortcut).
Dependencies
------------
Install Python dependencies (recommended in a venv):

```bash
pip install -r requirements.txt
```

The project uses `duckduckgo2` (preferred DuckDuckGo client) and `diskcache` for caching Wikipedia/Wikidata lookups. If `diskcache` is not available the agent will fall back to a small JSON cache.

If you prefer to install only runtime essentials, the minimal set is:

```bash
pip install requests prompt_toolkit python-dotenv
```

To get the improved DuckDuckGo client and caching behavior, install the full requirements:

```bash
pip install -r requirements.txt
```

Shortcuts

- In interactive mode pressing Ctrl+P toggles session auto-approve for low-risk commands.
- Pressing Ctrl+O toggles session auto-approve for all commands.

Wrapper

There is a small wrapper script `smart-term` in the project root. Make it executable and place it in your PATH for convenient usage:

```bash
chmod +x smart-term
./install_smart_term.sh
smart-term 'install htop and run it'
```

If you'd like a shorter command `term`, copy or symlink `/usr/local/bin/smart-term` to `/usr/local/bin/term`.

Shell integration and leading-! triggers

If you want to type commands starting with an exclamation mark directly at your zsh prompt (for example `!web_search how old is Twitter`), you have two options:

1) Install the provided wrappers (recommended) — these create commands you can run without needing the leading `!` and also support the `!`-style trigger when forwarded by the wrapper installer.

```bash
sudo ./install_smart_term.sh
source ~/.zshrc   # reload if you appended the zsh widget
```

This will install `smart-term` and convenience wrappers: `term`, `do`, `web_search`, `web_fetch`, `web_scrape` under `/usr/local/bin` so you can call them directly, e.g. `web_search how old is Twitter`.

2) Optional zsh widget — intercept leading `!` lines and forward them to `smart-term`:

Run `bash install_bang_widget.sh` to append a small widget to `~/.zshrc`. Then reload your shell with `source ~/.zshrc`. The widget will run `smart-term` in the background for lines that start with `!`.

Simplest usage — `st` wrapper

A single, compact launcher `st` is provided for the simplest possible workflow. After running the installer, you can use:

```bash
st                        # interactive mode (same as python3 cli.py)
st web_search how old is Twitter
st web_fetch https://example.com
st term install htop and run it
st !web_search how old is Twitter   # also supported
```

Caveats: Some zsh configurations perform history expansion on `!` before widgets run, which results in `zsh: event not found` errors. Installing the wrappers (recommended) is the most reliable approach. The optional zsh widget is provided as a convenience but may not work in every environment.

Security

This is an experimental prototype. Always review commands before approving. The tool performs simple heuristics to flag high-risk commands (e.g., `rm -rf`, `dd`, `mkfs`, `sudo`) but it is not foolproof.
