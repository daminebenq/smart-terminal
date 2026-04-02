import pytest
from smart_terminal.agent import TerminalAgent


def test_extract_year_from_wikidata_claims_person():
    agent = TerminalAgent(api_base='', model='')
    claims = {
        'P569': [
            {'mainsnak': {'datavalue': {'value': {'time': '+1962-01-17T00:00:00Z'}}}}
        ]
    }
    year, label = agent._extract_year_from_wikidata_claims(claims)
    assert year == 1962
    assert label == 'born'


def test_extract_year_from_wikidata_claims_inception():
    agent = TerminalAgent(api_base='', model='')
    claims = {
        'P571': [
            {'mainsnak': {'datavalue': {'value': {'time': '+1956-03-20T00:00:00Z'}}}}
        ]
    }
    year, label = agent._extract_year_from_wikidata_claims(claims)
    assert year == 1956
    assert label == 'founded'


def test_extract_population_from_wikidata_claims_quantity_with_qualifier():
    agent = TerminalAgent(api_base='', model='')
    claims = {
        'P1082': [
            {
                'mainsnak': {'datavalue': {'value': {'amount': '+11304500'}}},
                'qualifiers': {
                    'P585': [
                        {'datavalue': {'value': {'time': '+2016-01-01T00:00:00Z'}}}
                    ]
                }
            }
        ]
    }
    pop, year = agent._extract_population_from_wikidata_claims(claims)
    assert pop == 11304500
    assert year == 2016


def test_extract_population_from_wikidata_claims_no_population():
    agent = TerminalAgent(api_base='', model='')
    claims = {}
    pop, year = agent._extract_population_from_wikidata_claims(claims)
    assert pop is None and year is None


def test_pretty_print_trims_and_collapses():
    agent = TerminalAgent(api_base='', model='')
    long_text = "\n\nLine1\n\n\n\nLine2\n\n\nLine3\n"
    # capture stdout
    import io, sys
    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        agent._pretty_print(long_text)
    finally:
        sys.stdout = old
    out = buf.getvalue()
    assert 'Line1' in out and 'Line2' in out and 'Line3' in out
    # ensure no more than two consecutive newlines
    assert '\n\n\n' not in out
