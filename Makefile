install:
	pip3 install -r requirements.txt

test:
	PYTHONPATH=$$(pwd) pytest -q

clean-cache:
	python3 -c "from smart_terminal.agent import TerminalAgent; from smart_terminal.settings import SettingsManager; s=SettingsManager(); a=TerminalAgent(api_base=s.get('OLLAMA_API_BASE') or '', model=s.get('OLLAMA_MODEL') or ''); a.clear_cache()"
