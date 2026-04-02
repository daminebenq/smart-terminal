from smart_terminal.agent import TerminalAgent


def test_how_old_twitter(capsys):
    agent = TerminalAgent(api_base='https://ollama-api.example', model='test')
    agent.handle_web_search('how old is Twitter')
    captured = capsys.readouterr()
    out = captured.out.strip()
    assert out, 'Expected some output from web_search'
    # Expect either an approximate age line or some search-like output (links/listing)
    assert ('years old' in out) or ('founded' in out) or (' — ' in out)
