# Smart Terminal — Makefile (thin wrapper around install.sh)

.PHONY: install install-full install-launcher uninstall update test lint run web-ui doctor clean-cache

install:            ## standard install (venv + launchers + shell integration)
	./install.sh

install-full:       ## everything: web UI, browser scraping, dev tools
	./install.sh --full

install-launcher:   ## (re)write launchers only, no config prompt
	./install.sh --skip-config -y

uninstall:
	./install.sh --uninstall

update:
	./install.sh --update

test:
	@[ -x .venv/bin/pytest ] || ./install.sh --with-dev --skip-config --no-shell-integration -y -q
	PYTHONPATH=$$(pwd) .venv/bin/python -m pytest -q

lint:
	shellcheck -S warning install.sh smart-term st

run:
	./smart-term

web-ui:
	@.venv/bin/python -c "import flask" 2>/dev/null || ./install.sh --with-web --skip-config -y -q
	PYTHONPATH=$$(pwd) .venv/bin/python web_app.py

doctor:
	./smart-term doctor

clean-cache:
	./smart-term --clear-cache
