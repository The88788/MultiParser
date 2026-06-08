from __future__ import annotations

import json
import random
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from core.browser_utils import proxy_check_strategy, get_sync_playwright, find_chrome_executable, save_cookies
from parsers.ozon.extractors import detect_access_denied, parse_prices_from_text
from parsers.ozon.parser_core import CaptchaSolverManager, ParserCore, StealthManager
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


class ProxyChecker:
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
        # Держим ровно 3 файла: proxy_check.log, .1.log, .2.log
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

    def _build_launch_kwargs_for_proxy(self, parser: ParserCore, proxy: dict | None, strategy: str = '') -> dict:
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

    def _check_product_page(self, page, url: str, label: str = '', captcha_solver=None) -> dict:
        try:
            page.goto(url, wait_until='domcontentloaded', timeout=35000)
            page.wait_for_timeout(1500)
            actual_url = page.url
            if label:
                self._log('INFO', f'[{label}] Карточка товара — URL после загрузки: {actual_url}')
            self._dismiss_cookie_consent(page, label)
            if self._detect_vpn_blocked(page):
                return {'status': 'vpn_blocked', 'shop': None, 'price_with_ozon_cart': None,
                        'price_without_ozon_cart': None}
            if self._detect_ozon_slider_captcha(page):
                if label:
                    self._log('WARNING', f'[{label}] Обнаружена slider-капча Ozon на карточке товара')
                if captcha_solver and captcha_solver.has_any_key():
                    solved = self._solve_ozon_slider_captcha(page, label, captcha_solver)
                    if not solved:
                        return {'status': 'slider_captcha', 'shop': None, 'price_with_ozon_cart': None,
                                'price_without_ozon_cart': None}
                    actual_url = page.url
                else:
                    return {'status': 'slider_captcha', 'shop': None, 'price_with_ozon_cart': None,
                            'price_without_ozon_cart': None}
            if '/search/' in actual_url:
                if label:
                    self._log('WARNING', f'[{label}] Редирект на поиск: {actual_url}')
                return {'status': 'product_page_blocked', 'shop': None, 'price_with_ozon_cart': None,
                        'price_without_ozon_cart': None}
            if '/product/' not in actual_url:
                if label:
                    self._log('WARNING', f'[{label}] Редирект не на карточку товара: {actual_url}')
                return {'status': 'product_page_blocked', 'shop': None, 'price_with_ozon_cart': None,
                        'price_without_ozon_cart': None}
            page_text = page.locator('body').inner_text(timeout=5000)
            if self._detect_region_unavailable(page_text):
                return {'status': 'region_unavailable', 'shop': None, 'price_with_ozon_cart': None,
                        'price_without_ozon_cart': None}
            if detect_access_denied(page_text)[0]:
                return {'status': 'access_denied', 'shop': None, 'price_with_ozon_cart': None,
                        'price_without_ozon_cart': None}
            shop = self._extract_shop_from_page(page)
            prices = self._extract_prices_from_page(page)
            if not shop and not (prices.get('with') or prices.get('without')):
                return {'status': 'missing_required_fields', 'shop': shop, 'price_with_ozon_cart': None,
                        'price_without_ozon_cart': None}
            if not prices.get('with') and not prices.get('without'):
                return {'status': 'missing_required_fields', 'shop': shop, 'price_with_ozon_cart': None,
                        'price_without_ozon_cart': None}
            return {
                'status': 'ok',
                'shop': shop,
                'price_with_ozon_cart': prices.get('with'),
                'price_without_ozon_cart': prices.get('without'),
            }
        except PlaywrightTimeoutError:
            return {'status': 'timeout', 'shop': None, 'price_with_ozon_cart': None, 'price_without_ozon_cart': None}
        except Exception as e:
            return {'status': f'error: {type(e).__name__}', 'shop': None, 'price_with_ozon_cart': None,
                    'price_without_ozon_cart': None}

    def _extract_shop_from_page(self, page) -> Optional[str]:
        try:
            shop = page.evaluate("""
                () => {
                    const x = document.evaluate("//span[contains(text(),'Магазин')]", document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null);
                    if (!x.singleNodeValue) return null;
                    let el = x.singleNodeValue.closest('div');
                    while (el) {
                        const spans = el.querySelectorAll('span');
                        for (let s of spans) {
                            const t = s.textContent.trim();
                            if (t && t.length > 1 && t !== 'Магазин' && !t.startsWith('О магазине') && !t.startsWith('Перейти'))
                                return t;
                        }
                        el = el.parentElement;
                    }
                    return null;
                }
            """)
            return shop.strip() if shop else None
        except Exception:
            return None

    def _extract_prices_from_page(self, page) -> dict:
        try:
            price_text = page.locator('[data-widget="webPrice"]').first.inner_text(timeout=3000)
            with_bank, without_bank, _ = parse_prices_from_text(price_text)
            return {'with': with_bank, 'without': without_bank}
        except Exception:
            return {'with': None, 'without': None}

    def _detect_region_unavailable(self, text: str) -> bool:
        return 'Товар не доставляется в ваш регион' in text

    def _is_turnstile_present(self, page) -> bool:
        try:
            return page.locator('iframe[src*="turnstile"]').count() > 0
        except Exception:
            return False

    def _dump_captcha_page(self, page, label: str) -> None:
        """Сохраняет скриншот и HTML страницы капчи для диагностики."""
        log_dir = self.base_dir / 'logs'
        log_dir.mkdir(parents=True, exist_ok=True)
        ts = stamp_for_filename()

        try:
            if self._log_file_path and self._log_file_path.exists():
                snap_path = log_dir / f'captcha_log_{ts}.log'
                shutil.copy2(str(self._log_file_path), str(snap_path))
                self._log('DEBUG', f'[{label}] Снимок лога: {snap_path}')
        except Exception as e:
            self._log('DEBUG', f'[{label}] Снимок лога — ошибка: {e}')

        try:
            dom_info = page.evaluate("""() => {
                const sels = ['img.image','img.puzzle','#slider','#slider-container',
                              '#slider-background','[id*="slider"]','button',
                              '[class*="slider"]','[class*="captcha"]',
                              'input[type="range"]','canvas','img'];
                const out = {};
                for (const sel of sels) {
                    out[sel] = [...document.querySelectorAll(sel)].map(el => {
                        const r = el.getBoundingClientRect();
                        const cls = [...el.classList].join('.').substring(0, 60);
                        return `${el.tagName}#${el.id}.${cls}|${Math.round(r.width)}x${Math.round(r.height)}`;
                    });
                }
                return JSON.stringify(out, null, 2);
            }""")
            self._log('DEBUG', f'[{label}] DOM элементы: {dom_info}')
        except Exception as e:
            self._log('DEBUG', f'[{label}] DOM dump — ошибка: {e}')

        try:
            shot_path = log_dir / f'captcha_screenshot_{ts}.png'
            page.screenshot(path=str(shot_path), full_page=True)
            self._log('DEBUG', f'[{label}] Скриншот: {shot_path}')
        except Exception as e:
            self._log('DEBUG', f'[{label}] Скриншот — ошибка: {e}')

        try:
            html = page.evaluate("""() => {
                const clone = document.body.cloneNode(true);
                clone.querySelectorAll('input[type="hidden"]').forEach(
                    el => el.setAttribute('value', '[STRIPPED]'));
                return clone.innerHTML;
            }""")
            html_path = log_dir / f'captcha_debug_{ts}.html'
            html_path.write_text(html, encoding='utf-8')
            self._log('DEBUG', f'[{label}] HTML: {html_path}')
        except Exception as e:
            self._log('DEBUG', f'[{label}] HTML dump — ошибка: {e}')

    def _solve_ozon_slider_captcha(self, page, label: str, captcha_solver: CaptchaSolverManager) -> bool:
        try:
            self._log('INFO', f'[{label}] Ожидаем загрузки изображения пазла...')

            # Ждём пока img.image загрузится (naturalWidth > 0), макс. 10 сек
            try:
                page.wait_for_function(
                    "() => { const img = document.querySelector('img.image'); "
                    "return !!(img && img.naturalWidth > 0); }",
                    timeout=10000,
                )
            except Exception:
                pass
            page.wait_for_timeout(800)

            # Находим основное изображение пазла
            img_loc = page.locator('img.image').first
            if not img_loc.is_visible(timeout=3000):
                self._dump_captcha_page(page, label)
                self._log('WARNING', f'[{label}] img.image не найден — страница не загрузила пазл')
                return False

            img_box = img_loc.bounding_box()
            if not img_box or img_box['width'] < 50 or img_box['height'] < 50:
                self._log('WARNING', f'[{label}] img.image слишком мало: {img_box}')
                return False

            self._log('INFO', f'[{label}] Пазл найден: {img_box["width"]:.0f}×{img_box["height"]:.0f}px '
                               f'(x={img_box["x"]:.0f}, y={img_box["y"]:.0f})')

            # Скриншот фонового изображения — отправляем в антикапча
            img_bytes = page.screenshot(clip={
                'x': img_box['x'], 'y': img_box['y'],
                'width': img_box['width'], 'height': img_box['height'],
            })

            coords = captcha_solver.solve_image_coordinates(img_bytes)
            if not coords:
                self._log('WARNING', f'[{label}] Сервис антикапчи не вернул координаты')
                return False

            target_x, _ = coords
            self._log('INFO', f'[{label}] Целевая позиция пазла: x={target_x} (из {img_box["width"]:.0f}px)')

            # Ищем кнопку-ползунок: сначала CSS-селекторы, затем JS-поиск по позиции
            btn_center_x: Optional[float] = None
            y: Optional[float] = None

            for sel in ('#slider', 'button', '[role="button"]', '[class*="slider"]', '[class*="arrow"]',
                        '[class*="handle"]', '[class*="control"]', '[draggable="true"]', '[tabindex]'):
                try:
                    loc = page.locator(sel).first
                    if loc.is_visible(timeout=500):
                        box = loc.bounding_box()
                        if box and 10 < box['width'] < 300 and 10 < box['height'] < 300:
                            btn_center_x = box['x'] + box['width'] / 2
                            y = box['y'] + box['height'] / 2
                            self._log('DEBUG', f'[{label}] Слайдер найден по {sel}: {box["width"]:.0f}×{box["height"]:.0f}px')
                            break
                except Exception:
                    continue

            if btn_center_x is None:
                # JS-поиск: все видимые элементы в диапазоне 100px ниже img.image
                try:
                    candidates = page.evaluate("""() => {
                        const img = document.querySelector('img.image');
                        if (!img) return [];
                        const ir = img.getBoundingClientRect();
                        const res = [];
                        document.querySelectorAll('*').forEach(el => {
                            const r = el.getBoundingClientRect();
                            if (r.top >= ir.bottom && r.top <= ir.bottom + 100 &&
                                r.width >= 15 && r.height >= 15 &&
                                r.left >= ir.left - 50 && r.right <= ir.right + 50) {
                                res.push({tag: el.tagName,
                                    cls: [...el.classList].join('.').substring(0, 80),
                                    cx: Math.round(r.x + r.width / 2),
                                    cy: Math.round(r.y + r.height / 2),
                                    w: Math.round(r.width), h: Math.round(r.height)});
                            }
                        });
                        return res;
                    }""")
                    self._log('DEBUG', f'[{label}] JS-элементы ниже img.image: {candidates}')
                    if candidates:
                        # DIV < 200px → скорее всего ручка слайдера; SVG — декоративный элемент
                        divs = [c for c in candidates if c['tag'] == 'DIV' and c['w'] < 200]
                        pool = divs or [c for c in candidates if c['tag'] != 'SVG' and c['w'] < 200]
                        pool = pool or candidates
                        small = min(pool, key=lambda c: c['w'] * c['h'])
                        btn_center_x = small['cx']
                        y = small['cy']
                        self._log('DEBUG', f'[{label}] JS-слайдер: {small}')
                except Exception as e:
                    self._log('DEBUG', f'[{label}] JS-поиск слайдера — ошибка: {e}')

            if btn_center_x is None:
                # Позиционный фоллбэк: кнопка у левого края img.image, ~24px ниже
                btn_center_x = img_box['x'] + 24
                y = img_box['y'] + img_box['height'] + 24
                self._log('WARNING', f'[{label}] Слайдер не найден, расчётная позиция: ({btn_center_x:.0f}, {y:.0f})')

            # Смещаем ползунок на target_x пикселей вправо от его начальной позиции
            target_x_screen = btn_center_x + target_x
            self._log('DEBUG', f'[{label}] Перетаскиваем: ({btn_center_x:.0f},{y:.0f}) → x={target_x_screen:.0f} (delta={target_x}px)')

            page.mouse.move(btn_center_x, y)
            page.mouse.down()
            steps = 30
            for i in range(1, steps + 1):
                cur_x = btn_center_x + (target_x_screen - btn_center_x) * i / steps
                page.mouse.move(cur_x, y + random.uniform(-1.5, 1.5))
                page.wait_for_timeout(random.randint(15, 45))
            page.mouse.up()
            page.wait_for_timeout(3500)

            try:
                post_url = page.url
                post_title = page.title()
                self._log('DEBUG', f'[{label}] После перетаскивания | URL: {post_url} | Заголовок: {post_title}')
            except Exception:
                pass
            self._dump_captcha_page(page, label)

            if not self._detect_ozon_slider_captcha(page):
                self._log('INFO', f'[{label}] Slider-капча успешно решена!')
                return True

            self._log('WARNING', f'[{label}] Slider-капча не решена (позиция неверна)')
            return False

        except Exception as e:
            self._log('WARNING', f'[{label}] Ошибка при решении slider-капчи: {e}')
            return False

    def _detect_ozon_slider_captcha(self, page) -> bool:
        try:
            title = page.title()
            if 'Antibot' in title or 'antibot' in title:
                return True
        except Exception:
            pass
        try:
            text = page.locator('body').inner_text(timeout=2000)
            if 'Сопоставьте пазл' in text:
                return True
            if 'Подтвердите, что вы не бот' in text:
                try:
                    if page.locator('input[type="range"]').count() > 0:
                        return True
                except Exception:
                    pass
                try:
                    if 'fab_cp' in page.content():
                        return True
                except Exception:
                    pass
        except Exception:
            pass
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

    def _detect_antibot_challenge(self, page) -> bool:
        try:
            title = page.title()
            return 'Antibot Challenge' in title or 'antibot' in title.lower()
        except Exception:
            return False

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

    def _get_random_product_urls_from_main(self, page) -> list[str]:
        try:
            urls = page.evaluate("""
                () => {
                    const links = Array.from(document.querySelectorAll('a[href*="/product/"]'));
                    return [...new Set(links.map(a => a.href))];
                }
            """)
            random.shuffle(urls)
            return urls[:3]
        except Exception:
            return []

    def _log_page_state(self, page, label: str, context_msg: str) -> None:
        try:
            url = page.url
            title = page.title()
            self._log('INFO', f'[{label}] {context_msg} | URL: {url} | Заголовок: {title}')
        except Exception:
            pass

    def _get_product_urls_with_retry(self, page, label: str, attempts: int = 3, wait_ms: int = 2000) -> list:
        for attempt in range(1, attempts + 1):
            urls = self._get_random_product_urls_from_main(page)
            if urls:
                return urls
            if attempt < attempts:
                self._log('INFO', f'[{label}] Ссылки на товары не найдены (попытка {attempt}/{attempts}), ждём дозагрузки...')
                page.wait_for_timeout(wait_ms)
                try:
                    page.mouse.wheel(0, 400)
                    page.wait_for_timeout(500)
                except Exception:
                    pass
        return []

    def _resolve_antidetect_cfg(
        self,
        parser: ParserCore,
        label: str = '',
        exclude_strategies: list[str] | None = None,
    ) -> dict:
        antidetect_cfg = dict(parser.antidetect_cfg)
        exclude = ['camoufox'] + (exclude_strategies or [])
        antidetect_cfg['strategy'] = proxy_check_strategy(exclude=exclude)
        return antidetect_cfg

    def _run_single_attempt(
        self,
        parser: ParserCore,
        proxy: dict,
        label: str,
        masked_line: str,
        antidetect_cfg: dict,
        captcha_solver: CaptchaSolverManager,
        headed: bool,
    ) -> ProxyTestResult:
        result = ProxyTestResult(raw=masked_line, masked=masked_line, status='pending')
        stealth = StealthManager({'antidetect': antidetect_cfg}, self._log)
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
                    page.goto('https://www.ozon.ru', wait_until='domcontentloaded', timeout=30000)
                    page.wait_for_timeout(2000)
                    self._dismiss_cookie_consent(page, label)
                    self._log_page_state(page, label, 'Главная страница загружена')

                    antibot_was_seen = self._detect_antibot_challenge(page)
                    if antibot_was_seen:
                        self._log('WARNING', f'[{label}] Antibot Challenge — ждём JS-проверки (до 15 сек)...')
                        for _ in range(15):
                            page.wait_for_timeout(1000)
                            if not self._detect_antibot_challenge(page):
                                break
                        self._dismiss_cookie_consent(page, label)
                        self._log_page_state(page, label, 'После Antibot Challenge')

                    if self._detect_vpn_blocked(page):
                        self._log_page_state(page, label, 'VPN-блок обнаружен')
                        cleared = self._try_refresh_vpn_page(page, label)
                        if not cleared:
                            self._log('WARNING', f'[{label}] VPN-блок остался после обновления')
                            self._log_page_state(page, label, 'После обновления VPN-блок не снят')
                            if not antibot_was_seen:
                                self._log('WARNING', f'[{label}] Прямой IP-бан — Antibot Challenge не было, ретраи бесполезны')
                                result.status = 'ip_ban'
                            else:
                                result.status = 'vpn_blocked'
                            return result
                        page.wait_for_timeout(3000)
                        self._dismiss_cookie_consent(page, label)
                        self._log_page_state(page, label, 'VPN-блок снят, ждём дозагрузки главной')

                    if self._is_turnstile_present(page):
                        self._log('WARNING', f'[{label}] Обнаружена капча при проверке прокси, пытаемся решить...')
                        token = captcha_solver.solve_turnstile(page, 'https://www.ozon.ru')
                        if token:
                            self._log('INFO', f'[{label}] Капча решена, перезагружаем страницу...')
                            page.wait_for_timeout(2000)
                            page.goto('https://www.ozon.ru', wait_until='domcontentloaded', timeout=30000)
                            page.wait_for_timeout(2000)
                            self._log_page_state(page, label, 'После решения капчи')
                        else:
                            self._log('WARNING', f'[{label}] Не удалось решить капчу автоматически')

                    body_text = page.locator('body').inner_text(timeout=5000)
                    if detect_access_denied(body_text)[0]:
                        self._log_page_state(page, label, 'Access denied на главной')
                        result.status = 'access_denied'
                        return result

                    product_urls = self._get_product_urls_with_retry(page, label, attempts=3, wait_ms=2000)
                    if not product_urls:
                        if self._detect_vpn_blocked(page):
                            self._log_page_state(page, label, 'VPN-блок обнаружен повторно (JS-рендер)')
                            cleared = self._try_refresh_vpn_page(page, label)
                            result.status = 'no_product_links' if cleared else 'vpn_blocked'
                        elif self._detect_antibot_challenge(page):
                            self._log_page_state(page, label, 'Antibot Challenge после ожидания — прокси заблокирована')
                            result.status = 'antibot_blocked'
                        else:
                            self._log_page_state(page, label, 'Товары не найдены на главной странице')
                            result.status = 'no_product_links'
                        return result

                    self._log('INFO', f'[{label}] Найдено ссылок на товары: {len(product_urls)}, проверяем...')
                    ok_count = 0
                    for prod_url in product_urls[:2]:
                        self._log('INFO', f'[{label}] Проверяем товар: {prod_url}')
                        card_result = self._check_product_page(page, prod_url, label, captcha_solver)
                        self._log('INFO', f'[{label}] Результат карточки: {card_result["status"]}')
                        if card_result['status'] == 'ok':
                            ok_count += 1
                        elif card_result['status'] in ('access_denied', 'timeout', 'vpn_blocked'):
                            result.status = card_result['status']
                            return result
                        elif card_result['status'] == 'region_unavailable':
                            self._log('WARNING', f'[{label}] Товар не доставляется в регион прокси — прокси рабочая')
                            ok_count += 1
                        elif card_result['status'] == 'product_page_blocked':
                            self._log('WARNING', f'[{label}] Карточка товара заблокирована, но главная открылась')
                            ok_count += 1
                        elif card_result['status'] == 'slider_captcha':
                            self._log('WARNING', f'[{label}] Slider-капча на карточке — прокси невалидна для парсинга')
                            result.status = 'captcha_required'
                            return result
                    if ok_count >= 1:
                        result.status = 'ok'
                        result.strategy = antidetect_cfg.get('strategy', '')
                        profile = _proxy_profile_name(proxy)
                        save_cookies(context, self.base_dir, profile, log=self._log)
                        profile_dir = self.base_dir / 'profiles' / profile
                        profile_dir.mkdir(parents=True, exist_ok=True)
                        try:
                            (profile_dir / 'strategy.json').write_text(
                                json.dumps({'strategy': result.strategy}),
                                encoding='utf-8',
                            )
                        except Exception:
                            pass
                    else:
                        result.status = 'missing_required_fields'
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
            else:
                result.status = f'{type(e).__name__}' if not err_msg else f'{type(e).__name__}: {err_msg[:120]}'
                self._log('ERROR', f'[{label}] Необработанное исключение: {type(e).__name__}: {e}')
        return result

    def check_one_proxy(self, parser: ParserCore, proxy: dict, label: str, masked_line: str) -> ProxyTestResult:
        captcha_solver = CaptchaSolverManager(self.config, self._log)
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
            parser = ParserCore(
                base_dir=self.base_dir,
                config=self.config,
                stop_requested=lambda: False,
                log=self._log,
                stats_callback=None,
            )

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
