import os
import json
from typing import Dict, Any, Optional

CONFIG_PATH = os.path.join(os.getcwd(), '.smart_terminal_config.json')

# Global config written by first-run setup
_GLOBAL_CONFIG_FILE = os.path.join(os.path.expanduser('~'), '.smart-terminal-config', 'config.json')


def _load_global_config() -> Dict[str, str]:
    """Read the global first-run config and map it to the env-style keys used internally."""
    if not os.path.isfile(_GLOBAL_CONFIG_FILE):
        return {}
    try:
        with open(_GLOBAL_CONFIG_FILE, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
        return {
            'OLLAMA_API_BASE': cfg.get('api_url', ''),
            'OLLAMA_MODEL': cfg.get('model', ''),
            'OLLAMA_API_KEY': cfg.get('api_token', ''),
        }
    except Exception:
        return {}


class SettingsManager:
    def __init__(self):
        # Global config (from setup wizard) takes precedence over env vars
        global_cfg = _load_global_config()
        self._data: Dict[str, Any] = {
            'OLLAMA_API_BASE': global_cfg.get('OLLAMA_API_BASE', '') or os.getenv('OLLAMA_API_BASE', ''),
            'OLLAMA_MODEL': global_cfg.get('OLLAMA_MODEL', '') or os.getenv('OLLAMA_MODEL', ''),
            'OLLAMA_API_KEY': global_cfg.get('OLLAMA_API_KEY', '') or os.getenv('OLLAMA_API_KEY', ''),
            # behavior toggles
            'AUTO_APPROVE_ZERO_RISK': os.getenv('AUTO_APPROVE_ZERO_RISK', 'true'),
            'AUTO_APPROVE_LOW_RISK_THRESHOLD': os.getenv('AUTO_APPROVE_LOW_RISK_THRESHOLD', '20'),
            'SANDBOX': os.getenv('SMART_TERMINAL_SANDBOX', 'false'),
            'SANDBOX_IMAGE': os.getenv('SMART_TERMINAL_SANDBOX_IMAGE', 'ubuntu:24.04'),
            'DRY_RUN': os.getenv('DRY_RUN', 'false'),
            'LOG_LEVEL': os.getenv('LOG_LEVEL', 'INFO'),
            'HISTORY_FILE': os.path.join(os.path.expanduser('~'), '.smart_terminal_history')
        }
        self.load()

    def load(self):
        try:
            if os.path.exists(CONFIG_PATH):
                with open(CONFIG_PATH, 'r') as f:
                    data = json.load(f)
                    self._data.update(data)
        except Exception:
            # ignore malformed config
            pass

    def save(self):
        with open(CONFIG_PATH, 'w') as f:
            json.dump(self._data, f, indent=2)

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        val = self._data.get(key)
        return val if val is not None else default

    def set(self, key: str, value: str):
        self._data[key] = value
        self.save()

    def as_dict(self) -> Dict[str, str]:
        return dict(self._data)

    def masked(self) -> Dict[str, str]:
        out = {}
        for k, v in self._data.items():
            if 'KEY' in k or 'API' in k and v:
                out[k] = v[:4] + '...' + v[-4:]
            else:
                out[k] = v
        return out
