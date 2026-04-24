"""Conversation state for multi-turn chat.

Provides:
- Message history tracking (role/content/timestamp)
- Token estimation (char/4 heuristic)
- Auto-compaction via summarization when context grows too large
- Persistence to disk (~/.smart-terminal-config/sessions/)
- Session resume
"""

from __future__ import annotations
import os
import json
import time
import uuid
from pathlib import Path
from typing import Callable, List, Dict, Optional

SESSIONS_DIR = Path(os.path.expanduser('~')) / '.smart-terminal-config' / 'sessions'


def estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token for English."""
    if not text:
        return 0
    return max(1, len(text) // 4)


DEFAULT_SYSTEM_PROMPT = (
    "You are Smart Terminal, an AI assistant embedded in the user's shell. "
    "You help with coding, shell commands, system diagnosis, and general questions. "
    "When the user asks for shell commands, propose them in a ```bash code block and "
    "briefly explain what they do. Be concise. Prefer action over verbose explanation. "
    "Remember prior turns and refer back to context when useful."
)


class Conversation:
    """Holds conversation history and handles compaction/persistence."""

    def __init__(
        self,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        session_id: Optional[str] = None,
        max_context_tokens: int = 8000,
        compact_threshold: float = 0.75,
    ):
        self.session_id = session_id or f"session-{int(time.time())}-{uuid.uuid4().hex[:6]}"
        self.system_prompt = system_prompt
        self.messages: List[Dict] = []
        self.max_context_tokens = max_context_tokens
        self.compact_threshold = compact_threshold
        self.created_at = int(time.time())
        self.updated_at = self.created_at
        # summary of compacted messages prepended as context
        self.compacted_summary: str = ""

    # ── message management ──

    def add_user(self, content: str):
        self.messages.append({
            'role': 'user',
            'content': content,
            'ts': int(time.time()),
        })
        self.updated_at = int(time.time())

    def add_assistant(self, content: str):
        self.messages.append({
            'role': 'assistant',
            'content': content,
            'ts': int(time.time()),
        })
        self.updated_at = int(time.time())

    def clear(self):
        """Wipe all messages but keep session_id and system_prompt."""
        self.messages = []
        self.compacted_summary = ""
        self.updated_at = int(time.time())

    # ── token accounting ──

    def estimate_total_tokens(self) -> int:
        total = estimate_tokens(self.system_prompt) + estimate_tokens(self.compacted_summary)
        for m in self.messages:
            total += estimate_tokens(m.get('content', ''))
        return total

    def should_compact(self) -> bool:
        return self.estimate_total_tokens() >= int(self.max_context_tokens * self.compact_threshold)

    # ── API format ──

    def to_api_messages(self) -> List[Dict]:
        """Return message list in OpenAI/Ollama chat format.

        Long-term memory is injected into the system prompt so the assistant
        always has access to remembered facts from prior sessions.
        """
        out = []
        sys_content = self.system_prompt

        # Inject long-term memory (pinned + recent) at the top of system prompt
        try:
            from smart_terminal.memory import memory_context_block
            mem_block = memory_context_block()
            if mem_block:
                sys_content = sys_content + "\n\n" + mem_block
        except Exception:
            pass

        if self.compacted_summary:
            sys_content = sys_content + "\n\n## Summary of earlier conversation\n" + self.compacted_summary
        out.append({'role': 'system', 'content': sys_content})
        for m in self.messages:
            out.append({'role': m['role'], 'content': m['content']})
        return out

    # ── compaction ──

    def compact(self, summarizer: Callable[[List[Dict]], str],
                keep_recent: int = 4,
                memorizer: Optional[Callable[[List[Dict]], List[Dict]]] = None) -> str:
        """Summarize older messages, keep the most recent `keep_recent` turns.

        `summarizer` is called with the list of older message dicts and should
        return a concise summary string.
        `memorizer` (optional) is called with the same list and is expected to
        persist durable facts to long-term memory; it should return a list of
        added memory entries (or an empty list).

        Returns the summary text for display.
        """
        if len(self.messages) <= keep_recent:
            return ""

        to_summarize = self.messages[:-keep_recent]
        kept = self.messages[-keep_recent:]

        summary_text = summarizer(to_summarize)

        # Best-effort memorization — independent of summarization success
        if memorizer is not None:
            try:
                memorizer(to_summarize)
            except Exception:
                pass

        if not summary_text:
            # Still drop older messages to free context, even if summary failed
            self.messages = kept
            self.updated_at = int(time.time())
            return ""

        # merge with any existing summary
        if self.compacted_summary:
            self.compacted_summary = self.compacted_summary + "\n\n" + summary_text
        else:
            self.compacted_summary = summary_text

        self.messages = kept
        self.updated_at = int(time.time())
        return summary_text

    # ── persistence ──

    def to_dict(self) -> Dict:
        return {
            'session_id': self.session_id,
            'system_prompt': self.system_prompt,
            'messages': self.messages,
            'compacted_summary': self.compacted_summary,
            'max_context_tokens': self.max_context_tokens,
            'compact_threshold': self.compact_threshold,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'Conversation':
        c = cls(
            system_prompt=data.get('system_prompt', DEFAULT_SYSTEM_PROMPT),
            session_id=data.get('session_id'),
            max_context_tokens=data.get('max_context_tokens', 8000),
            compact_threshold=data.get('compact_threshold', 0.75),
        )
        c.messages = data.get('messages', []) or []
        c.compacted_summary = data.get('compacted_summary', '') or ''
        c.created_at = data.get('created_at', int(time.time()))
        c.updated_at = data.get('updated_at', c.created_at)
        return c

    def save(self, path: Optional[Path] = None) -> Path:
        if path is None:
            SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
            path = SESSIONS_DIR / f"{self.session_id}.json"
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(self.to_dict(), f, indent=2)
        return path

    @classmethod
    def load(cls, path: Path) -> 'Conversation':
        with open(path, 'r', encoding='utf-8') as f:
            return cls.from_dict(json.load(f))

    @classmethod
    def list_sessions(cls) -> List[Dict]:
        """Return summary info for all saved sessions, newest first."""
        if not SESSIONS_DIR.exists():
            return []
        out = []
        for p in SESSIONS_DIR.glob('*.json'):
            try:
                with open(p, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                msgs = data.get('messages', []) or []
                first_user = next((m.get('content', '') for m in msgs if m.get('role') == 'user'), '')
                out.append({
                    'path': p,
                    'session_id': data.get('session_id', p.stem),
                    'updated_at': data.get('updated_at', 0),
                    'msg_count': len(msgs),
                    'preview': (first_user[:60] + '…') if len(first_user) > 60 else first_user,
                })
            except Exception:
                continue
        out.sort(key=lambda d: d['updated_at'], reverse=True)
        return out

    @classmethod
    def latest(cls) -> Optional['Conversation']:
        sessions = cls.list_sessions()
        if not sessions:
            return None
        return cls.load(sessions[0]['path'])
