from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Callable

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from core.browser_utils import save_cookies
from core.proxy_checker import ProxyCheckerBase, ProxyTestResult, _proxy_profile_name
from parsers.wb.extractors import detect_access_denied_wb
from parsers.wb.parser_core import CaptchaSolverManager, ParserCore, StealthManager


class WbProxyChecker(ProxyCheckerBase):
    """Проверяет прокси на сайте Wildberries."""

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
        return self._check_wb(page, proxy, label, result, antidetect_cfg, context)

    # ---- WB-специфичные методы ----

    def _dismiss_wb_popups(self, page, label: str = '') -> None:
        """Закрывает WB-специфичные попапы: город, рекламные оверлеи, уведомления."""
        try:
            if page.locator('[class*="popupContent"]').is_visible(timeout=800):
                page.keyboard.press('Escape')
                page.wait_for_timeout(400)
                if label:
                    self._log('INFO', f'[{label}] Закрыт попап WB (Escape)')
                return
        except Exception:
            pass

        candidates = [
            ('xpath=//div[contains(@class,"popupContent")]/..//button', 'попап X'),
            ('xpath=//div[contains(@class,"popupContent")]/preceding-sibling::button', 'попап X'),
            ('button:has-text("Да, верно")', 'город'),
            ('[class*="city-confirm"] button:first-child', 'город'),
            ('.city-confirm__btn_yes', 'город'),
            ('button:has-text("×")', 'оверлей ×'),
            ('button:has-text("✕")', 'оверлей ✕'),
            ('button[class*="close"]:visible', 'оверлей close'),
            ('button[aria-label*="Закрыть"]:visible', 'оверлей aria'),
            ('button[aria-label*="close" i]:visible', 'оверлей aria-en'),
            ('[class*="popup"] [class*="close"]:visible', 'popup close'),
        ]
        for selector, name in candidates:
            try:
                btn = page.locator(selector).first
                if btn.is_visible(timeout=500):
                    btn.click(timeout=1200)
                    page.wait_for_timeout(400)
                    if label:
                        self._log('INFO', f'[{label}] Закрыт попап WB ({name}): {selector}')
                    return
            except Exception:
                pass

    def _get_wb_product_urls(self, page) -> list[str]:
        try:
            urls = page.evaluate("""
                () => {
                    const links = Array.from(document.querySelectorAll('a[href*="/catalog/"]'));
                    return [...new Set(links.map(a => a.href).filter(h => /\\/catalog\\/\\d+/.test(h)))];
                }
            """)
            random.shuffle(urls)
            return urls[:2]
        except Exception:
            return []

    def _check_wb(self, page, proxy, label, result, antidetect_cfg, context) -> ProxyTestResult:
        page.goto('https://www.wildberries.ru', wait_until='domcontentloaded', timeout=30000)
        page.wait_for_timeout(2000)
        self._dismiss_cookie_consent(page, label)
        self._dismiss_wb_popups(page, label)
        self._log_page_state(page, label, 'Главная WB загружена')

        body_text = page.locator('body').inner_text(timeout=5000)
        is_denied, _ = detect_access_denied_wb(body_text)
        if is_denied:
            self._log_page_state(page, label, 'Access denied на главной WB')
            result.status = 'access_denied'
            return result

        # Ищем карточки товаров WB (/catalog/\d+) с retry.
        # wait_for_selector срабатывает на nav-ссылки /catalog/category — поэтому
        # проверяем именно числовые ID и повторяем, пока SPA не дорендерит карточки.
        product_urls: list[str] = []
        attempts = 3
        for attempt in range(1, attempts + 1):
            product_urls = self._get_wb_product_urls(page)
            if product_urls:
                break
            if attempt < attempts:
                self._log('INFO', f'[{label}] Ссылки на товары WB не найдены (попытка {attempt}/{attempts}), ждём...')
                page.wait_for_timeout(2000)
                self._dismiss_wb_popups(page, label)
                try:
                    page.mouse.wheel(0, 300)
                    page.wait_for_timeout(500)
                except Exception:
                    pass

        if not product_urls:
            self._log_page_state(page, label, 'Товары WB не найдены на главной')
            result.status = 'no_product_links'
            return result

        self._log('INFO', f'[{label}] Найдено ссылок WB: {len(product_urls)}, проверяем...')
        for prod_url in product_urls[:1]:
            self._log('INFO', f'[{label}] Проверяем товар WB: {prod_url}')
            try:
                page.goto(prod_url, wait_until='domcontentloaded', timeout=35000)
                page.wait_for_timeout(1500)
                card_text = page.locator('body').inner_text(timeout=5000)
                is_denied, _ = detect_access_denied_wb(card_text)
                if is_denied:
                    result.status = 'access_denied'
                    return result
            except PlaywrightTimeoutError:
                result.status = 'timeout'
                return result

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
        return result
