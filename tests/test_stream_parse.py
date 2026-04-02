import json
from smart_terminal.agent import TerminalAgent


def test_extract_commands_from_streamed_json_lines():
    # Simulate a streamed Ollama response with JSON lines and embedded code block
    streamed = (
        '{"model":"glm-5","response":"","thinking":"..."}\n'
        '{"response":"```bash\\nsudo apt update\\nsudo apt install -y htop\\nhtop\\n```"}\n'
    )
    a = TerminalAgent(api_base='https://example', model='glm-5')
    cmds = a._extract_commands(streamed)
    assert 'sudo apt update' in cmds[0]
    assert 'sudo apt install -y htop' in cmds[1]
    assert 'htop' in cmds[2]
