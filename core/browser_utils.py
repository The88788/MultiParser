from __future__ import annotations

import json
import os
import random
from pathlib import Path

# UA entries paired with their exact Sec-Ch-Ua / Sec-Ch-Ua-Full-Version-List values
# so both headers are always consistent with the User-Agent string.
_UA_PROFILES = [
    {
        'ua': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36',
        'sec_ch_ua': '"Chromium";v="136", "Google Chrome";v="136", "Not-A.Brand";v="99"',
        'sec_ch_ua_full': '"Chromium";v="136.0.7103.93", "Google Chrome";v="136.0.7103.93", "Not-A.Brand";v="99.0.0.0"',
        'version': '136',
    },
    {
        'ua': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36',
        'sec_ch_ua': '"Chromium";v="135", "Google Chrome";v="135", "Not-A.Brand";v="99"',
        'sec_ch_ua_full': '"Chromium";v="135.0.7049.115", "Google Chrome";v="135.0.7049.115", "Not-A.Brand";v="99.0.0.0"',
        'version': '135',
    },
    {
        'ua': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36',
        'sec_ch_ua': '"Chromium";v="134", "Google Chrome";v="134", "Not-A.Brand";v="24"',
        'sec_ch_ua_full': '"Chromium";v="134.0.6998.165", "Google Chrome";v="134.0.6998.165", "Not-A.Brand";v="24.0.0.0"',
        'version': '134',
    },
    {
        'ua': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36',
        'sec_ch_ua': '"Chromium";v="133", "Google Chrome";v="133", "Not-A.Brand";v="24"',
        'sec_ch_ua_full': '"Chromium";v="133.0.6943.141", "Google Chrome";v="133.0.6943.141", "Not-A.Brand";v="24.0.0.0"',
        'version': '133',
    },
]

# Moscow-area coordinates with slight jitter so they're not always identical
_MOSCOW_LOCATIONS = [
    (55.7558, 37.6176),   # Kremlin area
    (55.7522, 37.6156),   # Manezhnaya
    (55.7601, 37.6218),   # Red Square
    (55.7539, 37.6208),   # Zaryadye
    (55.7489, 37.6093),   # Borovitskaya
]


def random_ua_profile() -> dict:
    """Returns a consistent {ua, sec_ch_ua, sec_ch_ua_full, version} bundle."""
    return random.choice(_UA_PROFILES)


def random_user_agent() -> str:
    return random_ua_profile()['ua']


def random_viewport() -> dict:
    variants = [
        {'width': 1366, 'height': 768},
        {'width': 1440, 'height': 900},
        {'width': 1536, 'height': 864},
        {'width': 1600, 'height': 900},
        {'width': 1920, 'height': 1080},
    ]
    return random.choice(variants)


def random_geolocation() -> dict:
    lat, lon = random.choice(_MOSCOW_LOCATIONS)
    lat += random.uniform(-0.002, 0.002)
    lon += random.uniform(-0.002, 0.002)
    return {'latitude': round(lat, 6), 'longitude': round(lon, 6)}


def find_chrome_executable() -> str | None:
    """Finds installed Chrome or Edge on Windows. Returns None if not found."""
    candidates = [
        r'C:\Program Files\Google\Chrome\Application\chrome.exe',
        r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
        os.path.expandvars(r'%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe'),
        r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
        r'C:\Program Files\Microsoft\Edge\Application\msedge.exe',
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def random_antidetect_strategy(exclude: list[str] | None = None) -> str:
    pool = ['stealth_js', 'xdriver', 'camoufox', 'browserforge', 'patchright', 'chrome']
    if exclude:
        pool = [s for s in pool if s not in exclude]
    return random.choice(pool)


# Порядок стратегий для проверки прокси: от наиболее эффективной к наименее.
# patchright обходит Antibot Challenge лучше всех, поэтому идёт первым.
_PROXY_CHECK_STRATEGY_ORDER = ['patchright', 'chrome', 'xdriver', 'browserforge', 'stealth_js']


def proxy_check_strategy(exclude: list[str] | None = None) -> str:
    """Возвращает следующую лучшую стратегию для проверки прокси (в порядке приоритета)."""
    for s in _PROXY_CHECK_STRATEGY_ORDER:
        if not exclude or s not in exclude:
            return s
    return random_antidetect_strategy(exclude=exclude)


def get_sync_playwright(strategy: str):
    """Returns sync_playwright from patchright if strategy=='patchright', else from playwright.
    Falls back to playwright if patchright is not installed."""
    if strategy == 'patchright':
        try:
            from patchright.sync_api import sync_playwright as _patchright_sync
            return _patchright_sync
        except ImportError:
            pass
    from playwright.sync_api import sync_playwright
    return sync_playwright


def _cookies_path(base_dir: Path, profile_name: str | None = None) -> Path:
    if profile_name:
        profile_dir = base_dir / 'profiles' / profile_name
        profile_dir.mkdir(parents=True, exist_ok=True)
        return profile_dir / 'cookies.json'
    return base_dir / 'cookies.json'


def load_cookies(context, base_dir: Path, profile_name: str | None = None, log=None) -> None:
    path = _cookies_path(base_dir, profile_name)
    if not path.exists():
        return
    try:
        cookies = json.loads(path.read_text(encoding='utf-8'))
        if isinstance(cookies, list) and cookies:
            context.add_cookies(cookies)
    except Exception as exc:
        if log:
            log('WARNING', f'load_cookies ({path.name}): {exc}')


def save_cookies(context, base_dir: Path, profile_name: str | None = None, log=None) -> None:
    path = _cookies_path(base_dir, profile_name)
    try:
        cookies = context.cookies()
        path.write_text(json.dumps(cookies, ensure_ascii=False, indent=2), encoding='utf-8')
    except Exception as exc:
        if log:
            log('WARNING', f'save_cookies ({path.name}): {exc}')
