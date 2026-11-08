"""Model-provider adapters.

Ollama is handled directly in agent.py (its native /api/chat and /api/generate).
This module adds OpenAI-compatible (OpenAI, Groq, most self-hosted gateways)
and Anthropic Messages API support so every provider offered by the setup
wizard actually works.
"""
from __future__ import annotations

import json
import os
from typing import Callable, Dict, List, Optional

OLLAMA = 'ollama'
OPENAI = 'openai'        # any OpenAI-compatible /chat/completions endpoint
ANTHROPIC = 'anthropic'

_OPENAI_LIKE = {'openai', 'groq', 'openai-compatible'}


def detect_provider(api_base: str) -> str:
    """Pick the wire protocol for *api_base*.

    Order: SMART_TERM_PROVIDER env → provider saved by the setup wizard →
    URL heuristics → Ollama.
    """
    explicit = (os.getenv('SMART_TERM_PROVIDER') or '').strip().lower()
    if not explicit:
        try:
            from smart_terminal.setup import load_global_config
            explicit = (load_global_config().get('provider') or '').strip().lower()
        except Exception:
            explicit = ''
    if explicit == ANTHROPIC:
        return ANTHROPIC
    if explicit in _OPENAI_LIKE:
        return OPENAI
    if explicit == OLLAMA:
        return OLLAMA
    base = (api_base or '').lower().rstrip('/')
    if 'anthropic.com' in base:
        return ANTHROPIC
    if base.endswith('/v1') or 'openai.com' in base or 'groq.com' in base:
        return OPENAI
    return OLLAMA


def _emit(on_token: Optional[Callable[[str], None]], chunk: str) -> None:
    if on_token and chunk:
        try:
            on_token(chunk)
        except Exception:
            pass


def openai_chat(session, api_base: str, api_key: str, model: str,
                messages: List[Dict], stream: bool = True,
                on_token: Optional[Callable[[str], None]] = None,
                timeout: int = 300) -> str:
    url = api_base.rstrip('/') + '/chat/completions'
    headers = {'Content-Type': 'application/json'}
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'
    payload = {
        'model': model,
        'messages': [{'role': m['role'], 'content': m.get('content', '')} for m in messages],
        'stream': bool(stream),
    }
    r = session.post(url, json=payload, headers=headers, timeout=timeout, stream=bool(stream))
    r.raise_for_status()
    if not stream:
        j = r.json()
        choices = j.get('choices') or []
        if choices:
            return ((choices[0].get('message') or {}).get('content') or '')
        return ''
    acc: List[str] = []
    for line in r.iter_lines(decode_unicode=True):
        if not line or not line.startswith('data:'):
            continue
        data = line[5:].strip()
        if data == '[DONE]':
            break
        try:
            j = json.loads(data)
        except ValueError:
            continue
        choices = j.get('choices') or []
        if not choices:
            continue
        chunk = (choices[0].get('delta') or {}).get('content') or ''
        if chunk:
            acc.append(chunk)
            _emit(on_token, chunk)
    return ''.join(acc)


def anthropic_chat(session, api_base: str, api_key: str, model: str,
                   messages: List[Dict], stream: bool = True,
                   on_token: Optional[Callable[[str], None]] = None,
                   timeout: int = 300, max_tokens: int = 4096) -> str:
    base = api_base.rstrip('/')
    url = base + ('/messages' if base.endswith('/v1') else '/v1/messages')
    headers = {
        'Content-Type': 'application/json',
        'x-api-key': api_key or '',
        'anthropic-version': '2023-06-01',
    }
    system = '\n\n'.join(m.get('content', '') for m in messages if m.get('role') == 'system')
    convo = [{'role': m['role'], 'content': m.get('content', '')}
             for m in messages if m.get('role') in ('user', 'assistant')]
    payload = {'model': model, 'max_tokens': max_tokens, 'messages': convo, 'stream': bool(stream)}
    if system:
        payload['system'] = system
    r = session.post(url, json=payload, headers=headers, timeout=timeout, stream=bool(stream))
    r.raise_for_status()
    if not stream:
        j = r.json()
        return ''.join(b.get('text', '') for b in (j.get('content') or []) if b.get('type') == 'text')
    acc: List[str] = []
    for line in r.iter_lines(decode_unicode=True):
        if not line or not line.startswith('data:'):
            continue
        try:
            j = json.loads(line[5:].strip())
        except ValueError:
            continue
        if j.get('type') == 'content_block_delta':
            chunk = (j.get('delta') or {}).get('text') or ''
            if chunk:
                acc.append(chunk)
                _emit(on_token, chunk)
        elif j.get('type') == 'message_stop':
            break
    return ''.join(acc)


def chat(provider: str, session, api_base: str, api_key: str, model: str,
         messages: List[Dict], stream: bool = True,
         on_token: Optional[Callable[[str], None]] = None, timeout: int = 300) -> str:
    if provider == ANTHROPIC:
        return anthropic_chat(session, api_base, api_key, model, messages, stream, on_token, timeout)
    return openai_chat(session, api_base, api_key, model, messages, stream, on_token, timeout)


def list_models(provider: str, session, api_base: str, api_key: str, timeout: int = 10) -> List[str]:
    """Return model names available at *api_base* (best effort)."""
    base = api_base.rstrip('/')
    if provider == OLLAMA:
        headers = {'Authorization': f'Bearer {api_key}'} if api_key else {}
        r = session.get(base + '/api/tags', headers=headers, timeout=timeout)
        r.raise_for_status()
        return [m.get('name', '?') for m in (r.json().get('models') or [])]
    if provider == ANTHROPIC:
        url = base + ('/models' if base.endswith('/v1') else '/v1/models')
        r = session.get(url, headers={'x-api-key': api_key or '', 'anthropic-version': '2023-06-01'},
                        timeout=timeout)
    else:
        r = session.get(base + '/models',
                        headers={'Authorization': f'Bearer {api_key}'} if api_key else {},
                        timeout=timeout)
    r.raise_for_status()
    return [m.get('id', '?') for m in (r.json().get('data') or [])]
