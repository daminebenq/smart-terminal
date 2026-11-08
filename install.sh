#!/usr/bin/env bash
# Smart Terminal — one-shot installer.
#
#   curl -fsSL https://raw.githubusercontent.com/daminebenq/smart-terminal/main/install.sh | bash
#   curl -fsSL .../install.sh | bash -s -- --full --provider ollama --model llama3.2:3b
#   ./install.sh --help
#
# Works on macOS (bash 3.2+) and Linux (incl. PEP 668 distros). Everything is
# installed into a private virtualenv; nothing touches the system Python.
set -euo pipefail

VERSION="0.2.0"
REPO_URL="${SMART_TERM_REPO:-https://github.com/daminebenq/smart-terminal.git}"
BRANCH="${SMART_TERM_BRANCH:-main}"
INSTALL_DIR="${SMART_TERM_HOME:-}"
BIN_DIR=""
PYTHON_BIN="${PYTHON:-}"
CONFIG_DIR="$HOME/.smart-terminal-config"
SHELL_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/smart-terminal"

PROFILE="standard"          # minimal | standard | full
WITH_WEB=0                  # Flask web UI
WITH_BROWSER=0              # Playwright + Selenium (+ chromium)
WITH_DEV=0                  # pytest
WITH_MACOS_APP=0
WITH_LAUNCH_AGENT=0
SYSTEM_INSTALL=0
SHELL_INTEGRATION=1
ALIASES=1
CONFIGURE="auto"            # auto | wizard | skip
PROVIDER=""
API_URL=""
MODEL=""
ASSUME_YES=0
MODE="install"              # install | update | uninstall
PURGE=0
QUIET=0

# ── output ───────────────────────────────────────────────────────────────────
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  B=$'\033[1m'; D=$'\033[2m'; R=$'\033[0m'; G=$'\033[1;32m'; Y=$'\033[1;33m'; E=$'\033[1;31m'; C=$'\033[1;36m'
else
  B=""; D=""; R=""; G=""; Y=""; E=""; C=""
fi
step() { [ "$QUIET" = 1 ] || printf '%s==>%s %s%s%s\n' "$C" "$R" "$B" "$*" "$R"; }
ok()   { [ "$QUIET" = 1 ] || printf '  %s✓%s %s\n' "$G" "$R" "$*"; }
warn() { printf '  %s!%s %s\n' "$Y" "$R" "$*" >&2; }
die()  { printf '%s✗ %s%s\n' "$E" "$*" "$R" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

usage() {
  cat <<EOF
${B}Smart Terminal installer v$VERSION${R}

Usage: install.sh [options]

${B}Profiles${R}
  --minimal              Core only (chat, term, ask) — no web search libs
  --standard             Core + web search/fetch (default)
  --full                 Everything: web UI, browser scraping, dev tools
  --with-web             Add the Flask web UI
  --with-browser         Add Playwright/Selenium and download Chromium
  --with-dev             Add pytest
  --macos-app            Also build & install the native macOS app (macOS only)
  --launch-agent         With --macos-app: start the app at login

${B}Locations${R}
  --dir DIR              Where to put the code (default: this checkout, or ~/.smart-terminal)
  --bin-dir DIR          Where to put launchers (default: ~/.local/bin)
  --system               Put launchers in /usr/local/bin (uses sudo if needed)
  --python PATH          Python interpreter to build the venv with (>= 3.9)
  --branch NAME          Git branch to install (default: $BRANCH)
  --repo URL             Git repository (default: $REPO_URL)

${B}Shell${R}
  --no-shell-integration Skip completions, Ctrl+G widget and 'ai' helper
  --no-aliases           Only install smart-term and st (skip term, web_search, …)

${B}Configuration${R}
  --provider NAME        ollama | openai | anthropic | groq | custom (non-interactive setup)
  --api-url URL          API base URL (defaults per provider)
  --model NAME           Model name
                         API key is read from \$SMART_TERM_API_KEY (never pass it as an argument)
  --configure            Always run the interactive setup wizard
  --skip-config          Don't configure now

${B}Maintenance${R}
  --update               Pull latest code and reinstall with the same layout
  --uninstall            Remove launchers, venv and shell integration
  --purge                With --uninstall: also delete config, sessions and memory
  -y, --yes              Don't ask questions (assume defaults)
  -q, --quiet            Less output
  -h, --help             Show this help

${B}Examples${R}
  ./install.sh
  ./install.sh --full --system
  SMART_TERM_API_KEY=sk-... ./install.sh --provider openai --model gpt-4o-mini -y
  ./install.sh --uninstall --purge
EOF
}

# ── args ─────────────────────────────────────────────────────────────────────
need_arg() { [ $# -ge 2 ] && [ -n "$2" ] || die "option $1 requires a value"; }
while [ $# -gt 0 ]; do
  case "$1" in
    --minimal)  PROFILE="minimal" ;;
    --standard) PROFILE="standard" ;;
    --full)     PROFILE="full"; WITH_WEB=1; WITH_BROWSER=1; WITH_DEV=1 ;;
    --with-web) WITH_WEB=1 ;;
    --with-browser) WITH_BROWSER=1 ;;
    --with-dev) WITH_DEV=1 ;;
    --macos-app) WITH_MACOS_APP=1 ;;
    --launch-agent) WITH_LAUNCH_AGENT=1 ;;
    --dir) need_arg "$@"; INSTALL_DIR="$2"; shift ;;
    --bin-dir) need_arg "$@"; BIN_DIR="$2"; shift ;;
    --system) SYSTEM_INSTALL=1 ;;
    --python) need_arg "$@"; PYTHON_BIN="$2"; shift ;;
    --branch) need_arg "$@"; BRANCH="$2"; shift ;;
    --repo) need_arg "$@"; REPO_URL="$2"; shift ;;
    --no-shell-integration) SHELL_INTEGRATION=0 ;;
    --no-aliases) ALIASES=0 ;;
    --provider) need_arg "$@"; PROVIDER="$2"; shift ;;
    --api-url) need_arg "$@"; API_URL="$2"; shift ;;
    --model) need_arg "$@"; MODEL="$2"; shift ;;
    --api-key|--api-key=*) die "don't pass API keys on the command line; use SMART_TERM_API_KEY=... instead" ;;
    --configure) CONFIGURE="wizard" ;;
    --skip-config) CONFIGURE="skip" ;;
    --update) MODE="update" ;;
    --uninstall) MODE="uninstall" ;;
    --purge) PURGE=1 ;;
    -y|--yes) ASSUME_YES=1 ;;
    -q|--quiet) QUIET=1 ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown option: $1 (see --help)" ;;
  esac
  shift
done

OS="$(uname -s)"
# Interactive only if we can talk to a terminal (works under `curl | bash`).
if [ "$ASSUME_YES" = 0 ] && [ -r /dev/tty ] && [ -w /dev/tty ] && (: </dev/tty) 2>/dev/null; then
  INTERACTIVE=1
else
  INTERACTIVE=0
fi

ask_yn() { # ask_yn "question" default(y|n)
  local def="$2" ans
  [ "$INTERACTIVE" = 1 ] || { [ "$def" = y ]; return; }
  printf '  %s?%s %s [%s] ' "$C" "$R" "$1" "$([ "$def" = y ] && echo Y/n || echo y/N)" >/dev/tty
  read -r ans </dev/tty || ans=""
  ans="${ans:-$def}"
  case "$ans" in y|Y|yes|YES) return 0 ;; *) return 1 ;; esac
}

# ── locations ────────────────────────────────────────────────────────────────
SCRIPT_DIR=""
if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "${BASH_SOURCE[0]}" ]; then
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi
if [ -z "$INSTALL_DIR" ]; then
  if [ -n "$SCRIPT_DIR" ] && [ -f "$SCRIPT_DIR/cli.py" ] && [ -d "$SCRIPT_DIR/smart_terminal" ]; then
    INSTALL_DIR="$SCRIPT_DIR"
  elif [ -f "$SHELL_DIR/install.env" ]; then
    INSTALL_DIR="$(sed -n 's/^INSTALL_DIR=//p' "$SHELL_DIR/install.env" | tr -d '"')"
  fi
  INSTALL_DIR="${INSTALL_DIR:-$HOME/.smart-terminal}"
fi
case "$INSTALL_DIR" in /*) ;; *) INSTALL_DIR="$(pwd)/$INSTALL_DIR" ;; esac

if [ -z "$BIN_DIR" ]; then
  if [ "$SYSTEM_INSTALL" = 1 ]; then BIN_DIR="/usr/local/bin"
  elif [ -f "$SHELL_DIR/install.env" ]; then BIN_DIR="$(sed -n 's/^BIN_DIR=//p' "$SHELL_DIR/install.env" | tr -d '"')"
  fi
  BIN_DIR="${BIN_DIR:-$HOME/.local/bin}"
fi
VENV="$INSTALL_DIR/.venv"
WRAPPERS="smart-term st"
[ "$ALIASES" = 1 ] && WRAPPERS="$WRAPPERS term do web_search web_fetch web_scrape"
MARK_BEGIN="# >>> smart-terminal >>>"
MARK_END="# <<< smart-terminal <<<"

SUDO=""
bin_writable() { mkdir -p "$BIN_DIR" 2>/dev/null && [ -w "$BIN_DIR" ]; }
pick_sudo() {
  if bin_writable; then SUDO=""
  elif have sudo; then SUDO="sudo"; $SUDO mkdir -p "$BIN_DIR"
  else die "$BIN_DIR is not writable and sudo is unavailable (try --bin-dir ~/.local/bin)"
  fi
}

rc_files() {
  local f
  for f in "$HOME/.zshrc" "$HOME/.bashrc" "$HOME/.bash_profile"; do
    [ -f "$f" ] && echo "$f"
  done
  return 0
}

strip_rc_block() { # remove our marked block from a file (portable, no sed -i)
  local f="$1" tmp
  [ -f "$f" ] || return 0
  grep -qF "$MARK_BEGIN" "$f" || return 0
  tmp="$(mktemp)"
  awk -v b="$MARK_BEGIN" -v e="$MARK_END" '$0==b{skip=1;next} $0==e{skip=0;next} !skip' "$f" >"$tmp"
  cat "$tmp" >"$f" && rm -f "$tmp"
}

# ── uninstall ────────────────────────────────────────────────────────────────
do_uninstall() {
  step "Uninstalling Smart Terminal"
  pick_sudo
  local w
  for w in smart-term st term "do" web_search web_fetch web_scrape; do
    if [ -f "$BIN_DIR/$w" ] && grep -q "smart-terminal launcher" "$BIN_DIR/$w" 2>/dev/null; then
      $SUDO rm -f "$BIN_DIR/$w" && ok "removed $BIN_DIR/$w"
    fi
  done
  local f
  for f in $(rc_files); do strip_rc_block "$f" && ok "cleaned $f"; done
  [ -f "$HOME/.config/fish/conf.d/smart-terminal.fish" ] && rm -f "$HOME/.config/fish/conf.d/smart-terminal.fish"
  rm -rf "$SHELL_DIR" && ok "removed $SHELL_DIR"
  if [ -d "$VENV" ]; then rm -rf "$VENV" && ok "removed $VENV"; fi
  if [ "$PURGE" = 1 ]; then
    if [ -f "$CONFIG_DIR/config.json" ]; then
      if [ "$OS" = Darwin ]; then chflags nouchg "$CONFIG_DIR/config.json" 2>/dev/null || true
      else chattr -i "$CONFIG_DIR/config.json" 2>/dev/null || true; fi
    fi
    rm -rf "$CONFIG_DIR" && ok "purged $CONFIG_DIR (config, sessions, memory)"
  else
    ok "kept $CONFIG_DIR (use --purge to delete config, sessions and memory)"
  fi
  if [ "$INSTALL_DIR" = "$HOME/.smart-terminal" ] && [ -d "$INSTALL_DIR/.git" ]; then
    ok "source checkout left at $INSTALL_DIR (rm -rf it to remove completely)"
  fi
  printf '\n%sDone.%s Open a new shell to finish.\n' "$G" "$R"
}

# ── steps ────────────────────────────────────────────────────────────────────
find_python() {
  local c v
  for c in "$PYTHON_BIN" python3.13 python3.12 python3.11 python3.10 python3.9 python3; do
    [ -n "$c" ] || continue
    have "$c" || continue
    v="$("$c" -c 'import sys; print("%d %d" % sys.version_info[:2])' 2>/dev/null)" || continue
    set -- $v
    if [ "$1" -eq 3 ] && [ "$2" -ge 9 ]; then PYTHON_BIN="$(command -v "$c")"; return 0; fi
  done
  return 1
}

install_python_hint() {
  case "$OS" in
    Darwin) echo "brew install python@3.12   (or download from python.org)" ;;
    Linux)
      if have apt-get; then echo "sudo apt-get install -y python3 python3-venv python3-pip"
      elif have dnf; then echo "sudo dnf install -y python3"
      elif have pacman; then echo "sudo pacman -S python"
      else echo "install Python 3.9+ with your package manager"; fi ;;
    *) echo "install Python 3.9+" ;;
  esac
}

fetch_source() {
  if [ -f "$INSTALL_DIR/cli.py" ] && [ -d "$INSTALL_DIR/smart_terminal" ]; then
    if [ "$MODE" = update ] && [ -d "$INSTALL_DIR/.git" ]; then
      step "Updating source in $INSTALL_DIR"
      git -C "$INSTALL_DIR" pull --ff-only || warn "git pull failed; continuing with current checkout"
    fi
    ok "source: $INSTALL_DIR"
    return
  fi
  have git || die "git is required to download Smart Terminal"
  step "Cloning $REPO_URL ($BRANCH) → $INSTALL_DIR"
  if [ -e "$INSTALL_DIR" ] && [ -n "$(ls -A "$INSTALL_DIR" 2>/dev/null)" ]; then
    die "$INSTALL_DIR exists and is not a Smart Terminal checkout; pick another --dir"
  fi
  git clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$INSTALL_DIR"
  ok "cloned"
}

build_venv() {
  step "Python environment"
  find_python || die "Python 3.9+ not found. Install it: $(install_python_hint)"
  ok "using $PYTHON_BIN ($("$PYTHON_BIN" -V 2>&1))"
  if [ ! -x "$VENV/bin/python" ]; then
    "$PYTHON_BIN" -m venv "$VENV" 2>/dev/null || {
      warn "venv creation failed."
      [ "$OS" = Linux ] && have apt-get && warn "on Debian/Ubuntu/Kali: sudo apt-get install -y python3-venv"
      die "could not create $VENV"
    }
    ok "created $VENV"
  else
    ok "reusing $VENV"
  fi
  local PIP="$VENV/bin/python -m pip"
  local pipq="-q"; [ "$QUIET" = 1 ] || pipq="-q --progress-bar off"
  $PIP install $pipq --upgrade pip >/dev/null 2>&1 || warn "pip self-upgrade failed (continuing)"

  local core="requests prompt_toolkit python-dotenv rich"
  local web="ddgs diskcache beautifulsoup4 trafilatura"
  local pkgs="$core"
  [ "$PROFILE" != minimal ] && pkgs="$pkgs $web"
  [ "$WITH_WEB" = 1 ] && pkgs="$pkgs flask flask-cors"
  [ "$WITH_BROWSER" = 1 ] && pkgs="$pkgs playwright selenium"
  [ "$WITH_DEV" = 1 ] && pkgs="$pkgs pytest"
  step "Installing packages ($PROFILE$( [ "$WITH_WEB" = 1 ] && echo ' +web')$( [ "$WITH_BROWSER" = 1 ] && echo ' +browser')$( [ "$WITH_DEV" = 1 ] && echo ' +dev'))"
  # shellcheck disable=SC2086
  $PIP install $pipq --upgrade $pkgs || die "pip install failed"
  ok "installed: $pkgs"
  if [ "$WITH_BROWSER" = 1 ]; then
    step "Downloading Chromium for Playwright"
    "$VENV/bin/python" -m playwright install chromium || warn "playwright browser download failed (web_scrape will fall back to Selenium)"
  fi
}

write_launchers() {
  step "Launchers → $BIN_DIR"
  pick_sudo
  local tmp w
  tmp="$(mktemp)"
  cat >"$tmp" <<EOF
#!/usr/bin/env bash
# smart-terminal launcher (generated by install.sh v$VERSION)
export PYTHONPATH="$INSTALL_DIR\${PYTHONPATH:+:\$PYTHONPATH}"
exec "$VENV/bin/python" "$INSTALL_DIR/cli.py" "\$@"
EOF
  $SUDO install -m 0755 "$tmp" "$BIN_DIR/smart-term"
  ok "smart-term"
  for w in $WRAPPERS; do
    [ "$w" = smart-term ] && continue
    if [ "$w" = st ]; then
      printf '#!/usr/bin/env bash\n# smart-terminal launcher (alias)\nexec "%s/smart-term" "$@"\n' "$BIN_DIR" >"$tmp"
    else
      if [ -e "$BIN_DIR/$w" ] && ! grep -q "smart-terminal launcher" "$BIN_DIR/$w" 2>/dev/null; then
        warn "$BIN_DIR/$w exists and isn't ours; skipping"; continue
      fi
      printf '#!/usr/bin/env bash\n# smart-terminal launcher (alias)\nexec "%s/smart-term" %s "$@"\n' "$BIN_DIR" "$w" >"$tmp"
    fi
    $SUDO install -m 0755 "$tmp" "$BIN_DIR/$w"
    ok "$w"
  done
  rm -f "$tmp"
}

write_shell_integration() {
  mkdir -p "$SHELL_DIR"
  cat >"$SHELL_DIR/install.env" <<EOF
INSTALL_DIR="$INSTALL_DIR"
BIN_DIR="$BIN_DIR"
VERSION="$VERSION"
EOF
  local path_line=""
  case ":$PATH:" in *":$BIN_DIR:"*) ;; *) path_line="case \":\$PATH:\" in *\":$BIN_DIR:\"*) ;; *) export PATH=\"$BIN_DIR:\$PATH\" ;; esac" ;; esac

  if [ "$SHELL_INTEGRATION" = 0 ]; then
    if [ -n "$path_line" ]; then
      local f
      for f in $(rc_files); do
        strip_rc_block "$f"
        printf '%s\n%s\n%s\n' "$MARK_BEGIN" "$path_line" "$MARK_END" >>"$f"
      done
    fi
    return
  fi
  step "Shell integration"
  "$BIN_DIR/smart-term" completion bash >"$SHELL_DIR/completion.bash" 2>/dev/null || true
  "$BIN_DIR/smart-term" completion zsh  >"$SHELL_DIR/completion.zsh"  2>/dev/null || true

  cat >"$SHELL_DIR/init.zsh" <<'EOF'
# Smart Terminal zsh integration (generated)
if [[ -o interactive ]]; then
  (( $+functions[compdef] )) || { autoload -Uz compinit && compinit -i; }
  source "${0:A:h}/completion.zsh" 2>/dev/null
  # Ctrl+G: turn the plain-English text on the prompt into a shell command (review, then Enter)
  _smart_term_suggest() {
    [[ -z "$BUFFER" ]] && return
    local req="$BUFFER" out
    BUFFER="$req  ⏳"; zle redisplay
    out="$(smart-term suggest "$req" 2>/dev/null)"
    if [[ -n "$out" ]]; then BUFFER="$out"; else BUFFER="$req"; fi
    CURSOR=${#BUFFER}; zle redisplay
  }
  zle -N _smart_term_suggest
  bindkey '^G' _smart_term_suggest
  # ai <question>  — quick one-shot answer; `cmd | ai "explain"` works too
  (( $+commands[ai] || $+aliases[ai] || $+functions[ai] )) || ai() { smart-term ask "$*"; }
fi
EOF
  cat >"$SHELL_DIR/init.bash" <<'EOF'
# Smart Terminal bash integration (generated)
if [[ $- == *i* ]]; then
  _st_dir="$(dirname "${BASH_SOURCE[0]}")"
  source "$_st_dir/completion.bash" 2>/dev/null
  unset _st_dir
  # Ctrl+G: turn the text on the prompt into a shell command (review, then Enter)
  _smart_term_suggest() {
    [[ -z "$READLINE_LINE" ]] && return
    local out; out="$(smart-term suggest "$READLINE_LINE" 2>/dev/null)"
    [[ -n "$out" ]] && READLINE_LINE="$out" && READLINE_POINT=${#READLINE_LINE}
  }
  bind -x '"\C-g": _smart_term_suggest' 2>/dev/null
  type ai >/dev/null 2>&1 || ai() { smart-term ask "$*"; }
fi
EOF
  local f
  for f in $(rc_files); do
    strip_rc_block "$f"
    {
      echo "$MARK_BEGIN"
      [ -n "$path_line" ] && echo "$path_line"
      case "$f" in
        *zshrc) echo "[ -f \"$SHELL_DIR/init.zsh\" ] && source \"$SHELL_DIR/init.zsh\"" ;;
        *)      echo "[ -n \"\${BASH_VERSION:-}\" ] && [ -f \"$SHELL_DIR/init.bash\" ] && source \"$SHELL_DIR/init.bash\"" ;;
      esac
      echo "$MARK_END"
    } >>"$f"
    ok "hooked $f"
  done
  if [ -z "$(rc_files)" ]; then
    local def="$HOME/.bashrc"; case "${SHELL:-}" in *zsh) def="$HOME/.zshrc" ;; esac
    touch "$def"; write_shell_integration_one "$def" "$path_line"
  fi
  if have fish || [ -d "$HOME/.config/fish" ]; then
    mkdir -p "$HOME/.config/fish/conf.d"
    {
      echo "# Smart Terminal (generated)"
      echo "fish_add_path -g $BIN_DIR"
      "$BIN_DIR/smart-term" completion fish 2>/dev/null || true
      echo 'function ai; smart-term ask $argv; end'
    } >"$HOME/.config/fish/conf.d/smart-terminal.fish"
    ok "fish: ~/.config/fish/conf.d/smart-terminal.fish"
  fi
  ok "Ctrl+G turns plain English into a command · 'ai <question>' · tab completion"
}

write_shell_integration_one() { # fallback when no rc file existed
  local f="$1" path_line="$2"
  {
    echo "$MARK_BEGIN"
    [ -n "$path_line" ] && echo "$path_line"
    case "$f" in
      *zshrc) echo "[ -f \"$SHELL_DIR/init.zsh\" ] && source \"$SHELL_DIR/init.zsh\"" ;;
      *)      echo "[ -f \"$SHELL_DIR/init.bash\" ] && source \"$SHELL_DIR/init.bash\"" ;;
    esac
    echo "$MARK_END"
  } >>"$f"
  ok "hooked $f"
}

configure() {
  [ "$CONFIGURE" = skip ] && return
  local py="$VENV/bin/python"
  if [ -n "$PROVIDER" ] || [ -n "$MODEL" ]; then
    [ -n "$MODEL" ] || die "--model is required with --provider"
    step "Writing configuration ($PROVIDER${PROVIDER:+ / }$MODEL)"
    SMART_TERM_PROVIDER_IN="${PROVIDER:-ollama}" SMART_TERM_URL_IN="$API_URL" SMART_TERM_MODEL_IN="$MODEL" \
      PYTHONPATH="$INSTALL_DIR" "$py" - <<'PY'
import os, sys
from smart_terminal.setup import configure_noninteractive
try:
    configure_noninteractive(os.environ['SMART_TERM_PROVIDER_IN'], os.environ.get('SMART_TERM_URL_IN', ''),
                             os.environ['SMART_TERM_MODEL_IN'], os.environ.get('SMART_TERM_API_KEY', ''))
except ValueError as e:
    sys.exit(f'configuration error: {e}')
PY
    ok "saved to $CONFIG_DIR/config.json"
    return
  fi
  if [ -f "$CONFIG_DIR/config.json" ] && [ "$CONFIGURE" != wizard ]; then
    ok "existing configuration kept ($CONFIG_DIR/config.json)"
    return
  fi
  if [ "$INTERACTIVE" = 1 ] && { [ "$CONFIGURE" = wizard ] || ask_yn "Run the setup wizard now?" y; }; then
    PYTHONPATH="$INSTALL_DIR" "$py" "$INSTALL_DIR/cli.py" configure </dev/tty
  else
    warn "not configured yet — run: smart-term configure"
  fi
}

install_macos_app() {
  [ "$WITH_MACOS_APP" = 1 ] || return 0
  [ "$OS" = Darwin ] || { warn "--macos-app is macOS only; skipped"; return 0; }
  step "Building the native macOS app"
  ( cd "$INSTALL_DIR/SmartTerminalApp" && CREATE_LAUNCH_AGENT="$( [ "$WITH_LAUNCH_AGENT" = 1 ] && echo true || echo false )" ./install.sh ) \
    || warn "macOS app install failed (the CLI is still installed)"
}

verify() {
  step "Verifying"
  local v
  v="$("$BIN_DIR/smart-term" --version 2>&1)" || die "launcher failed: $v"
  ok "$v"
}

summary() {
  local reload="exec \$SHELL"
  printf '\n%s✨ Smart Terminal is installed.%s\n\n' "$G" "$R"
  printf '  %sStart%s          smart-term            %s(chat; !cmd runs shell; /help)%s\n' "$B" "$R" "$D" "$R"
  printf '  %sOne-shot%s       smart-term ask "how do I undo a git commit"\n' "$B" "$R"
  printf '  %sCommands%s       smart-term term find large files in ~/Downloads\n' "$B" "$R"
  printf '  %sFix%s            smart-term fix npm run build\n' "$B" "$R"
  printf '  %sHealth check%s   smart-term doctor\n' "$B" "$R"
  [ "$SHELL_INTEGRATION" = 1 ] && printf '  %sIn your shell%s  type plain English, press %sCtrl+G%s → command\n' "$B" "$R" "$B" "$R"
  [ "$WITH_WEB" = 1 ] && printf '  %sWeb UI%s         cd %s && .venv/bin/python web_app.py  → http://localhost:5001\n' "$B" "$R" "$INSTALL_DIR"
  printf '\n  %sReload your shell to pick up changes:%s %s\n' "$D" "$R" "$reload"
  printf '  %sUpdate:%s smart-term update   %sUninstall:%s smart-term uninstall\n\n' "$D" "$R" "$D" "$R"
}

# ── main ─────────────────────────────────────────────────────────────────────
[ "$OS" = Darwin ] || [ "$OS" = Linux ] || warn "untested OS: $OS (macOS and Linux are supported; on Windows use WSL)"
[ "$(id -u)" = 0 ] && [ "$SYSTEM_INSTALL" = 0 ] && warn "running as root: files go to root's home. Prefer running as your user."

if [ "$MODE" = uninstall ]; then do_uninstall; exit 0; fi

printf '%s\n' "${B}Smart Terminal installer v$VERSION${R}  ${D}($OS, profile: $PROFILE)${R}"
fetch_source
build_venv
write_launchers
write_shell_integration
verify
configure
install_macos_app
summary
