# Smart Terminal — Makefile
#
# Default target creates a project-local virtualenv at ./.venv and installs
# requirements there. Works on macOS, Linux (including PEP 668 distros like
# Kali/Debian/Ubuntu 24+), and WSL without needing --break-system-packages.

VENV       ?= .venv
PYTHON     ?= python3
VENV_PY    := $(VENV)/bin/python
VENV_PIP   := $(VENV)/bin/pip

.PHONY: install venv install-system install-launcher test clean-cache run

install: venv
	$(VENV_PIP) install --upgrade pip
	$(VENV_PIP) install -r requirements.txt
	@$(MAKE) install-launcher
	@echo ""
	@echo "✓ Installed into $(VENV)"
	@echo "  Run from anywhere: smart-term"
	@echo "  Or directly:        $(VENV_PY) cli.py"

# Installs the 'smart-term' launcher (and st/term/do/web_* wrappers) onto PATH.
# Tries /usr/local/bin (sudo if needed), falls back to ~/.local/bin.
install-launcher:
	@if [ -x install_smart_term.sh ]; then \
		echo ""; \
		echo "Installing 'smart-term' launcher onto PATH ..."; \
		./install_smart_term.sh || echo "  (launcher install skipped — run ./install_smart_term.sh manually if needed)"; \
	else \
		echo "install_smart_term.sh not found or not executable; skipping launcher install"; \
	fi

venv:
	@if [ ! -x "$(VENV_PY)" ]; then \
		echo "Creating virtualenv at $(VENV) ..."; \
		$(PYTHON) -m venv $(VENV) || { \
			echo ""; \
			echo "venv creation failed. On Debian/Kali/Ubuntu install:"; \
			echo "  sudo apt install python3-venv"; \
			exit 1; \
		}; \
	fi

# Escape hatch for users who explicitly want a system-wide install on
# externally-managed Python (PEP 668). Use at your own risk.
install-system:
	$(PYTHON) -m pip install --break-system-packages -r requirements.txt

test: venv
	$(VENV_PIP) install -r requirements.txt >/dev/null
	PYTHONPATH=$$(pwd) $(VENV_PY) -m pytest -q

run: venv
	PYTHONPATH=$$(pwd) $(VENV_PY) cli.py

clean-cache:
	$(VENV_PY) -c "from smart_terminal.agent import TerminalAgent; from smart_terminal.settings import SettingsManager; s=SettingsManager(); a=TerminalAgent(api_base=s.get('OLLAMA_API_BASE') or '', model=s.get('OLLAMA_MODEL') or ''); a.clear_cache()"
