from __future__ import annotations

import json
import random
import shutil
from pathlib import Path
from typing import Callable, Optional

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from core.browser_utils import save_cookies
from core.proxy_checker import ProxyCheckerBase, ProxyTestResult, _proxy_profile_name
from core.utils import stamp_for_filename
from parsers.ozon.extractors import detect_access_denied, parse_prices_from_text
from parsers.ozon.parser_core import CaptchaSolverManager, ParserCore, StealthManager


class OzonProxyChecker(ProxyCheckerBase):
    """Проверяет прокси на сайте Ozon."""

    def _make_parser(self) -> ParserCore:
        return ParserCore(
            base_dir=self.base_dir,
            config=self.config,
            stop_requested=lambda: False,
            log=self._log,
            stats_callback=None,
        )

    def _make_stealth(self, config_dict: dict) -> StealthManager:
        return StealthManager(config_dict, self._log)

    def _make_captcha_solver(self) -> CaptchaSolverManager:
        return CaptchaSolverManager(self.config, self._log)

    def _do_check(self, page, proxy: dict, label: str, result: ProxyTestResult,
                  antidetect_cfg: dict, context, captcha_solver) -> ProxyTestResult:
        return self._check_ozon(page, proxy, label, result, antidetect_cfg, context, captcha_solver)

    # ---- OZON-специфичные методы ----

    def _check_ozon(self, page, proxy, label, result, antidetect_cfg, context, captcha_solver) -> ProxyTestResult:
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
                result.status = 'ip_ban' if not antibot_was_seen else 'vpn_blocked'
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
            elif card_result['status'] in ('region_unavailable', 'product_page_blocked'):
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
                    json.dumps({'strategy': result.strategy}), encoding='utf-8')
            except Exception:
                pass
        else:
            result.status = 'missing_required_fields'
        return result

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

    def _dump_captcha_page(self, page, label: str) -> None:
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

            try:
                page.wait_for_function(
                    "() => { const img = document.querySelector('img.image'); "
                    "return !!(img && img.naturalWidth > 0); }",
                    timeout=10000,
                )
            except Exception:
                pass
            page.wait_for_timeout(800)

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
                btn_center_x = img_box['x'] + 24
                y = img_box['y'] + img_box['height'] + 24
                self._log('WARNING', f'[{label}] Слайдер не найден, расчётная позиция: ({btn_center_x:.0f}, {y:.0f})')

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
