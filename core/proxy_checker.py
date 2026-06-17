from __future__ import annotations

import json
import random
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from core.browser_utils import proxy_check_strategy, get_sync_playwright, find_chrome_executable, save_cookies
from core.utils import now_str, time_str, stamp_for_filename


@dataclass
class ProxyTestResult:
    raw: str
    masked: str
    status: str  # ok / captcha_required / access_denied / timeout / vpn_blocked / ip_ban / antibot_blocked / no_product_links / product_page_blocked / missing_required_fields / invalid_proxy
    attempts: int = 1
    strategy: str = ''  # winning strategy from successful check


def _proxy_profile_name(proxy: dict) -> str:
    """Stable filesystem-safe profile name derived from the proxy's server address."""
    server = proxy.get('server', 'unknown')
    for proto in ('socks5://', 'https://', 'http://'):
        if server.startswith(proto):
            server = server[len(proto):]
            break
    safe = ''.join(c if c.isalnum() else '_' for c in server)
    return f'proxy_{safe}'


def profile_name_from_line(raw: str) -> str | None:
    """Return filesystem-safe profile name for a raw proxy line string.

    Returns None if the line cannot be parsed.
    """
    raw = (raw or '').strip()
    if not raw or raw.startswith('#'):
        return None
    try:
        if '://' in raw:
            parsed = urlparse(raw)
            if not parsed.hostname or not parsed.port:
                return None
            server = f'{parsed.scheme}://{parsed.hostname}:{parsed.port}'
        else:
            parts = raw.split(':')
            if len(parts) in (2, 4):
                server = f'http://{parts[0].strip()}:{parts[1].strip()}'
            else:
                return None
        return _proxy_profile_name({'server': server})
    except Exception:
        return None


def cleanup_stale_profiles(base_dir: Path, all_proxy_servers: list[str]) -> int:
    """Delete profile dirs for proxies no longer present in the proxy list.

    Keeps 'default' and any profile whose name matches a current proxy.
    Returns the number of removed directories.
    """
    profiles_dir = base_dir / 'profiles'
    if not profiles_dir.exists():
        return 0
    expected = {_proxy_profile_name({'server': s}) for s in all_proxy_servers if s.strip()}
    removed = 0
    for entry in profiles_dir.iterdir():
        if not entry.is_dir() or entry.name == 'default':
            continue
        if entry.name.startswith('proxy_') and entry.name not in expected:
            try:
                shutil.rmtree(entry)
                removed += 1
            except Exception:
                pass
    return removed


class ProxyCheckerBase:
    """Базовый класс проверки прокси. Не используется напрямую — используй OzonProxyChecker или WbProxyChecker."""

    def __init__(self, *, base_dir: Path, config: dict, log: Callable[[str, str], None],
                 stop_requested: Callable[[], bool] | None = None):
        self.base_dir = base_dir
        self.config = config
        self._original_log = log
        self._stop_requested = stop_requested or (lambda: False)
        self._log_file_path: Path | None = None
        self._init_log_file()

        self.valid_proxy_lines: list[str] = []
        self.invalid_proxy_lines: list[str] = []
        self.checked_proxy_file_path: str = ''

    # ---- абстрактные методы (реализуются в подклассах) ----

    def _make_parser(self):
        raise NotImplementedError

    def _make_stealth(self, config_dict: dict):
        raise NotImplementedError

    def _make_captcha_solver(self):
        raise NotImplementedError

    def _do_check(self, page, proxy: dict, label: str, result: ProxyTestResult,
                  antidetect_cfg: dict, context, captcha_solver) -> ProxyTestResult:
        raise NotImplementedError

    # ---- общая инфраструктура ----

    def _log(self, level: str, message: str) -> None:
        self._original_log(level, f'[{time_str()}] {message}')
        if self._log_file_path:
            try:
                with open(self._log_file_path, 'a', encoding='utf-8') as f:
                    f.write(f'[{now_str()}] [{level}] {message}\n')
            except Exception:
                pass

    @staticmethod
    def _status_label(status: str) -> str:
        _LABELS = {
            'connection_failed': 'Нет подключения к прокси',
            'timeout': 'Таймаут соединения',
            'ip_ban': 'IP заблокирован',
            'vpn_blocked': 'VPN заблокирован',
            'access_denied': 'Доступ запрещён',
            'captcha_required': 'Требуется решение капчи',
            'antibot_blocked': 'Заблокирован антиботом',
            'missing_required_fields': 'Не все поля распознаны',
            'no_product_links': 'Товары не найдены на главной',
        }
        return _LABELS.get(status, status)

    def _init_log_file(self) -> None:
        log_dir = self.base_dir / 'logs'
        log_dir.mkdir(parents=True, exist_ok=True)
        self._rotate_proxy_logs(log_dir)
        self._log_file_path = log_dir / 'proxy_check.log'
        self._log_file_path.write_text('', encoding='utf-8')

    def _rotate_proxy_logs(self, log_dir: Path) -> None:
        old2 = log_dir / 'proxy_check.2.log'
        old1 = log_dir / 'proxy_check.1.log'
        cur  = log_dir / 'proxy_check.log'
        if old2.exists():
            old2.unlink()
        if old1.exists():
            old1.rename(old2)
        if cur.exists():
            cur.rename(old1)

    def _mask_secret(self, value: str) -> str:
        value = (value or '').strip()
        if not value:
            return value
        if len(value) <= 2:
            return '*' * len(value)
        if len(value) <= 4:
            return value[0] + '*' * (len(value) - 1)
        return value[:2] + '*' * (len(value) - 4) + value[-2:]

    def _mask_proxy_line(self, raw: str) -> str:
        raw = (raw or '').strip()
        if not raw:
            return raw

        if '://' in raw and '@' in raw:
            try:
                parsed = urlparse(raw)
                scheme = parsed.scheme
                host = parsed.hostname or ''
                port = parsed.port or ''
                username = self._mask_secret(parsed.username or '')
                password = self._mask_secret(parsed.password or '')
                return f'{scheme}://{username}:{password}@{host}:{port}'
            except Exception:
                return raw

        parts = raw.split(':')
        if len(parts) == 4 and '://' not in raw:
            host, port, username, password = parts
            return f'{host}:{port}:{self._mask_secret(username)}:{self._mask_secret(password)}'

        return raw

    def _build_launch_kwargs_for_proxy(self, parser, proxy: dict | None, strategy: str = '') -> dict:
        launch_kwargs = {
            'headless': not bool(parser.parser_cfg.get('headed', True)),
            'args': [
                '--disable-blink-features=AutomationControlled',
                '--disable-features=IsolateOrigins,site-per-process,TranslateUI,BlockInsecurePrivateNetworkRequests',
                '--no-sandbox',
                '--disable-web-security',
                '--lang=ru-RU',
            ],
        }
        if strategy == 'chrome':
            chrome_path = find_chrome_executable()
            if chrome_path:
                launch_kwargs['executable_path'] = chrome_path
                self._log('INFO', f'Используется реальный Chrome: {chrome_path}')
            else:
                self._log('WARNING', 'Real Chrome не найден — используем Chromium')
        if proxy:
            launch_kwargs['proxy'] = proxy
        return launch_kwargs

    def _log_page_state(self, page, label: str, context_msg: str) -> None:
        try:
            url = page.url
            title = page.title()
            self._log('INFO', f'[{label}] {context_msg} | URL: {url} | Заголовок: {title}')
        except Exception:
            pass

    def _detect_vpn_blocked(self, page) -> bool:
        try:
            text = page.locator('body').inner_text(timeout=3000)
            return 'Выключите VPN' in text or 'Похоже, нет соединения' in text
        except Exception:
            return False

    def _try_refresh_vpn_page(self, page, label: str) -> bool:
        try:
            btn = page.locator('button:has-text("Обновить страницу"), a:has-text("Обновить страницу")')
            if btn.count() > 0:
                self._log('WARNING', f'[{label}] VPN-блок: нажимаем «Обновить страницу»...')
                btn.first.click()
            else:
                self._log('WARNING', f'[{label}] VPN-блок: кнопка не найдена, перезагружаем страницу...')
                page.reload(wait_until='domcontentloaded', timeout=30000)
            page.wait_for_timeout(3000)
            return not self._detect_vpn_blocked(page)
        except Exception as e:
            self._log('WARNING', f'[{label}] Ошибка при обновлении VPN-страницы: {e}')
            return False

    def _detect_antibot_challenge(self, page) -> bool:
        try:
            title = page.title()
            return 'Antibot Challenge' in title or 'antibot' in title.lower()
        except Exception:
            return False

    def _is_turnstile_present(self, page) -> bool:
        try:
            return page.locator('iframe[src*="turnstile"]').count() > 0
        except Exception:
            return False

    def _dismiss_cookie_consent(self, page, label: str = '') -> None:
        try:
            btn = page.locator('button:text-is("OK")')
            if btn.count() == 0:
                btn = page.locator('button:has-text("OK")').first
            else:
                btn = btn.first
            if btn.is_visible(timeout=1200):
                btn.click(timeout=2000)
                page.wait_for_timeout(400)
                if label:
                    self._log('INFO', f'[{label}] Закрыт попап куки')
        except Exception:
            pass

    def _resolve_antidetect_cfg(self, parser, label: str = '',
                                 exclude_strategies: list[str] | None = None) -> dict:
        antidetect_cfg = dict(parser.antidetect_cfg)
        exclude = ['camoufox'] + (exclude_strategies or [])
        antidetect_cfg['strategy'] = proxy_check_strategy(exclude=exclude)
        return antidetect_cfg

    def _run_single_attempt(self, parser, proxy: dict, label: str, masked_line: str,
                             antidetect_cfg: dict, captcha_solver, headed: bool) -> ProxyTestResult:
        result = ProxyTestResult(raw=masked_line, masked=masked_line, status='pending')
        stealth = self._make_stealth({'antidetect': antidetect_cfg})
        strategy_name = stealth.STRATEGY_NAMES.get(stealth.strategy, stealth.strategy)
        self._log('INFO', f'[{label}] Выбрана стратегия: {strategy_name}')

        _strategy = antidetect_cfg.get('strategy', 'stealth_js')
        launch_kwargs = self._build_launch_kwargs_for_proxy(parser, proxy, strategy=_strategy)
        _sync_pw = get_sync_playwright(_strategy)
        try:
            with _sync_pw() as p:
                browser = p.chromium.launch(**launch_kwargs)
                context = browser.new_context(
                    ignore_https_errors=True,
                    geolocation={'latitude': 55.7558, 'longitude': 37.6176},
                    permissions=['geolocation'],
                    locale='ru-RU',
                    timezone_id='Europe/Moscow',
                )
                page = None
                try:
                    page = context.new_page()
                    stealth.apply(page)
                    result = self._do_check(page, proxy, label, result, antidetect_cfg, context, captcha_solver)
                    return result
                finally:
                    if headed and page is not None and result.status != 'ok':
                        try:
                            self._log('INFO', f'[{label}] Финальный статус: {result.status} — браузер закроется через 8 сек')
                            page.wait_for_timeout(8000)
                        except Exception:
                            pass
                    context.close()
                    browser.close()
        except PlaywrightTimeoutError:
            result.status = 'timeout'
        except Exception as e:
            err_msg = str(e).strip()
            if 'ERR_PROXY_CONNECTION_FAILED' in err_msg:
                result.status = 'connection_failed'
                self._log('ERROR', f'[{label}] Нет подключения к прокси')
            elif 'ERR_TIMED_OUT' in err_msg or 'TIMED_OUT' in err_msg:
                result.status = 'timeout'
                self._log('ERROR', f'[{label}] Таймаут сети (прокси)')
            else:
                result.status = f'{type(e).__name__}' if not err_msg else f'{type(e).__name__}: {err_msg[:120]}'
                self._log('ERROR', f'[{label}] Необработанное исключение: {type(e).__name__}: {e}')
        return result

    def check_one_proxy(self, parser, proxy: dict, label: str, masked_line: str) -> ProxyTestResult:
        captcha_solver = self._make_captcha_solver()
        headed = bool(parser.parser_cfg.get('headed', True))
        used: list[str] = []

        antidetect_cfg = self._resolve_antidetect_cfg(parser, label=label, exclude_strategies=used)
        used.append(antidetect_cfg['strategy'])
        result = self._run_single_attempt(parser, proxy, label, masked_line, antidetect_cfg, captcha_solver, headed)

        if result.status == 'vpn_blocked':
            self._log('INFO', f'[{label}] VPN-блок — повторная попытка через 30 сек с другой стратегией...')
            time.sleep(30)
            retry_cfg = self._resolve_antidetect_cfg(parser, label=label, exclude_strategies=used)
            used.append(retry_cfg['strategy'])
            result = self._run_single_attempt(parser, proxy, label, masked_line, retry_cfg, captcha_solver, headed)
            result.attempts = 2

        if result.status == 'vpn_blocked':
            self._log('INFO', f'[{label}] VPN-блок — третья попытка через 60 сек...')
            time.sleep(60)
            third_cfg = self._resolve_antidetect_cfg(parser, label=label, exclude_strategies=used)
            result = self._run_single_attempt(parser, proxy, label, masked_line, third_cfg, captcha_solver, headed)
            result.attempts = 3

        if result.status == 'ip_ban':
            self._log('WARNING', f'[{label}] Прямой IP-бан подтверждён — пропускаем')

        return result

    def run(self) -> None:
        try:
            parser = self._make_parser()

            proxy_cfg = self.config.get('proxy', {})
            if not bool(proxy_cfg.get('enabled', False)):
                self._log('WARNING', 'Прокси отключен. Проверять нечего')
                return

            use_single_proxy = bool(proxy_cfg.get('use_single_proxy', True))
            single_proxy = str(proxy_cfg.get('single_proxy', '')).strip()
            proxy_file = str(proxy_cfg.get('proxy_file', '')).strip()

            self.valid_proxy_lines = []
            self.invalid_proxy_lines = []
            self.checked_proxy_file_path = ''

            if use_single_proxy:
                if not single_proxy:
                    self._log('ERROR', 'Прокси включен, но поле single_proxy пустое')
                    return

                masked_line = self._mask_proxy_line(single_proxy)

                try:
                    proxy = parser._parse_single_proxy_line(single_proxy)
                except Exception as exc:
                    self.invalid_proxy_lines.append(single_proxy)
                    self._log('ERROR', f'[single] Неверная строка proxy: {masked_line} | {type(exc).__name__}: {exc}')
                    return

                res = self.check_one_proxy(parser, proxy, 'single', masked_line)
                if res.status == 'ok':
                    self.valid_proxy_lines.append(single_proxy)
                    self._log('INFO', f'[single] Прокси валидна. Статус: {res.status}')
                else:
                    self.invalid_proxy_lines.append(single_proxy)
                    self._log('ERROR', f'[single] Прокси невалидна. Статус: {self._status_label(res.status)}')

                self._log(
                    'INFO',
                    f'Проверка proxy завершена. Рабочих: {len(self.valid_proxy_lines)}, нерабочих: {len(self.invalid_proxy_lines)}'
                )
                return

            if not proxy_file:
                self._log('ERROR', 'Прокси включен, но proxy_file не указан')
                return

            proxy_path = Path(proxy_file)
            if not proxy_path.is_absolute():
                proxy_path = self.base_dir / proxy_path

            if not proxy_path.exists():
                self._log('ERROR', f'Файл proxy не найден: {proxy_path}')
                return

            self.checked_proxy_file_path = str(proxy_path)

            raw_lines = [
                line.strip()
                for line in proxy_path.read_text(encoding='utf-8').splitlines()
                if line.strip()
            ]

            if not raw_lines:
                self._log('ERROR', f'Файл proxy пустой: {proxy_path}')
                return

            self._log('INFO', f'Файл proxy загружен. Строк: {len(raw_lines)}')

            for idx, raw_line in enumerate(raw_lines, start=1):
                label = f'{idx}/{len(raw_lines)}'
                masked_line = self._mask_proxy_line(raw_line)

                try:
                    proxy = parser._parse_single_proxy_line(raw_line)
                except Exception as exc:
                    self.invalid_proxy_lines.append(raw_line)
                    self._log('ERROR', f'[{label}] Неверная строка proxy: {masked_line} | {type(exc).__name__}: {exc}')
                    continue

                res = self.check_one_proxy(parser, proxy, label, masked_line)
                if res.status == 'ok':
                    self.valid_proxy_lines.append(raw_line)
                    self._log('INFO', f'[{label}] Прокси валидна. Статус: {res.status}')
                else:
                    self.invalid_proxy_lines.append(raw_line)
                    self._log('ERROR', f'[{label}] Прокси невалидна. Статус: {self._status_label(res.status)}')

                if self._stop_requested():
                    self._log('WARNING', 'Проверка прокси остановлена пользователем')
                    break

                if idx < len(raw_lines):
                    delay = random.uniform(3.0, 7.0)
                    self._log('INFO', f'[{label}] Пауза {delay:.1f} сек перед следующей прокси...')
                    time.sleep(delay)

            self._log(
                'INFO',
                f'Проверка proxy завершена. Рабочих: {len(self.valid_proxy_lines)}, нерабочих: {len(self.invalid_proxy_lines)}'
            )

        except Exception as exc:
            self._log('ERROR', f'Ошибка проверки proxy: {type(exc).__name__}: {exc}')
