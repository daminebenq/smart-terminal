import os
import re
import sys
import json
import logging
import requests
import time
import hashlib
from pathlib import Path
import subprocess
import platform
from typing import List
from smart_terminal.settings import SettingsManager
import shutil
try:
    from ddgs import DDGS
    HAVE_DDGS = True
except Exception:
    try:
        from duckduckgo_search import DDGS
        HAVE_DDGS = True
    except Exception:
        DDGS = None
        HAVE_DDGS = False
try:
    import diskcache
    HAVE_DISKCACHE = True
except Exception:
    diskcache = None
    HAVE_DISKCACHE = False
try:
    from bs4 import BeautifulSoup
    HAVE_BS4 = True
except Exception:
    BeautifulSoup = None
    HAVE_BS4 = False
try:
    import trafilatura
    HAVE_TRAFILATURA = True
except Exception:
    trafilatura = None
    HAVE_TRAFILATURA = False
try:
    from playwright.sync_api import sync_playwright
    HAVE_PLAYWRIGHT = True
except Exception:
    sync_playwright = None
    HAVE_PLAYWRIGHT = False
try:
    from selenium import webdriver
    HAVE_SELENIUM = True
except Exception:
    webdriver = None
    HAVE_SELENIUM = False

LOG_PATH = os.path.join(os.getcwd(), 'logs')
os.makedirs(LOG_PATH, exist_ok=True)
logging.basicConfig(filename=os.path.join(LOG_PATH, 'smart-terminal.log'), level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(message)s')


class TerminalAgent:
    def __init__(self, api_base: str, model: str):
        self.api_base = api_base.rstrip('/')
        self.model = model
        self.api_key = os.getenv('OLLAMA_API_KEY')
        # load settings for dry-run and other toggles
        try:
            ss = SettingsManager()
            self.settings = ss
            self.dry_run = ss.get('DRY_RUN') in (True, 'true', 'True', '1', 'yes')
            self.auto_approve_zero_risk = ss.get('AUTO_APPROVE_ZERO_RISK', 'true').lower() in ('1','true','yes')
            try:
                self.low_risk_threshold = int(ss.get('AUTO_APPROVE_LOW_RISK_THRESHOLD', '20'))
            except Exception:
                self.low_risk_threshold = 20
            self.sandbox_enabled = ss.get('SANDBOX', 'false').lower() in ('1','true','yes')
            self.sandbox_image = ss.get('SANDBOX_IMAGE') or 'ubuntu:24.04'
            # logging level can be controlled via settings
            lvl = ss.get('LOG_LEVEL') or os.getenv('LOG_LEVEL') or 'INFO'
            try:
                logging.getLogger().setLevel(getattr(logging, lvl.upper()))
            except Exception:
                logging.getLogger().setLevel(logging.INFO)
        except Exception:
            self.dry_run = False
            self.auto_approve_zero_risk = True
            self.low_risk_threshold = 20
            self.sandbox_enabled = False
            self.sandbox_image = 'ubuntu:24.04'
        # detect host OS so we can instruct the model and validate commands
        self.detected_os = self._detect_os()
        # prepare a requests session with retry/backoff
        self.session = requests.Session()
        try:
            from urllib3.util import Retry
            from requests.adapters import HTTPAdapter
            retry_strategy = Retry(total=3, backoff_factor=0.8, status_forcelist=[429, 500, 502, 503, 504], allowed_methods=["GET", "POST"])
            adapter = HTTPAdapter(max_retries=retry_strategy)
            self.session.mount('https://', adapter)
            self.session.mount('http://', adapter)
        except Exception:
            # fallback: use default session
            self.session = requests.Session()

        # simple per-host rate limit (seconds between requests)
        self._host_last = {}
        self._min_interval = float(self.settings.get('WEB_MIN_INTERVAL') or os.getenv('WEB_MIN_INTERVAL') or 0.5)

        # cache backend: prefer diskcache for bounded, efficient on-disk cache; fall back to small JSON cache
        cache_dir = Path(os.getenv('XDG_CACHE_HOME', os.path.join(os.path.expanduser('~'), '.cache')))/'smart-terminal'
        cache_dir.mkdir(parents=True, exist_ok=True)
        self._wiki_ttl = int(self.settings.get('WIKI_CACHE_TTL') or os.getenv('WIKI_CACHE_TTL') or 60*60*24)
        if HAVE_DISKCACHE:
            try:
                self._diskcache = diskcache.Cache(str(cache_dir/'diskcache'))
                self._use_diskcache = True
            except Exception:
                self._diskcache = None
                self._use_diskcache = False
                # fallback to JSON
                self._cache_path = cache_dir / 'wiki_cache.json'
                try:
                    if self._cache_path.exists():
                        with open(self._cache_path, 'r', encoding='utf-8') as f:
                            self._cache = json.load(f)
                    else:
                        self._cache = {}
                except Exception:
                    self._cache = {}
        else:
            self._diskcache = None
            self._use_diskcache = False
            self._cache_path = cache_dir / 'wiki_cache.json'
            try:
                if self._cache_path.exists():
                    with open(self._cache_path, 'r', encoding='utf-8') as f:
                        self._cache = json.load(f)
                else:
                    self._cache = {}
            except Exception:
                self._cache = {}
        # load coda agent templates if present
        try:
            self._builtin_agents = self._load_coda_agents()
        except Exception:
            self._builtin_agents = {}
        # color codes for pretty output
        self._COLOR_HDR = '\033[1;34m'
        self._COLOR_OK = '\033[1;32m'
        self._COLOR_WARN = '\033[1;33m'
        self._COLOR_RESET = '\033[0m'

    def handle_instruction(self, instruction: str, auto_mode: bool = False,
                           session_auto_low: bool = False, session_auto_all: bool = False):
        # quick local handlers for trivial queries to avoid heavy model calls and extra approval
        if self._is_local_query(instruction):
            self._handle_local_query(instruction)
            return
        prompt = self._build_prompt(instruction)
        resp_text = self._call_ollama(prompt)
        if not resp_text:
            print('No response from model')
            return

        # Try to extract commands. If the model produced a natural-language answer
        # (explanations, paragraphs) we will print it and not attempt to execute.
        commands = self._extract_commands(resp_text)
        if not commands:
            # If the response looks like natural language, print a concise answer and return.
            if self._looks_like_natural_language(resp_text):
                # Print the model's answer (trim long output)
                out = resp_text.strip()
                if len(out) > 4000:
                    print(out[:4000] + '\n... (truncated)')
                else:
                    print(out)
                return
            # otherwise show the raw response for debugging but do not execute
            print('Model response contained no executable commands. Response:')
            print(resp_text)
            return

        # validate commands against detected OS
        issues = self._validate_commands_against_os(commands)
        require_strict_confirm = False
        if issues:
            print('\nCompatibility issues detected with host OS:')
            for it in issues:
                print(' -', it)
            print('These commands may not be safe to run on this machine. You must explicitly type "confirm" to proceed.')
            # bump risk significantly
            # we'll still call approval flow but require explicit confirm
            require_strict_confirm = True

        risk = self._assess_risk(commands)
        # Present concise command list and risk score
        for i, c in enumerate(commands, 1):
            print(f'[{i}] {c}')
        print(f'Risk score: {risk}/100')

        # fast-path: auto-approve trivial/zero-risk commands for a snappy experience
        if risk == 0 and self.auto_approve_zero_risk:
            logging.debug('Auto-approving zero-risk command')
            approved = True
        else:
            approved = False

        if not approved and auto_mode:
            # auto_mode means user requested !do; still ask unless set via env toggles or session toggles
            auto_all_env = os.getenv('AUTO_APPROVE_ALL', 'false').lower() == 'true'
            if auto_all_env or session_auto_all:
                approved = True

        if not approved:
            approved = self._interactive_approval(commands, risk, session_auto_low, session_auto_all, require_strict_confirm=require_strict_confirm)

        if approved:
            self._execute_commands(commands)
        else:
            print('Commands not approved. Aborting.')

    def _build_prompt(self, instruction: str) -> str:
        return (
            f"""
You are a terminal assistant. Given the user instruction, output a sequence of shell commands only.
Return them in a plain-text list or a markdown code block. Do not run them. Example:
```
ls -la
cd project
./install.sh
```
Target OS: {self.detected_os}
Only provide commands that are correct for the target OS. If the request depends on a specific distribution, prefer the detected distro. If unsure, ask a clarifying question instead of guessing.
User instruction: {instruction}
"""
        )

    def _call_ollama(self, prompt: str) -> str:
        url = f"{self.api_base}/api/generate"
        payload = {
            "model": self.model,
            "prompt": prompt,
            "max_tokens": 1024
        }
        headers = {'Content-Type': 'application/json'}
        if self.api_key:
            headers['Authorization'] = f'Bearer {self.api_key}'

        try:
            # Use session with backoff/retry and throttling helper
            r = self._request_with_retries('post', url, json=payload, headers=headers, timeout=60)
            if r is None:
                return ''
            r.raise_for_status()
            raw = r.text
            text_acc = ''
            # Heuristic: if raw contains multiple JSON objects ("}\n{" pattern) or repeated '{"model":', parse line-by-line
            if '\n{' in raw or raw.count('{"model":') > 1:
                parts = []
                for line in raw.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        j = json.loads(line)
                    except Exception:
                        parts.append(line)
                        continue
                    if isinstance(j, dict):
                        for key in ('response', 'text', 'output'):
                            if key in j and isinstance(j[key], str) and j[key]:
                                parts.append(j[key])
                        if 'choices' in j and isinstance(j['choices'], list):
                            for ch in j['choices']:
                                if isinstance(ch, dict):
                                    content = ch.get('content')
                                    if isinstance(content, list):
                                        for item in content:
                                            if isinstance(item, dict) and 'text' in item:
                                                parts.append(item['text'])
                    else:
                        parts.append(str(j))
                text_acc = ''.join(parts)
            else:
                try:
                    j = r.json()
                    if isinstance(j, dict):
                        if 'text' in j and j['text']:
                            text_acc = j['text']
                        elif 'output' in j and j['output']:
                            text_acc = j['output']
                        elif 'response' in j and j['response']:
                            text_acc = j['response']
                        elif 'choices' in j and isinstance(j['choices'], list):
                            pieces = []
                            for ch in j['choices']:
                                if isinstance(ch, dict):
                                    content = ch.get('content') or ch.get('message')
                                    if isinstance(content, list):
                                        for item in content:
                                            if isinstance(item, dict) and 'text' in item:
                                                pieces.append(item['text'])
                                    elif isinstance(content, str):
                                        pieces.append(content)
                            if pieces:
                                text_acc = '\n'.join(pieces)
                            else:
                                text_acc = json.dumps(j)
                    else:
                        text_acc = str(j)
                except Exception:
                    text_acc = raw

            return text_acc
        except Exception as e:
            logging.exception('Ollama call failed')
            print('Error calling Ollama API:', e)
            return ''

    def _looks_like_natural_language(self, text: str) -> bool:
        """Heuristic: detect if the model output is prose/explanations rather than shell commands."""
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        if not lines:
            return False
        sentencey = 0
        for l in lines:
            # lines that look like sentences: end with period or contain multiple words and verbs
            if len(l) > 40 and re.search(r"\b(is|was|are|do|did|has|have|will|would|should)\b", l, re.IGNORECASE):
                sentencey += 1
            if l.endswith('.') or l.endswith('?'):
                sentencey += 1
        return (sentencey / len(lines)) > 0.4

    def _request_with_retries(self, method: str, url: str, params=None, json=None, headers=None, timeout: float = 10):
        """Centralized request helper with per-host throttling and session retries.

        Returns requests.Response or None on repeated failure.
        """
        try:
            # ensure a sensible User-Agent to avoid blocks from some sites
            default_ua = {'User-Agent': os.getenv('SMART_TERM_UA') or 'Mozilla/5.0 (compatible; smart-terminal/1.0)'}
            if headers:
                # do not mutate caller dict
                h = dict(default_ua)
                h.update(headers)
            else:
                h = default_ua
            host = requests.utils.urlparse(url).netloc
            last = self._host_last.get(host)
            if last:
                elapsed = time.time() - last
                if elapsed < self._min_interval:
                    to_wait = self._min_interval - elapsed
                    time.sleep(to_wait)
            # perform request
            if method.lower() == 'get':
                r = self.session.get(url, params=params, headers=h, timeout=timeout)
            elif method.lower() == 'post':
                r = self.session.post(url, params=params, json=json, headers=h, timeout=timeout)
            else:
                r = self.session.request(method, url, params=params, json=json, headers=h, timeout=timeout)
            # update last timestamp
            self._host_last[host] = time.time()
            return r
        except Exception as e:
            logging.debug('Request failed to %s: %s', url, e)
            return None

    def _cache_get(self, key: str, ttl: int):
        if self._use_diskcache and self._diskcache is not None:
            try:
                val = self._diskcache.get(key)
                return val
            except Exception:
                return None
        entry = self._cache.get(key)
        if not entry:
            return None
        ts = entry.get('ts', 0)
        if time.time() - ts > ttl:
            return None
        return entry.get('value')

    def _cache_set(self, key: str, value):
        if self._use_diskcache and self._diskcache is not None:
            try:
                # diskcache supports TTL per item but we will rely on our TTL check when reading
                self._diskcache.set(key, value)
                return
            except Exception:
                logging.debug('diskcache write failed; falling back to JSON')
        try:
            self._cache[key] = {'ts': int(time.time()), 'value': value}
            with open(self._cache_path, 'w', encoding='utf-8') as f:
                json.dump(self._cache, f)
        except Exception:
            logging.debug('Failed to write cache to disk')

    def _make_cache_key(self, url: str, params: dict | None):
        m = hashlib.sha256()
        m.update(url.encode('utf-8'))
        if params:
            m.update(json.dumps(params, sort_keys=True).encode('utf-8'))
        return m.hexdigest()

    def clear_cache(self):
        """Clear the on-disk cache (diskcache if available, otherwise JSON file)."""
        try:
            if self._use_diskcache and self._diskcache is not None:
                try:
                    self._diskcache.clear()
                    print('Diskcache cleared')
                    return
                except Exception:
                    logging.debug('Failed to clear diskcache; falling back to JSON')
            # fallback: remove JSON cache file and in-memory dict
            try:
                self._cache = {}
                if hasattr(self, '_cache_path') and self._cache_path.exists():
                    try:
                        self._cache_path.unlink()
                    except Exception:
                        pass
                print('JSON cache cleared')
            except Exception:
                print('Failed to clear cache')
        except Exception as e:
            logging.exception('Error clearing cache')
            print('Error clearing cache:', e)

    def chat(self, instruction: str) -> str:
        """Ask the model a question and return the plain-text answer (no execution)."""
        prompt = (
            f"""
You are a helpful assistant. Answer the user's question concisely in plain text. Do not output shell commands or code blocks unless explicitly asked.
User question: {instruction}
"""
        )
        resp = self._call_ollama(prompt)
        return resp.strip()

    # ── Agentic smart-instruction flow ──

    def handle_smart_instruction(self, instruction: str):
        """AI-driven multi-step handler: diagnose system → web-research → plan → confirm → execute."""
        if not self.api_base or not self.model:
            print('Please set OLLAMA_API_BASE and OLLAMA_MODEL first.')
            return

        # ── Step 1: Ask the LLM what diagnostic commands to run ──
        diag_prompt = (
            f"You are a terminal assistant on {self.detected_os}. "
            f"The user wants to: {instruction}\n\n"
            "What shell commands should be run FIRST to check the current system state "
            "before taking any action? Output ONLY a JSON array of short diagnostic commands. "
            'Example: ["node --version", "which node"]\n'
            "Keep it to 1-5 commands maximum. Output ONLY the JSON array, nothing else."
        )
        diag_resp = self._call_ollama(diag_prompt)
        diag_commands = self._parse_json_array(diag_resp)

        # ── Step 2: Run diagnostic commands and capture output ──
        diag_output = {}
        if diag_commands:
            print(f'\n{self._COLOR_HDR}Checking current state...{self._COLOR_RESET}')
            for cmd in diag_commands[:5]:
                # safety: skip obviously dangerous commands
                if self._assess_risk([cmd]) > 30:
                    continue
                try:
                    shell_cmd = ['cmd', '/c', cmd] if self.detected_os == 'windows' else ['zsh', '-lc', cmd]
                    res = subprocess.run(
                        shell_cmd,
                        capture_output=True, text=True, timeout=15
                    )
                    output = (res.stdout + res.stderr).strip()
                    diag_output[cmd] = output or '(no output)'
                    print(f'  $ {cmd}  →  {output[:120]}')
                except subprocess.TimeoutExpired:
                    diag_output[cmd] = '(timed out)'
                except Exception as e:
                    diag_output[cmd] = f'(error: {e})'

        # ── Step 3: Web search for latest version / info ──
        web_context = self._web_search_context(instruction)

        # ── Step 4: Send everything to LLM for diagnosis + action plan ──
        diag_block = '\n'.join(f'$ {k}\n{v}' for k, v in diag_output.items()) if diag_output else '(no diagnostics run)'
        web_block = web_context if web_context else '(no web results)'

        plan_prompt = (
            f"You are a terminal assistant on {self.detected_os}. "
            f"The user wants to: {instruction}\n\n"
            f"Current system state:\n{diag_block}\n\n"
            f"Latest info from the web:\n{web_block}\n\n"
            "Based on the above:\n"
            "1. Start with a brief STATUS line (what is installed now, what is the latest, is action needed?).\n"
            "2. If action IS needed, output the exact shell commands in a ```bash code block.\n"
            "3. If NO action is needed, say so and do not output any commands.\n"
            "Be specific and concise. Use commands appropriate for " + self.detected_os + "."
        )
        plan_resp = self._call_ollama(plan_prompt)
        if not plan_resp or not plan_resp.strip():
            print('No response from model.')
            return

        # ── Step 5: Extract commands (if any) and present plan ──
        commands = self._extract_commands(plan_resp)
        # Print the status/diagnosis part (everything that isn't a command)
        # Remove code fences from the display text to avoid duplication
        display_text = re.sub(r'```(?:bash|sh|shell)?\n[\s\S]*?```', '', plan_resp).strip()
        if display_text:
            print(f'\n{display_text}')

        if not commands:
            # No action needed — diagnosis was the answer
            return

        # ── Step 6: Show commands and ask for confirmation ──
        print(f'\n{self._COLOR_HDR}Proposed commands:{self._COLOR_RESET}')
        for i, c in enumerate(commands, 1):
            print(f'  [{i}] {c}')

        risk = self._assess_risk(commands)
        print(f'  Risk score: {risk}/100')

        # Check for OS compatibility issues
        issues = self._validate_commands_against_os(commands)
        if issues:
            print(f'\n{self._COLOR_WARN}Compatibility warnings:{self._COLOR_RESET}')
            for issue in issues:
                print(f'  - {issue}')

        print(f'\nApply these changes? [y/N] ', end='')
        sys.stdout.flush()
        try:
            ans = input().strip().lower()
        except (EOFError, KeyboardInterrupt):
            ans = ''
        if ans not in ('y', 'yes'):
            print('Aborted.')
            return

        # ── Step 7: Execute ──
        self._execute_commands(commands)

    def _web_search_context(self, instruction: str) -> str:
        """Gather web search context for an instruction. Returns a text block (no printing)."""
        parts = []
        # Extract a search query from the instruction
        search_query = instruction.strip()

        # Try Wikipedia
        wp = self._wikipedia_context(search_query)
        if wp:
            parts.append(wp.get('text', '')[:1500])

        # Try DDGS
        if HAVE_DDGS:
            results = self._ddgs_search(f'latest {search_query}', max_results=5)
            for r in results[:3]:
                text = r.get('text', '').strip()
                if text:
                    parts.append(f"{r.get('title','')}: {text[:500]}")

        return '\n\n'.join(parts)

    def _parse_json_array(self, text: str) -> list:
        """Try to extract a JSON array from model output."""
        if not text:
            return []
        # Find JSON array in the response
        m = re.search(r'\[.*?\]', text, re.S)
        if m:
            try:
                arr = json.loads(m.group(0))
                if isinstance(arr, list):
                    return [str(x) for x in arr]
            except json.JSONDecodeError:
                pass
        return []

    def handle_web_fetch(self, url: str):
        """Fetch a URL and print a concise summary of the response."""
        try:
            # Prefer trafilatura for clean main-text extraction, fallback to BeautifulSoup or raw HTML
            r = self._request_with_retries('get', url, timeout=20)
            if r is None:
                print('Error fetching URL: request failed')
                return
            r.raise_for_status()
            html = r.text
            content = None
            if HAVE_TRAFILATURA:
                try:
                    content = trafilatura.extract(html)
                except Exception:
                    content = None
            if not content and HAVE_BS4:
                try:
                    soup = BeautifulSoup(html, 'html.parser')
                    # prefer article or main tags
                    main = soup.find('article') or soup.find('main')
                    if main:
                        content = '\n'.join(p.get_text().strip() for p in main.find_all('p') if p.get_text().strip())
                    else:
                        # fallback: first few paragraphs
                        ps = soup.find_all('p')
                        content = '\n'.join(p.get_text().strip() for p in ps[:10])
                except Exception:
                    content = None
            # final fallback: raw HTML truncated
            if not content:
                snippet = html[:8000]
                self._pretty_print(f'Fetched {url} — status {r.status_code}. Raw HTML (truncated):\n{snippet}')
            else:
                self._pretty_print(f'Fetched {url} — status {r.status_code}. Extracted content:')
                self._pretty_print(content)
                # offer summarized batch answer
                self._maybe_batch_summarize(content)
        except Exception as e:
            print('Error fetching URL:', e)

    def handle_web_search(self, query: str):
        """Search the web and return an AI-synthesized answer based on gathered sources."""
        try:
            # ── Quick structured-data paths (age, population) ──
            # "how old is X" → Wikidata birth/inception year
            quick = self._try_age_query(query)
            if quick:
                return
            # "X population" → Wikidata P1082
            quick = self._try_population_query(query)
            if quick:
                return

            # ── Gather context from multiple sources ──
            sources = []  # list of {'title', 'url', 'text'}

            # 1) Wikipedia — most reliable for factual queries
            wp_ctx = self._wikipedia_context(query)
            if wp_ctx:
                sources.append(wp_ctx)

            # 2) DDGS text search — real web results
            if HAVE_DDGS:
                ddg_results = self._ddgs_search(query, max_results=8)
                for item in ddg_results:
                    sources.append(item)

            # 3) If nothing from DDGS, try DuckDuckGo instant answer API
            if len(sources) <= 1:
                ia = self._ddg_instant_answer(query)
                if ia:
                    sources.append(ia)

            if not sources:
                print('No search results found for that query.')
                return

            # ── Optionally fetch full content from the best sources ──
            # Pick up to 2 promising URLs to deep-fetch for richer context
            fetched_extra = 0
            for src in list(sources):
                if fetched_extra >= 2:
                    break
                url = src.get('url', '')
                # skip already-rich sources (Wikipedia context is usually enough)
                if src.get('_source') == 'wikipedia':
                    continue
                if not url or not url.startswith('http'):
                    continue
                # only fetch from domains likely to have useful content
                existing_text = src.get('text', '')
                if len(existing_text) > 300:
                    continue  # snippet is already decent
                try:
                    body = self._fetch_page_text(url, timeout=8)
                    if body and len(body) > len(existing_text) + 100:
                        src['text'] = body[:3000]
                        fetched_extra += 1
                except Exception:
                    pass

            # ── Build context and ask the LLM to synthesize an answer ──
            context_parts = []
            ref_list = []
            for i, src in enumerate(sources[:6], 1):
                title = src.get('title', f'Source {i}')
                url = src.get('url', '')
                text = src.get('text', '').strip()
                if not text:
                    continue
                # cap each source to prevent overwhelming the prompt
                if len(text) > 2000:
                    text = text[:2000] + '...'
                context_parts.append(f"[Source {i}: {title}]\n{text}")
                if url:
                    ref_list.append(f"[{i}] {title} — {url}")

            if not context_parts:
                print('Search returned results but no usable content.')
                return

            context_block = '\n\n'.join(context_parts)
            prompt = (
                "You are a knowledgeable assistant. Answer the user's question directly and concisely. "
                "Use the search results below as supporting context, but also use your own knowledge to give the best answer. "
                "Give ONLY the answer — no disclaimers, no meta-commentary about the sources, no hedging. "
                "Be factual and specific. Keep your answer to 1-3 short paragraphs.\n\n"
                f"Question: {query}\n\n"
                f"Context:\n{context_block}\n\n"
                "Answer:"
            )

            # Check if we have a model configured
            if not self.api_base or not self.model:
                # No model available — fall back to printing raw results
                print(f"{self._COLOR_HDR}Search results for: {query}{self._COLOR_RESET}\n")
                for src in sources[:5]:
                    title = src.get('title', '')
                    url = src.get('url', '')
                    text = src.get('text', '')[:200]
                    if title:
                        print(f"{self._COLOR_HDR}- {title}{self._COLOR_RESET}")
                        if text:
                            print(f"  {text.strip()}")
                        if url:
                            print(f"  {url}")
                return

            answer = self._call_ollama(prompt)
            if answer and answer.strip():
                print(f"\n{answer.strip()}\n")
            else:
                # Model returned nothing — print raw results
                print(f"{self._COLOR_HDR}Could not generate answer. Raw results:{self._COLOR_RESET}\n")
                for src in sources[:5]:
                    title = src.get('title', '')
                    url = src.get('url', '')
                    text = src.get('text', '')[:200]
                    if title:
                        print(f"- {title}")
                        if text:
                            print(f"  {text.strip()}")
                        if url:
                            print(f"  {url}")
        except Exception as e:
            logging.exception('Error in web search')
            print('Error performing web search:', e)

    # ── Web search helper methods ──

    # Junk domains to exclude from search results
    _JUNK_DOMAINS = {
        'tripadvisor.com', 'booking.com', 'expedia.com', 'hotels.com',
        'agoda.com', 'kayak.com', 'trivago.com', 'airbnb.com',
        'amazon.com', 'ebay.com', 'etsy.com', 'alibaba.com',
        'pinterest.com', 'instagram.com', 'facebook.com', 'tiktok.com',
        'twitter.com', 'x.com', 'linkedin.com',
    }

    def _is_junk_result(self, url: str, title: str = '', body: str = '') -> bool:
        """Filter out ad-like, e-commerce, and social media results."""
        if not url:
            return True
        try:
            host = requests.utils.urlparse(url).netloc.lower()
            # strip www.
            host = re.sub(r'^www\.', '', host)
            for junk in self._JUNK_DOMAINS:
                if host == junk or host.endswith('.' + junk):
                    return True
        except Exception:
            pass
        # detect ad-like titles
        lower_title = (title or '').lower()
        ad_phrases = ['closest hotels', 'book now', 'best deals', 'buy online', 'shop now', 'free shipping']
        for phrase in ad_phrases:
            if phrase in lower_title:
                return True
        return False

    def _ddgs_search(self, query: str, max_results: int = 8) -> list:
        """Run DDGS text search and return filtered results as dicts."""
        results = []
        try:
            with DDGS() as ddgs:
                raw = list(ddgs.text(query, max_results=max_results))
                for item in raw:
                    title = item.get('title', '')
                    href = item.get('href', '')
                    body = item.get('body', '')
                    if self._is_junk_result(href, title, body):
                        continue
                    results.append({
                        'title': title,
                        'url': href,
                        'text': body,
                        '_source': 'ddgs',
                    })
        except Exception as e:
            logging.debug('DDGS search failed: %s', e)
        return results

    def _ddg_instant_answer(self, query: str) -> dict | None:
        """Try DuckDuckGo instant answer API."""
        try:
            params = {'q': query, 'format': 'json', 'no_redirect': 1, 'no_html': 1}
            r = self._request_with_retries('get', 'https://api.duckduckgo.com/', params=params, timeout=10)
            if r is None:
                return None
            r.raise_for_status()
            j = r.json()
            abstract = j.get('AbstractText') or ''
            heading = j.get('Heading') or ''
            url = j.get('AbstractURL') or ''
            if abstract:
                return {'title': heading or 'DuckDuckGo Instant Answer', 'url': url, 'text': abstract, '_source': 'ddg_ia'}
        except Exception:
            pass
        return None

    def _wikipedia_context(self, query: str) -> dict | None:
        """Try to get a Wikipedia summary for the query. Returns a source dict or None."""
        try:
            # Extract a good search term from the query
            search_term = query.strip()
            # strip common question prefixes
            search_term = re.sub(
                r"^(how\s+many|how\s+much|what\s+is|what\s+are|where\s+is|where\s+are|who\s+is|who\s+are|when\s+was|when\s+were|why\s+is|why\s+are|tell\s+me\s+about)\s+",
                '', search_term, flags=re.IGNORECASE
            ).strip()
            search_term = re.sub(r"^(the|a|an)\s+", '', search_term, flags=re.IGNORECASE).strip()
            search_term = search_term.rstrip(' ?!.')

            if not search_term:
                return None

            wp_url = 'https://en.wikipedia.org/w/api.php'
            wp_params = {'action': 'opensearch', 'search': search_term, 'limit': 3, 'namespace': 0, 'format': 'json'}
            cache_key = self._make_cache_key(wp_url, wp_params)
            osj = self._cache_get(cache_key, self._wiki_ttl)
            if osj is None:
                r = self._request_with_retries('get', wp_url, params=wp_params, timeout=8)
                if r is None:
                    return None
                r.raise_for_status()
                osj = r.json()
                self._cache_set(cache_key, osj)

            titles = osj[1] if isinstance(osj, list) and len(osj) > 1 else []
            if not titles:
                return None

            title = titles[0]
            sum_url = f'https://en.wikipedia.org/api/rest_v1/page/summary/{requests.utils.requote_uri(title)}'
            sum_cache_key = self._make_cache_key(sum_url, None)
            sj = self._cache_get(sum_cache_key, self._wiki_ttl)
            if sj is None:
                r2 = self._request_with_retries('get', sum_url, timeout=8)
                if r2 is None:
                    return None
                r2.raise_for_status()
                sj = r2.json()
                self._cache_set(sum_cache_key, sj)

            extract = sj.get('extract') or sj.get('description') or ''
            page_url = sj.get('content_urls', {}).get('desktop', {}).get('page', '')
            if extract:
                return {'title': f'Wikipedia: {title}', 'url': page_url, 'text': extract, '_source': 'wikipedia'}
        except Exception:
            pass
        return None

    def _fetch_page_text(self, url: str, timeout: int = 8) -> str | None:
        """Fetch a URL and extract main text content. Returns text or None."""
        try:
            r = self._request_with_retries('get', url, timeout=timeout)
            if r is None:
                return None
            r.raise_for_status()
            html = r.text
            # Prefer trafilatura for clean extraction
            if HAVE_TRAFILATURA:
                try:
                    text = trafilatura.extract(html)
                    if text:
                        return text
                except Exception:
                    pass
            # Fallback to BeautifulSoup
            if HAVE_BS4:
                try:
                    soup = BeautifulSoup(html, 'html.parser')
                    main = soup.find('article') or soup.find('main')
                    if main:
                        return '\n'.join(p.get_text().strip() for p in main.find_all('p') if p.get_text().strip())
                    ps = soup.find_all('p')
                    return '\n'.join(p.get_text().strip() for p in ps[:15])
                except Exception:
                    pass
            return None
        except Exception:
            return None

    def _try_age_query(self, query: str) -> bool:
        """Handle 'how old is X' queries via Wikidata. Returns True if answered."""
        m = re.match(r"how\s+old\s+(?:is|are)\s+(.+)", query, flags=re.IGNORECASE)
        if not m:
            return False
        entity = m.group(1).strip()
        entity = re.sub(r"^(the|a|an)\s+", '', entity, flags=re.IGNORECASE).strip()
        entity = entity.rstrip(' ?!.')
        try:
            wp_url = 'https://en.wikipedia.org/w/api.php'
            wp_params = {'action': 'opensearch', 'search': entity, 'limit': 1, 'namespace': 0, 'format': 'json'}
            cache_key = self._make_cache_key(wp_url, wp_params)
            osj = self._cache_get(cache_key, self._wiki_ttl)
            if osj is None:
                r = self._request_with_retries('get', wp_url, params=wp_params, timeout=8)
                if r is None:
                    return False
                r.raise_for_status()
                osj = r.json()
                self._cache_set(cache_key, osj)
            titles = osj[1] if isinstance(osj, list) and len(osj) > 1 else []
            if not titles:
                return False
            title = titles[0].lstrip('/').strip()
            sum_url = f'https://en.wikipedia.org/api/rest_v1/page/summary/{requests.utils.requote_uri(title)}'
            sum_cache_key = self._make_cache_key(sum_url, None)
            sj2 = self._cache_get(sum_cache_key, self._wiki_ttl)
            if sj2 is None:
                r2 = self._request_with_retries('get', sum_url, timeout=8)
                if r2 is None:
                    return False
                r2.raise_for_status()
                sj2 = r2.json()
                self._cache_set(sum_cache_key, sj2)
            if not sj2:
                return False
            extract = sj2.get('extract') or ''
            wikibase = sj2.get('wikibase_item')
            year = None
            wikidata_label = None
            if wikibase:
                try:
                    wd_url = f'https://www.wikidata.org/wiki/Special:EntityData/{wikibase}.json'
                    wd_cache_key = self._make_cache_key(wd_url, None)
                    wj = self._cache_get(wd_cache_key, self._wiki_ttl)
                    if wj is None:
                        rwd = self._request_with_retries('get', wd_url, timeout=8)
                        if rwd is None:
                            wj = None
                        else:
                            rwd.raise_for_status()
                            wj = rwd.json()
                            self._cache_set(wd_cache_key, wj)
                    if wj:
                        ent = wj.get('entities', {}).get(wikibase, {})
                        claims = ent.get('claims', {})
                        year, wikidata_label = self._extract_year_from_wikidata_claims(claims)
                except Exception:
                    year = None
            # fallback to extract text
            if not year:
                y = re.search(r"born[^\d\n\r]{0,30}(\d{4})", extract, flags=re.IGNORECASE)
                if y:
                    wikidata_label = wikidata_label or 'born'
                else:
                    y = re.search(r"(founded|established|launched|created|started).*?(\d{4})", extract, flags=re.IGNORECASE)
                    if y:
                        wikidata_label = wikidata_label or 'founded'
                if not y:
                    y = re.search(r"\b(\d{4})\b", extract)
                if y:
                    try:
                        if y.lastindex and y.lastindex >= 2:
                            year = int(y.group(2))
                        else:
                            year = int(y.group(1))
                    except Exception:
                        year = None
            if year:
                from datetime import datetime
                age = datetime.now().year - year
                label = wikidata_label or 'founded'
                print(f"{title} is approximately {age} years old ({label} {year}).")
                return True
        except Exception:
            pass
        return False

    def _try_population_query(self, query: str) -> bool:
        """Handle population queries via Wikidata P1082. Returns True if answered."""
        if not re.search(r"population", query, flags=re.IGNORECASE):
            return False
        pop_entity = query
        pm1 = re.search(r"(.+?)\s+population", query, flags=re.IGNORECASE)
        pm2 = re.search(r"population\s+of\s+(.+)", query, flags=re.IGNORECASE)
        if pm1:
            pop_entity = pm1.group(1).strip()
        elif pm2:
            pop_entity = pm2.group(1).strip()
        pop_entity = re.sub(r"^(the|a|an)\s+", '', pop_entity, flags=re.IGNORECASE).strip().rstrip(' ?!.')
        try:
            wp_url = 'https://en.wikipedia.org/w/api.php'
            wp_params = {'action': 'opensearch', 'search': pop_entity, 'limit': 1, 'namespace': 0, 'format': 'json'}
            cache_key = self._make_cache_key(wp_url, wp_params)
            osj = self._cache_get(cache_key, self._wiki_ttl)
            if osj is None:
                r = self._request_with_retries('get', wp_url, params=wp_params, timeout=8)
                if r is not None:
                    r.raise_for_status()
                    osj = r.json()
                    self._cache_set(cache_key, osj)
            if not osj:
                return False
            titles = osj[1] if isinstance(osj, list) and len(osj) > 1 else []
            if not titles:
                return False
            title = titles[0]
            sum_url = f'https://en.wikipedia.org/api/rest_v1/page/summary/{requests.utils.requote_uri(title)}'
            sum_cache_key = self._make_cache_key(sum_url, None)
            sj2 = self._cache_get(sum_cache_key, self._wiki_ttl)
            if sj2 is None:
                r2 = self._request_with_retries('get', sum_url, timeout=8)
                if r2 is not None:
                    r2.raise_for_status()
                    sj2 = r2.json()
                    self._cache_set(sum_cache_key, sj2)
            if not sj2:
                return False
            wikibase = sj2.get('wikibase_item')
            if wikibase:
                wd_url = f'https://www.wikidata.org/wiki/Special:EntityData/{wikibase}.json'
                wd_cache_key = self._make_cache_key(wd_url, None)
                wj = self._cache_get(wd_cache_key, self._wiki_ttl)
                if wj is None:
                    rwd = self._request_with_retries('get', wd_url, timeout=8)
                    if rwd is not None:
                        rwd.raise_for_status()
                        wj = rwd.json()
                        self._cache_set(wd_cache_key, wj)
                if wj:
                    ent = wj.get('entities', {}).get(wikibase, {})
                    claims = ent.get('claims', {})
                    pop, pop_year = self._extract_population_from_wikidata_claims(claims)
                    if pop:
                        pop_fmt = f"{pop:,}"
                        if pop_year:
                            print(f"{title} population: {pop_fmt} (as of {pop_year})")
                        else:
                            print(f"{title} population: {pop_fmt}")
                        return True
        except Exception:
            pass
        return False

    def handle_web_scrape(self, url: str):
        """Fetch page and print main HTML (no rendering)."""
        try:
            # If Playwright is available, use it for JS-rendered pages
            html = None
            if HAVE_PLAYWRIGHT:
                try:
                    with sync_playwright() as pw:
                        browser = pw.chromium.launch(headless=True)
                        page = browser.new_page()
                        page.goto(url, wait_until='networkidle', timeout=20000)
                        html = page.content()
                        browser.close()
                except Exception:
                    html = None

            if not html:
                r = self._request_with_retries('get', url, timeout=15)
                if r is None:
                    print('Error scraping URL: request failed')
                    return
                r.raise_for_status()
                html = r.text

            # Try to extract main content using trafilatura or BeautifulSoup
            content = None
            if HAVE_TRAFILATURA:
                try:
                    content = trafilatura.extract(html)
                except Exception:
                    content = None
            if not content and HAVE_BS4:
                try:
                    soup = BeautifulSoup(html, 'html.parser')
                    main = soup.find('article') or soup.find('main')
                    if main:
                        content = '\n'.join(p.get_text().strip() for p in main.find_all('p') if p.get_text().strip())
                    else:
                        ps = soup.find_all('p')
                        content = '\n'.join(p.get_text().strip() for p in ps[:20])
                except Exception:
                    content = None

            if content:
                print(self._COLOR_HDR + f'Fetched {url} — extracted content:' + self._COLOR_RESET)
                self._pretty_print(content)
                self._maybe_batch_summarize(content)
            else:
                print(self._COLOR_HDR + f'Fetched {url} — HTML (truncated):' + self._COLOR_RESET)
                print(html[:16000])
        except Exception as e:
            print('Error scraping URL:', e)

    def _is_local_query(self, instruction: str) -> bool:
        """Detect trivial queries we can resolve locally without calling the model."""
        s = instruction.strip().lower()
        # common info queries
        patterns = [r"what\s+is\s+my\s+os", r"what\s+is\s+my\s+operating\s+system", r"which\s+os", r"what\s+is\s+my\s+platform", r"what\s+is\s+my\s+uname"]
        for p in patterns:
            if re.search(p, s):
                return True
        # short commands like 'whoami' or 'pwd' could be local but may be model-inferred; skip for now
        return False

    def _load_coda_agents(self):
        """Load simple agent templates from smart_terminal/agents/*.md into a dict.

        Returns: {name: {'description': str, 'content': str, 'path': Path}}
        """
        agents_dir = Path(__file__).resolve().parent / 'agents'
        agents = {}
        if not agents_dir.exists():
            return agents
        for md in agents_dir.glob('*.md'):
            try:
                txt = md.read_text(encoding='utf-8')
                # parse simple YAML frontmatter
                m = re.match(r"---\n(.*?)\n---\n(.*)", txt, flags=re.S)
                if m:
                    fm = m.group(1)
                    body = m.group(2).strip()
                    # find name/description fields
                    name = None
                    desc = None
                    for line in fm.splitlines():
                        if line.startswith('name:') and not name:
                            name = line.split(':',1)[1].strip()
                        if line.startswith('description:') and not desc:
                            desc = line.split(':',1)[1].strip()
                    key = name or md.stem
                    agents[key] = {'description': desc or '', 'content': body, 'path': md}
                else:
                    agents[md.stem] = {'description': '', 'content': txt, 'path': md}
            except Exception:
                continue
        return agents

    def run_coda_agent(self, agent_name: str, question: str) -> str:
        """Run a coda agent template by name with the provided question and return model output."""
        ag = self._builtin_agents.get(agent_name)
        if not ag:
            raise KeyError(f"Agent template not found: {agent_name}")
        prompt = f"{ag['content']}\n\nUser question: {question}\n\nProvide a concise, actionable response." 
        resp = self._call_ollama(prompt)
        return resp

    def _pretty_print(self, text: str):
        """Nicely print multi-line text with minimal formatting."""
        # trim long leading/trailing whitespace
        t = text.strip()
        # collapse multiple blank lines
        t = re.sub(r"\n{3,}", '\n\n', t)
        # print with a separator header if long
        if len(t) > 1000:
            print('--- BEGIN RESULT (truncated view) ---')
            print(t[:4000])
            print('...')
            print('--- END RESULT ---')
        else:
            print(t)

    def _maybe_batch_summarize(self, content: str):
        """Prompt the user to generate a summarized/batched answer using the model when content is long or complex."""
        # decide if summarization is useful
        if not content or len(content) < 200:
            return
        # skip prompt when stdin is not a terminal (piped / non-interactive)
        if not sys.stdin.isatty():
            return
        print('\nWould you like a concise summary or next-actions based on the above? [y/N]')
        try:
            ans = input('> ').strip().lower()
        except (EOFError, KeyboardInterrupt):
            return
        if ans != 'y':
            return
        prompt = (
            "You are an assistant that summarizes web search results or scraped content. "
            "Provide a concise 3-bullet summary and 3 suggested next shell actions the user can take to investigate or act on this information. "
            "Do not include code, just human-readable bullets.\n\n" + content
        )
        summary = self._call_ollama(prompt)
        if summary:
            print('\n=== Summary / Suggested Actions ===')
            print(summary)

    def _handle_local_query(self, instruction: str):
        s = instruction.strip().lower()
        if re.search(r"what\s+is\s+my\s+os|which\s+os|what\s+is\s+my\s+operating\s+system", s):
            # Provide quick local OS info without model call
            try:
                if self.detected_os == 'windows':
                    out = subprocess.check_output(
                        ['cmd', '/c', 'ver'],
                        text=True, stderr=subprocess.STDOUT
                    )
                    print(out.strip())
                    print(f'Platform: {platform.platform()}')
                elif self.detected_os == 'macos':
                    # run sw_vers for detailed macOS info
                    out = subprocess.check_output(['sw_vers'], text=True, stderr=subprocess.STDOUT)
                    print(out)
                elif self.detected_os in ('debian', 'redhat', 'arch', 'linux'):
                    # attempt lsb_release or /etc/os-release
                    try:
                        out = subprocess.check_output(['lsb_release', '-a'], text=True, stderr=subprocess.STDOUT)
                        print(out)
                    except Exception:
                        try:
                            with open('/etc/os-release', 'r') as f:
                                print(f.read())
                        except Exception:
                            print(platform.platform())
                else:
                    print(platform.platform())
            except Exception:
                # fallback
                print(platform.platform())
            return
        # fallback: not handled
        print('No local handler for that query; proceeding to model (this should be rare)')

    def _extract_commands(self, text: str) -> List[str]:
        # Extract code fences first
        cmds = []
        fences = re.findall(r"```(?:bash|sh|shell)?\n([\s\S]*?)```", text, flags=re.IGNORECASE)
        # support responses where newlines are escaped (JSON-encoded), e.g. "```bash\nsudo...\n```"
        if not fences and '\\n' in text and '```' in text:
            un = text.replace('\\n', '\n')
            fences = re.findall(r"```(?:bash|sh|shell)?\n([\s\S]*?)```", un, flags=re.IGNORECASE)
        for f in fences:
            for line in f.splitlines():
                line = line.strip()
                if not line:
                    continue
                # strip leading numbering like '[1]' or '1.'
                line = re.sub(r'^\[?\d+\]?[:\.]?\s*', '', line)
                # strip leading $ if present
                if line.startswith('$'):
                    line = line[1:].strip()
                cmds.append(line)

        if not cmds:
            # fallback: look for lines that look like commands
            for line in text.splitlines():
                s = line.strip()
                if not s:
                    continue
                # strip leading numbering like '[1]' or '1.'
                s = re.sub(r'^\[?\d+\]?[:\.]?\s*', '', s)
                if re.match(r"^(sudo\s+|rm\s+|mv\s+|cp\s+|curl\s+|wget\s+|git\s+|docker\s+|brew\s+|pip\s+|npm\s+|pnpm\s+|chmod\s+|chown\s+|systemctl\s+)", s):
                    if s.startswith('$'):
                        s = s[1:].strip()
                    cmds.append(s)

        # Post-process to join option/continuation lines with previous command.
        cleaned: List[str] = []
        for c in cmds:
            if not cleaned:
                cleaned.append(c)
                continue
            # if current starts with a dash or is an argument-only fragment, join to previous
            if re.match(r"^[-]{1,2}\w|^[|&<>]", c) or c.startswith('-'):
                cleaned[-1] = cleaned[-1].rstrip() + ' ' + c.lstrip()
            # if previous ends with a backslash, continue it
            elif cleaned[-1].endswith('\\'):
                cleaned[-1] = cleaned[-1].rstrip('\\') + c
            else:
                cleaned.append(c)

        # remove empty and duplicates while preserving order
        seen = set()
        final: List[str] = []
        for c in cleaned:
            if not c or c in seen:
                continue
            seen.add(c)
            final.append(c)
        return final

    def _detect_os(self) -> str:
        """Return a simple OS identifier: 'windows', 'macos', 'debian', 'redhat', 'arch', or 'unknown'."""
        sysname = platform.system().lower()
        if sysname == 'windows':
            return 'windows'
        if sysname == 'darwin':
            return 'macos'
        if sysname == 'linux':
            # try /etc/os-release
            try:
                with open('/etc/os-release', 'r') as f:
                    data = f.read()
                m = re.search(r"^id=(.+)$", data, flags=re.MULTILINE)
                if m:
                    ident = m.group(1).strip().strip('"').lower()
                    if ident in ('ubuntu', 'debian', 'pop', 'linuxmint'):
                        return 'debian'
                    if ident in ('centos', 'rhel', 'fedora', 'rocky'):
                        return 'redhat'
                    if ident in ('arch', 'manjaro'):
                        return 'arch'
            except Exception:
                pass
            return 'linux'
        return 'unknown'

    def _validate_commands_against_os(self, commands: List[str]) -> List[str]:
        """Return list of issues found where commands appear incompatible with detected OS."""
        issues = []
        osid = self.detected_os
        for c in commands:
            lc = c.lower()
            if re.search(r"\bapt\b|apt-get\b|dpkg\b", lc) and osid not in ('debian', 'linux'):
                issues.append(f"Command '{c}' uses apt but host is {osid}")
            if re.search(r"\byum\b|dnf\b|rpm\b", lc) and osid not in ('redhat', 'linux'):
                issues.append(f"Command '{c}' uses yum/dnf/rpm but host is {osid}")
            if re.search(r"\bbrew\b", lc) and osid != 'macos':
                issues.append(f"Command '{c}' uses brew but host is {osid}")
            if re.search(r"\bpacman\b", lc) and osid != 'arch':
                issues.append(f"Command '{c}' uses pacman but host is {osid}")
            if re.search(r"\bsudo\b", lc) and osid == 'windows':
                issues.append(f"Command '{c}' uses sudo but host is Windows (use elevated shell or gsudo)")
            if re.search(r"\bapt\b|apt-get\b|dpkg\b|yum\b|dnf\b|rpm\b|pacman\b", lc) and osid == 'windows':
                issues.append(f"Command '{c}' uses a Linux package manager but host is Windows")
            if re.search(r"\bchoco\b|\bwinget\b|\bscoop\b", lc) and osid not in ('windows',):
                issues.append(f"Command '{c}' uses a Windows package manager but host is {osid}")
        return issues

    # --- Wikidata extraction helpers (unit-testable) ---
    def _extract_year_from_wikidata_claims(self, claims: dict):
        """Given a Wikidata claims dict for an entity, try to extract a year and label.

        Returns (year:int or None, label:str or None) where label is 'born' or 'founded'.
        """
        for pid in ('P569', 'P571'):
            if pid in claims:
                for cl in claims[pid]:
                    try:
                        sn = cl.get('mainsnak', {})
                        dv = sn.get('datavalue', {})
                        val = dv.get('value') if isinstance(dv, dict) else None
                        if isinstance(val, dict) and 'time' in val:
                            t = val['time']
                            m2 = re.search(r"([+-]?\d{4})", t)
                            if m2:
                                year = int(m2.group(1))
                                return year, ('born' if pid == 'P569' else 'founded')
                    except Exception:
                        continue
        return None, None

    def _extract_population_from_wikidata_claims(self, claims: dict):
        """Given claims, extract population integer and optional year qualifier. Returns (pop:int or None, year:int or None)."""
        if 'P1082' not in claims:
            return None, None
        pop = None
        year = None
        for cl in claims['P1082']:
            try:
                mainsnak = cl.get('mainsnak', {})
                dv = mainsnak.get('datavalue', {})
                val = dv.get('value') if isinstance(dv, dict) else None
                if isinstance(val, dict):
                    amt = val.get('amount') or val.get('numeric') or val.get('value')
                    if isinstance(amt, str) and re.search(r"\d", amt):
                        m = re.search(r"([\d,\.]+)", amt)
                        if m:
                            num = m.group(1).replace(',', '')
                            try:
                                pop = int(float(num))
                            except Exception:
                                pop = None
                elif isinstance(val, (int, float)):
                    pop = int(val)
            except Exception:
                pop = None
            # if pop found, try to get qualifier year
            if pop:
                try:
                    quals = cl.get('qualifiers', {})
                    if 'P585' in quals:
                        qv = quals['P585'][0].get('datavalue', {}).get('value', {})
                        if isinstance(qv, dict) and 'time' in qv:
                            m2 = re.search(r"([+-]?\d{4})", qv['time'])
                            if m2:
                                year = int(m2.group(1))
                except Exception:
                    year = None
                return pop, year
        return None, None

    def _assess_risk(self, commands: List[str]) -> int:
        # Simple heuristic-based risk scoring: higher score == more risky
        score = 0
        dangerous_patterns = [r"rm\s+-rf", r":>\s*/dev/sd", r"dd\s+if=", r"mkfs\.", r"chmod\s+777", r"chown\s+root", r"shutdown", r"reboot", r"curl\s+.*\|\s*bash"]
        for c in commands:
            lc = c.lower()
            if re.search(r"sudo\b", lc):
                score += 30
            for p in dangerous_patterns:
                if re.search(p, lc):
                    score += 50
            # presence of network download
            if re.search(r"curl\s+|wget\s+|scp\s+|ftp\s+", lc):
                score += 10
            # destructive verbs
            if re.search(r"rm\b|dd\b|mkfs\b|>:|truncate\b", lc):
                score += 20

        return min(score, 100)

    def _interactive_approval(self, commands: List[str], risk: int,
                              session_auto_low: bool = False, session_auto_all: bool = False,
                              require_strict_confirm: bool = False) -> bool:
        # honor session toggles first
        if session_auto_all:
            print('Session auto-approve all is ON — automatically approving commands')
            return True
        if session_auto_low:
            threshold = int(os.getenv('AUTO_APPROVE_LOW_RISK_THRESHOLD', '20'))
            if risk <= threshold:
                print(f'Session auto-approve low-risk ON and risk {risk} <= threshold {threshold} — approving')
                return True
        if require_strict_confirm:
            print("Compatibility check failed. To proceed despite detected OS mismatches type 'confirm' (case-insensitive), otherwise abort.")
            try:
                ans = input('> ').strip().lower()
            except Exception:
                # no stdin available (tests or piped), abort safely
                logging.debug('No stdin available for confirmation')
                print('No interactive stdin; not confirmed. Aborting.')
                return False
            if ans == 'confirm':
                return True
            print('Not confirmed. Aborting.')
            return False

        print("Approve commands? [y/N] (type 'p' to auto-approve low-risk, 'o' to auto-approve everything)")
        try:
            ans = input('> ').strip().lower()
        except Exception:
            logging.debug('No stdin available for approval prompt')
            return False
        if ans == 'y' or ans == 'yes':
            return True
        if ans == 'p':
            # auto-approve low-risk
            threshold = int(os.getenv('AUTO_APPROVE_LOW_RISK_THRESHOLD', '20'))
            if risk <= threshold:
                print(f'Auto-approved (risk {risk} <= threshold {threshold})')
                return True
            else:
                print(f'Not auto-approved (risk {risk} > threshold {threshold})')
                return False
        if ans == 'o':
            # explicit user request to auto-approve everything for this request
            print('Auto-approving all commands for this request')
            return True
        return False

    def _execute_commands(self, commands: List[str]):
        for c in commands:
            print(f'Running: {c}')
            logging.info('Executing: %s', c)
            # provide undo hint based on simple heuristics
            hint = None
            if re.search(r"\b(apt|brew)\s+install\b", c):
                m = re.search(r"install\s+(-y\s+)?([\w\-]+)", c)
                if m:
                    pkg = m.group(2)
                    hint = f"To undo: try 'sudo apt remove {pkg}' or 'brew uninstall {pkg}' depending on your OS"
            if self.dry_run:
                print('[dry-run] Would run:', c)
                if hint:
                    print('[hint]', hint)
                logging.info('Dry-run: %s', c)
                continue

            # If sandbox is enabled, run command inside a disposable docker container
            if self.sandbox_enabled:
                docker_path = shutil.which('docker')
                if not docker_path:
                    print('Sandbox requested but docker not found; aborting execution')
                    logging.error('Sandbox requested but docker not found')
                    return
                # construct docker run command; mount current working dir as /workspace
                docker_cmd = f"docker run --rm -v {os.getcwd()}:/workspace -w /workspace {self.sandbox_image} bash -lc \"{c}\""
                print('[sandbox] Running in container:', self.sandbox_image)
                logging.info('Sandbox execute: %s', docker_cmd)
                try:
                    res = subprocess.run(docker_cmd, shell=True)
                    logging.info('Sandbox exit %s', res.returncode)
                    if hint:
                        print('[hint]', hint)
                except KeyboardInterrupt:
                    print('\nExecution interrupted by user')
                    logging.info('Execution interrupted by user')
                    break
                except Exception as e:
                    logging.exception('Sandbox execution failed')
                    print('Error executing in sandbox:', e)
                    return
                continue

            try:
                # For interactive commands (sudo, password prompts), inherit the terminal so prompts work.
                if self.detected_os == 'windows':
                    res = subprocess.run(['cmd', '/c', c])
                else:
                    res = subprocess.run(['zsh', '-lc', c])
                logging.info('Exit %s', res.returncode)
                if hint:
                    print('[hint]', hint)
            except KeyboardInterrupt:
                print('\nExecution interrupted by user')
                logging.info('Execution interrupted by user')
                break
            except Exception as e:
                logging.exception('Command execution failed')
                print('Error executing command:', e)
