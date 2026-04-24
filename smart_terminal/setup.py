"""First-run setup wizard for Smart Terminal.

Runs once to configure the AI provider, API URL, model, and optional API token.
Config is saved globally at ~/.smart-terminal-config/config.json.
After saving, the file is locked (immutable) to reject accidental deletion.
"""

import os
import json
import sys
import platform
import subprocess

CONFIG_DIR = os.path.join(os.path.expanduser('~'), '.smart-terminal-config')
CONFIG_FILE = os.path.join(CONFIG_DIR, 'config.json')

# Supported providers with their default API URL patterns
PROVIDERS = [
    {
        'key': 'ollama',
        'name': 'Ollama',
        'default_url': 'http://localhost:11434',
        'token_required': False,
    },
    {
        'key': 'openai',
        'name': 'OpenAI',
        'default_url': 'https://api.openai.com/v1',
        'token_required': True,
    },
    {
        'key': 'anthropic',
        'name': 'Anthropic (Claude)',
        'default_url': 'https://api.anthropic.com',
        'token_required': True,
    },
    {
        'key': 'groq',
        'name': 'Groq',
        'default_url': 'https://api.groq.com/openai/v1',
        'token_required': True,
    },
    {
        'key': 'custom',
        'name': 'Custom / Self-hosted',
        'default_url': '',
        'token_required': False,
    },
]


def is_configured() -> bool:
    """Check if first-run setup has been completed."""
    return os.path.isfile(CONFIG_FILE)


def load_global_config() -> dict:
    """Load the global config. Returns empty dict if not found."""
    if not os.path.isfile(CONFIG_FILE):
        return {}
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def save_global_config(cfg: dict):
    """Save config to ~/.smart-terminal-config/config.json and lock it."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    # Unlock first in case it's already locked from a previous configure
    _unlock_config()
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, indent=2)
    _lock_config()


def _lock_config():
    """Make the config file immutable (reject deletion/modification)."""
    from smart_terminal.platform_compat import lock_file
    lock_file(CONFIG_FILE)


def _unlock_config():
    """Remove immutable flag from config file so it can be written/deleted."""
    from smart_terminal.platform_compat import unlock_file
    unlock_file(CONFIG_FILE)


def _prompt(message: str, default: str = '') -> str:
    """Prompt user for input with optional default."""
    if default:
        display = f'{message} [{default}]: '
    else:
        display = f'{message}: '
    try:
        val = input(display).strip()
    except (EOFError, KeyboardInterrupt):
        print('\nSetup cancelled.')
        sys.exit(1)
    return val if val else default


def run_setup():
    """Interactive first-run setup wizard."""
    print('\n\033[1;34m╔══════════════════════════════════════════╗')
    print('║     Smart Terminal — First-Run Setup     ║')
    print('╚══════════════════════════════════════════╝\033[0m\n')

    # 1. Choose provider
    print('Select your AI provider:\n')
    for i, p in enumerate(PROVIDERS, 1):
        extra = f'  (default: {p["default_url"]})' if p['default_url'] else ''
        print(f'  {i}) {p["name"]}{extra}')
    print()

    while True:
        choice = _prompt('Enter number', '1')
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(PROVIDERS):
                provider = PROVIDERS[idx]
                break
        except ValueError:
            pass
        print(f'Please enter a number between 1 and {len(PROVIDERS)}.')

    print(f'\n  Selected: {provider["name"]}\n')

    # 2. API URL
    default_url = provider['default_url']
    api_url = _prompt('API URL (enter to use default, or type a custom URL)', default_url)
    if not api_url:
        print('API URL is required.')
        api_url = _prompt('API URL', default_url)

    # Normalize URL scheme (e.g. https:/host -> https://host)
    if api_url and '://' not in api_url:
        for scheme in ('https:/', 'http:/'):
            if api_url.startswith(scheme):
                api_url = scheme.rstrip('/') + '//' + api_url[len(scheme):]
                break

    # 3. Model name
    model_hint = ''
    if provider['key'] == 'ollama':
        model_hint = ' (e.g. llama3.2:3b, mistral)'
    elif provider['key'] == 'openai':
        model_hint = ' (e.g. gpt-4o, gpt-4o-mini)'
    elif provider['key'] == 'anthropic':
        model_hint = ' (e.g. claude-sonnet-4-20250514)'
    elif provider['key'] == 'groq':
        model_hint = ' (e.g. llama-3.3-70b-versatile)'
    model = _prompt(f'Model name{model_hint}')
    if not model:
        print('Model name is required.')
        model = _prompt(f'Model name{model_hint}')

    # 4. API token (can be skipped)
    if provider['token_required']:
        api_token = _prompt('API token/key')
    else:
        api_token = _prompt('API token/key (press Enter to skip if not needed)', '')

    # 5. Save
    cfg = {
        'provider': provider['key'],
        'provider_name': provider['name'],
        'api_url': api_url.rstrip('/'),
        'model': model,
        'api_token': api_token,
    }
    save_global_config(cfg)

    masked_token = (api_token[:4] + '...' + api_token[-4:]) if len(api_token) > 8 else ('***' if api_token else '(none)')
    print(f'\n\033[1;32m✓ Configuration saved and locked at {CONFIG_FILE}\033[0m')
    print(f'  Provider : {provider["name"]}')
    print(f'  API URL  : {api_url}')
    print(f'  Model    : {model}')
    print(f'  API Token: {masked_token}')
    print()


def run_reconfigure():
    """Unlock existing config and re-run the setup wizard."""
    if is_configured():
        _unlock_config()
        print('\033[1;33mReconfiguring Smart Terminal...\033[0m')
    run_setup()
