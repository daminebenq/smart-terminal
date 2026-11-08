import json
import os

import pytest

from smart_terminal import shell, providers


def test_cd_persists(tmp_path):
    st = shell.ShellState(cwd=str(tmp_path))
    (tmp_path / 'sub').mkdir()
    shell.run('cd sub', st)
    assert st.cwd == str(tmp_path / 'sub')
    shell.run('cd -', st)
    assert st.cwd == str(tmp_path)
    res = shell.run('cd does-not-exist', st)
    assert res.code == 1 and st.cwd == str(tmp_path)


def test_run_captures_output_and_exit_code(tmp_path, capsys):
    st = shell.ShellState(cwd=str(tmp_path))
    res = shell.run('echo hello; exit 3', st)
    assert res.code == 3
    assert 'hello' in res.output
    assert st.last_failed() is res


def test_run_uses_state_cwd(tmp_path):
    st = shell.ShellState(cwd=str(tmp_path))
    res = shell.run('pwd', st)
    assert os.path.realpath(res.output.strip()) == os.path.realpath(str(tmp_path))


def test_interactive_detection():
    assert shell._is_interactive('vim foo.txt')
    assert shell._is_interactive('sudo htop')
    assert not shell._is_interactive('python3 script.py')
    assert not shell._is_interactive('ls -la')


def test_git_branch(tmp_path):
    (tmp_path / '.git').mkdir()
    (tmp_path / '.git' / 'HEAD').write_text('ref: refs/heads/feature/x\n')
    (tmp_path / 'a' / 'b').mkdir(parents=True)
    assert shell.git_branch(str(tmp_path / 'a' / 'b')) == 'x'


@pytest.mark.parametrize('url,expected', [
    ('http://localhost:11434', providers.OLLAMA),
    ('https://api.openai.com/v1', providers.OPENAI),
    ('https://api.groq.com/openai/v1', providers.OPENAI),
    ('https://api.anthropic.com', providers.ANTHROPIC),
])
def test_detect_provider_from_url(monkeypatch, url, expected):
    monkeypatch.setenv('SMART_TERM_PROVIDER', '')
    monkeypatch.setattr('smart_terminal.setup.load_global_config', lambda: {})
    assert providers.detect_provider(url) == expected


class _Resp:
    def __init__(self, lines=None, body=None):
        self._lines, self._body = lines or [], body

    def raise_for_status(self):
        pass

    def iter_lines(self, decode_unicode=True):
        return iter(self._lines)

    def json(self):
        return self._body


class _Sess:
    def __init__(self, resp):
        self.resp, self.calls = resp, []

    def post(self, url, **kw):
        self.calls.append((url, kw))
        return self.resp


def test_openai_stream_parsing():
    lines = ['data: ' + json.dumps({'choices': [{'delta': {'content': 'Hel'}}]}),
             '', 'data: ' + json.dumps({'choices': [{'delta': {'content': 'lo'}}]}), 'data: [DONE]']
    sess = _Sess(_Resp(lines=lines))
    toks = []
    out = providers.openai_chat(sess, 'https://x/v1', 'k', 'm', [{'role': 'user', 'content': 'hi'}],
                                on_token=toks.append)
    assert out == 'Hello' and toks == ['Hel', 'lo']
    assert sess.calls[0][0] == 'https://x/v1/chat/completions'


def test_anthropic_splits_system_and_streams():
    lines = ['data: ' + json.dumps({'type': 'content_block_delta', 'delta': {'text': 'ok'}}),
             'data: ' + json.dumps({'type': 'message_stop'})]
    sess = _Sess(_Resp(lines=lines))
    out = providers.anthropic_chat(sess, 'https://api.anthropic.com', 'k', 'claude',
                                   [{'role': 'system', 'content': 'S'}, {'role': 'user', 'content': 'U'}])
    url, kw = sess.calls[0]
    assert out == 'ok'
    assert url.endswith('/v1/messages')
    assert kw['json']['system'] == 'S'
    assert kw['json']['messages'] == [{'role': 'user', 'content': 'U'}]


def test_configure_noninteractive(tmp_path, monkeypatch):
    from smart_terminal import setup
    monkeypatch.setattr(setup, 'CONFIG_DIR', str(tmp_path))
    monkeypatch.setattr(setup, 'CONFIG_FILE', str(tmp_path / 'config.json'))
    monkeypatch.setattr(setup, '_lock_config', lambda: None)
    monkeypatch.setattr(setup, '_unlock_config', lambda: None)
    cfg = setup.configure_noninteractive('ollama', '', 'llama3.2:3b')
    assert cfg['api_url'] == 'http://localhost:11434'
    with pytest.raises(ValueError):
        setup.configure_noninteractive('openai', '', 'gpt-4o')  # key required
    with pytest.raises(ValueError):
        setup.configure_noninteractive('nope', '', 'x')


def test_cli_global_options():
    import cli
    opts, rest = cli._parse_globals(['-y', '--model', 'foo', 'term', 'ls', '-la'])
    assert opts['yes'] and opts['model'] == 'foo'
    assert rest == ['term', 'ls', '-la']


def test_expand_file_refs(tmp_path, monkeypatch):
    from smart_terminal import chat
    (tmp_path / 'notes.txt').write_text('SECRET-CONTENT')
    monkeypatch.setattr(chat, '_STATE', shell.ShellState(cwd=str(tmp_path)))
    out = chat._expand_file_refs('summarize @notes.txt please, mail me@example.com')
    assert 'SECRET-CONTENT' in out
    assert out.count('--- file:') == 1


def test_repl_slash_commands(tmp_path, monkeypatch, capsys):
    from smart_terminal import chat
    from smart_terminal.conversation import Conversation
    st = shell.ShellState(cwd=str(tmp_path))
    monkeypatch.setattr(chat, '_STATE', st)

    class A:
        model, api_base, provider = 'm', 'http://x', 'ollama'
    conv = Conversation()
    chat._handle_slash('/run echo via-run', A(), conv, [''])
    (tmp_path / 'd').mkdir()
    chat._handle_slash('/cd d', A(), conv, [''])
    assert st.cwd == str(tmp_path / 'd')
    chat._handle_slash('/stats', A(), conv, [''])
    chat._handle_slash('/version', A(), conv, [''])
    conv.add_user('q'); conv.add_assistant('a')
    chat._handle_slash('/undo', A(), conv, [''])
    out = capsys.readouterr().out
    assert 'via-run' in out and 'commands' in out and '0.2.0' in out
    assert conv.messages == []


def test_completer_fuzzy_slash():
    from prompt_toolkit.document import Document
    from smart_terminal.chat import _ReplCompleter
    names = [c.text for c in _ReplCompleter().get_completions(Document('/dctr'), None)]
    assert '/doctor' in names
