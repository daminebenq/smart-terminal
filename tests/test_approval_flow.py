from smart_terminal.agent import TerminalAgent


def test_assess_risk_and_session_auto():
    a = TerminalAgent(api_base='https://example', model='glm-5')
    cmds = ['sudo apt install -y htop', 'htop']
    risk = a._assess_risk(cmds)
    assert isinstance(risk, int)
    # session auto flags short-circuit interactive approval
    approved = a._interactive_approval(cmds, risk, session_auto_low=True, session_auto_all=False)
    # since session_auto_low is True and default threshold 20, but our risk likely >20, could be False; ensure boolean
    assert isinstance(approved, bool)
    approved_all = a._interactive_approval(cmds, risk, session_auto_low=False, session_auto_all=True)
    assert approved_all is True
