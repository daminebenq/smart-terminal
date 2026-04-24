"""Long-term memory store for Smart Terminal.

Persistent facts extracted from conversations, surfaced in every new session.

Storage: ~/.smart-terminal-config/memory.json
Format: {
    "memories": [
        {"id": "...", "text": "...", "tags": [...], "source": "session-id",
         "created_at": ts, "updated_at": ts, "pinned": bool}
    ]
}
"""

from __future__ import annotations
import os
import json
import time
import uuid
import re
from pathlib import Path
from typing import Callable, List, Dict, Optional

MEMORY_PATH = Path(os.path.expanduser('~')) / '.smart-terminal-config' / 'memory.json'

# Soft limit to keep memory footprint reasonable
MAX_MEMORIES = 200
MAX_MEMORY_CHARS_IN_PROMPT = 3000


def _now() -> int:
    return int(time.time())


def _load() -> Dict:
    if not MEMORY_PATH.exists():
        return {"memories": []}
    try:
        with open(MEMORY_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"memories": []}
        data.setdefault("memories", [])
        return data
    except Exception:
        return {"memories": []}


def _save(data: Dict):
    MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = MEMORY_PATH.with_suffix('.json.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, MEMORY_PATH)


# ── Public API ──

def add_memory(text: str, tags: Optional[List[str]] = None,
               source: Optional[str] = None, pinned: bool = False) -> Dict:
    """Add (or dedupe) a memory. Returns the stored entry."""
    text = (text or '').strip()
    if not text:
        return {}
    data = _load()
    # dedupe: skip if text already present (case-insensitive exact match)
    low = text.lower()
    for m in data['memories']:
        if m.get('text', '').strip().lower() == low:
            m['updated_at'] = _now()
            if tags:
                m['tags'] = sorted(set((m.get('tags') or []) + list(tags)))
            if pinned:
                m['pinned'] = True
            _save(data)
            return m

    entry = {
        'id': uuid.uuid4().hex[:8],
        'text': text,
        'tags': sorted(set(tags or [])),
        'source': source or '',
        'created_at': _now(),
        'updated_at': _now(),
        'pinned': bool(pinned),
    }
    data['memories'].append(entry)

    # Trim: keep pinned + newest, drop oldest unpinned beyond limit
    if len(data['memories']) > MAX_MEMORIES:
        pinned_items = [m for m in data['memories'] if m.get('pinned')]
        others = [m for m in data['memories'] if not m.get('pinned')]
        others.sort(key=lambda m: m.get('updated_at', 0), reverse=True)
        keep = MAX_MEMORIES - len(pinned_items)
        data['memories'] = pinned_items + others[:max(0, keep)]

    _save(data)
    return entry


def list_memories(query: Optional[str] = None, tag: Optional[str] = None) -> List[Dict]:
    """Return memories, optionally filtered by substring query or tag."""
    data = _load()
    items = data.get('memories', []) or []
    if query:
        q = query.lower()
        items = [m for m in items if q in (m.get('text') or '').lower()
                 or any(q in t.lower() for t in m.get('tags', []))]
    if tag:
        items = [m for m in items if tag in (m.get('tags') or [])]
    # pinned first, then newest
    items.sort(key=lambda m: (not m.get('pinned'), -m.get('updated_at', 0)))
    return items


def remove_memory(memory_id: str) -> bool:
    data = _load()
    before = len(data['memories'])
    data['memories'] = [m for m in data['memories'] if m.get('id') != memory_id]
    _save(data)
    return len(data['memories']) < before


def clear_memories(pinned_too: bool = False) -> int:
    """Delete all memories (or only unpinned). Returns count deleted."""
    data = _load()
    before = len(data['memories'])
    if pinned_too:
        data['memories'] = []
    else:
        data['memories'] = [m for m in data['memories'] if m.get('pinned')]
    _save(data)
    return before - len(data['memories'])


def pin_memory(memory_id: str, pinned: bool = True) -> bool:
    data = _load()
    for m in data['memories']:
        if m.get('id') == memory_id:
            m['pinned'] = bool(pinned)
            m['updated_at'] = _now()
            _save(data)
            return True
    return False


def memory_context_block(query: Optional[str] = None, limit: int = 20) -> str:
    """Build a context block to inject into the system prompt.

    Pinned memories always included; then most recent up to limit.
    Optional `query` filter prioritizes relevant items.
    """
    items = list_memories(query=query)
    if not items:
        return ''
    # Always include pinned, then top-N recent
    pinned = [m for m in items if m.get('pinned')]
    others = [m for m in items if not m.get('pinned')]
    selected = pinned + others[:max(0, limit - len(pinned))]

    lines = ['## Long-term memory (from previous conversations)']
    total = 0
    for m in selected:
        bullet = f"- {m.get('text', '').strip()}"
        if m.get('tags'):
            bullet += f"  [{', '.join(m['tags'])}]"
        if total + len(bullet) > MAX_MEMORY_CHARS_IN_PROMPT:
            break
        lines.append(bullet)
        total += len(bullet)
    if len(lines) == 1:
        return ''
    return '\n'.join(lines)


# ── Fact extraction ──

_FACT_PROMPT = (
    "You are a memory extractor. From the given conversation, extract 0-6 "
    "DURABLE facts worth remembering across future sessions. "
    "Focus on: user preferences, long-term goals, environment/setup details, "
    "identities, stable constraints, and decisions that will remain true.\n\n"
    "Rules:\n"
    "- Skip anything transient (today's task, temporary errors, specific file contents).\n"
    "- Write each fact as ONE concise sentence in the third person.\n"
    "- Begin each line with '- '.\n"
    "- If nothing is worth remembering, output exactly: NONE\n"
    "- No preamble, no numbering, no explanations."
)


def extract_facts(messages: List[Dict],
                  chat_fn: Callable[[List[Dict]], str]) -> List[str]:
    """Call the model to extract durable facts from a message list.

    `chat_fn` receives an OpenAI-style messages list and returns the assistant
    text. On any failure, returns an empty list.
    """
    if not messages:
        return []
    transcript_parts = []
    for m in messages:
        role = m.get('role', 'user')
        content = (m.get('content') or '').strip()
        if not content:
            continue
        transcript_parts.append(f"[{role}] {content}")
    transcript = '\n'.join(transcript_parts)
    if not transcript:
        return []

    prompt_messages = [
        {'role': 'system', 'content': _FACT_PROMPT},
        {'role': 'user', 'content': f"Conversation:\n\n{transcript}"},
    ]
    try:
        out = chat_fn(prompt_messages) or ''
    except Exception:
        return []

    out = out.strip()
    if not out or out.upper().startswith('NONE'):
        return []

    facts: List[str] = []
    for raw in out.splitlines():
        line = raw.strip()
        if not line:
            continue
        # strip leading bullet markers / numbering
        line = re.sub(r'^[-*•\d\.\)\s]+', '', line).strip()
        if not line:
            continue
        # filter obvious non-facts
        if len(line) < 8 or len(line) > 280:
            continue
        if line.upper() == 'NONE':
            continue
        facts.append(line)
        if len(facts) >= 6:
            break
    return facts


def memorize_from_messages(messages: List[Dict],
                            chat_fn: Callable[[List[Dict]], str],
                            source: str = '') -> List[Dict]:
    """Extract facts via model and store them. Returns list of added entries."""
    facts = extract_facts(messages, chat_fn)
    added: List[Dict] = []
    for f in facts:
        entry = add_memory(f, source=source)
        if entry:
            added.append(entry)
    return added
