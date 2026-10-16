"""Optional, dependency-free .env support for sensitive GUI configuration.

The application continues to work without .env. Local JSON configs are still
used by the GUI and are ignored by Git. Environment variables override .env.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

_ENV_FIELDS = {
    '2CAPTCHA_API_KEY': ('captcha', 'twocaptcha_api_key'),
    'CAPSOLVER_API_KEY': ('captcha', 'capsolver_api_key'),
    'ANTICAPTCHA_API_KEY': ('captcha', 'anticaptcha_api_key'),
    'TELEGRAM_BOT_TOKEN': ('notifications', 'bot_token'),
    'TELEGRAM_CHAT_ID': ('notifications', 'chat_id'),
    'TELEGRAM_THREAD_ID': ('notifications', 'thread_id'),
    'TELEGRAM_PROXY': ('notifications', 'tg_proxy'),
    'SINGLE_PROXY': ('proxy', 'single_proxy'),
}
_VALID_KEY = re.compile(r'^[A-Z][A-Z0-9_]*$')


def read_dotenv(path: Path) -> dict[str, str]:
    """Read simple KEY=VALUE pairs; no execution, expansion or interpolation."""
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw in path.read_text(encoding='utf-8-sig').splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('export '):
            line = line[7:].lstrip()
        key, separator, value = line.partition('=')
        key = key.strip()
        if not separator or not _VALID_KEY.fullmatch(key):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] in ('"', "'") and value[-1] == value[0]:
            value = value[1:-1]
        else:
            value = value.split(' #', 1)[0].strip()
        values[key] = value
    return values


def apply_env_overrides(
    config: dict, parser: str, env_path: Path, environ: dict[str, str] | None = None
) -> dict:
    """Apply non-empty WB/OZON-specific values without exposing them in logs."""
    parser = parser.upper()
    if parser not in ('WB', 'OZON'):
        raise ValueError('Unsupported parser name')
    values = read_dotenv(env_path)
    values.update(os.environ if environ is None else environ)
    for suffix, (section, field) in _ENV_FIELDS.items():
        value = values.get(f'MULTIPARSER_{parser}_{suffix}', '')
        if value:
            config.setdefault(section, {})[field] = value
    return config
