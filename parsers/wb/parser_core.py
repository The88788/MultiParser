# core/parser_core.py by 88788
from __future__ import annotations

import re
import time
import random
import json
from pathlib import Path
import base64
import os
import tempfile
from typing import Callable, Optional, Any, Tuple
from urllib.parse import urlparse

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import Browser, Page

# Patchright бросает собственные классы исключений, отличные от playwright.
# Объединяем в кортежи чтобы один except ловил оба случая.
try:
    from patchright.sync_api import TimeoutError as _PatchTimeoutError
    from patchright.sync_api import Error as _PatchError
    _TIMEOUT_EXC = (PlaywrightTimeoutError, _PatchTimeoutError)
    _PLAYWRIGHT_EXC = (PlaywrightError, _PatchError)
except ImportError:
    _TIMEOUT_EXC = (PlaywrightTimeoutError,)
    _PLAYWRIGHT_EXC = (PlaywrightError,)

from parsers.wb.excel_exporter import export_snapshot
from parsers.wb.extractors import (
    count_unique_texts,
    detect_404_wb,
    detect_access_denied_wb,
    detect_sold_out_wb,
    extract_color_variants_from_cdn,
    extract_color_variants_from_links,
    extract_sizes_from_cdn,
    extract_brand_from_cdn,
    extract_product_name_from_cdn,
    extract_seller_from_cdn,
    fetch_wb_cdn,
    join_variant_texts,
    parse_prices_wb,
)
from parsers.wb.models import ErrorRow, ParseResult, RunOutput, RunStats
from core.proxy_manager import ProxyManager
from core.queue_manager import QueueManager
from core.utils import normalize_space, normalize_price, now_str, time_str, random_pause_seconds, stamp_for_filename
from parsers.wb.utils import build_wb_product_url, extract_wb_product_id_from_url
from core.browser_utils import random_ua_profile, random_user_agent, random_viewport, random_geolocation, load_cookies, save_cookies, random_antidetect_strategy, proxy_check_strategy, get_sync_playwright, find_chrome_executable


# ========== Антидетект менеджер ==========
class StealthManager:
    """Управляет стратегией антидетекта: XDriver, Camoufox, BrowserForge."""
    def __init__(self, config: dict, log_func: Callable[[str, str], None]):
        self.config = config.get('antidetect', {})
        self.log = log_func
        self.strategy = self.config.get('strategy', 'stealth_js')  # stealth_js, xdriver, camoufox, browserforge

    STRATEGY_NAMES = {
        'stealth_js':   'Стандартная',
        'xdriver':      'Расширенная',
        'browserforge': 'Профильная',
        'patchright':   'Максимальная',
        'camoufox':     'Firefox',
        'chrome':       'Chrome',
    }

    def apply(self, page: Page) -> None:
        if self.strategy == 'stealth_js':
            self._apply_stealth_js(page)
        elif self.strategy == 'xdriver':
            self._apply_playwright_stealth(page)
        elif self.strategy == 'camoufox':
            pass  # Camoufox управляет браузером на уровне запуска
        elif self.strategy == 'browserforge':
            self._apply_browserforge(page)
        elif self.strategy == 'patchright':
            pass  # Patchright патчит webdriver/TLS на уровне бинарника Chromium
        elif self.strategy == 'chrome':
            self._apply_stealth_js(page)  # JS-патчи нужны: Playwright всё равно ставит webdriver флаг

    def _apply_stealth_js(self, page: Page) -> None:
        page.add_init_script("""
        (() => {
            // Каждая секция независима: если одна упала — остальные продолжают работать.
            // Это критично для страниц капчи, где некоторые глобалы могут быть недоступны.

            try {
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            } catch(_) {}

            try {
                ['__playwright','__pw_manual','__PW_inspect','__selenium_unwrapped',
                 '__webdriver_evaluate','__driver_evaluate','__webdriver_script_fn',
                 '__driver_unwrapped','_Selenium_IDE_Recorder','_selenium',
                 'calledSelenium','_WEBDRIVER_ELEM_CACHE'
                ].forEach(k => { try { delete window[k]; } catch(_) {} });
            } catch(_) {}

            try {
                window.chrome = {
                    app: {
                        isInstalled: false,
                        InstallState: { DISABLED:'disabled', INSTALLED:'installed', NOT_INSTALLED:'not_installed' },
                        RunningState: { CANNOT_RUN:'cannot_run', READY_TO_RUN:'ready_to_run', RUNNING:'running' },
                        getDetails: function() { return null; },
                        getIsInstalled: function() { return false; },
                        installState: function(cb) { cb('not_installed'); },
                        runningState: function() { return 'cannot_run'; },
                    },
                    csi: function() {
                        return { onloadT: Date.now(), pageT: 100, startE: Date.now() - 100, tran: 15 };
                    },
                    loadTimes: function() {
                        var t = Date.now() / 1000;
                        return { commitLoadTime: t - 0.4, connectionInfo: 'h2',
                            finishDocumentLoadTime: t - 0.1, finishLoadTime: t,
                            firstPaintAfterLoadTime: 0, firstPaintTime: t - 0.3,
                            navigationType: 'Other', npnNegotiatedProtocol: 'h2',
                            requestTime: t - 0.5, startLoadTime: t - 0.5,
                            wasAlternateProtocolAvailable: false, wasFetchedViaSpdy: true,
                            wasNpnNegotiated: true };
                    },
                    runtime: { connect: function() { return {}; }, sendMessage: function() {}, id: undefined },
                };
            } catch(_) {}

            try {
                var _origQuery = window.navigator.permissions.query.bind(window.navigator.permissions);
                window.navigator.permissions.query = function(params) {
                    if (params && params.name === 'notifications') {
                        return Promise.resolve({ state: Notification.permission });
                    }
                    return _origQuery(params);
                };
            } catch(_) {}

            try {
                Object.defineProperty(navigator, 'languages', { get: () => ['ru-RU','ru','en-US','en'] });
            } catch(_) {}

            // Plugin/MimeType — используем plain objects без Object.create(Plugin.prototype),
            // чтобы не упасть на странице капчи где Plugin может быть недоступен.
            try {
                var _pluginData = [
                    { name:'PDF Viewer', description:'Portable Document Format',
                      filename:'internal-pdf-viewer',
                      mimes:[{type:'application/pdf',suffixes:'pdf'},{type:'text/pdf',suffixes:'pdf'}] },
                    { name:'Chrome PDF Viewer', description:'Portable Document Format',
                      filename:'internal-pdf-viewer', mimes:[{type:'application/pdf',suffixes:'pdf'}] },
                    { name:'Chromium PDF Viewer', description:'Portable Document Format',
                      filename:'internal-pdf-viewer', mimes:[{type:'application/pdf',suffixes:'pdf'}] },
                    { name:'Microsoft Edge PDF Viewer', description:'Portable Document Format',
                      filename:'internal-pdf-viewer', mimes:[{type:'application/pdf',suffixes:'pdf'}] },
                    { name:'WebKit built-in PDF', description:'Portable Document Format',
                      filename:'internal-pdf-viewer', mimes:[{type:'application/pdf',suffixes:'pdf'}] },
                ];
                var _fakePlugins = _pluginData.map(function(d) {
                    var p = { name: d.name, description: d.description,
                               filename: d.filename, length: d.mimes.length };
                    d.mimes.forEach(function(m, i) {
                        p[i] = { type: m.type, suffixes: m.suffixes, description: d.description, enabledPlugin: p };
                    });
                    p.item = function(i) { return this[i] || null; };
                    p.namedItem = function(n) { return this[0] && this[0].type === n ? this[0] : null; };
                    p[Symbol.iterator] = function*() { for (var i = 0; i < this.length; i++) yield this[i]; };
                    return p;
                });
                Object.defineProperty(navigator, 'plugins', {
                    get: function() {
                        var arr = { length: _fakePlugins.length,
                            item: function(i) { return _fakePlugins[i] || null; },
                            namedItem: function(n) { return _fakePlugins.find(function(p){ return p.name===n; }) || null; },
                            refresh: function() {} };
                        _fakePlugins.forEach(function(p,i) { arr[i] = p; });
                        arr[Symbol.iterator] = function*() { for (var i=0; i<this.length; i++) yield this[i]; };
                        return arr;
                    },
                    enumerable: true,
                });
                Object.defineProperty(navigator, 'mimeTypes', {
                    get: function() {
                        var mts = [
                            { type:'application/pdf', suffixes:'pdf', description:'Portable Document Format' },
                            { type:'text/pdf', suffixes:'pdf', description:'Portable Document Format' },
                        ];
                        var arr = { length: mts.length,
                            item: function(i) { return mts[i] || null; },
                            namedItem: function(t) { return mts.find(function(m){ return m.type===t; }) || null; } };
                        mts.forEach(function(m,i) { arr[i] = m; });
                        arr[Symbol.iterator] = function*() { for (var i=0; i<this.length; i++) yield this[i]; };
                        return arr;
                    },
                    enumerable: true,
                });
            } catch(_) {}

            try {
                var _conc = [4,6,8,12,16][Math.floor(Math.random()*5)];
                Object.defineProperty(navigator, 'hardwareConcurrency', { get: function() { return _conc; } });
            } catch(_) {}

            try {
                Object.defineProperty(navigator, 'deviceMemory', { get: function() { return 8; } });
            } catch(_) {}

            try {
                Object.defineProperty(navigator, 'connection', {
                    get: function() {
                        return { effectiveType:'4g', rtt:50, downlink:10, saveData:false, onchange:null };
                    }, enumerable: true,
                });
            } catch(_) {}

            try { Object.defineProperty(screen, 'colorDepth', { get: function(){ return 24; } }); } catch(_) {}
            try { Object.defineProperty(screen, 'pixelDepth',  { get: function(){ return 24; } }); } catch(_) {}

            // Canvas fingerprint: добавляем невидимый шум в копию canvas при вызове toDataURL,
            // чтобы сломать hash-сигнатуру headless Chromium, не затрагивая оригинальный canvas.
            try {
                var _origToDataURL = HTMLCanvasElement.prototype.toDataURL;
                HTMLCanvasElement.prototype.toDataURL = function() {
                    try {
                        var tmp = document.createElement('canvas');
                        tmp.width  = this.width  || 1;
                        tmp.height = this.height || 1;
                        var tCtx = tmp.getContext('2d');
                        tCtx.drawImage(this, 0, 0);
                        var img = tCtx.getImageData(0, 0, tmp.width, tmp.height);
                        for (var i = 0; i < img.data.length; i += 97) {
                            img.data[i] = (img.data[i] + 1) & 255;
                        }
                        tCtx.putImageData(img, 0, 0);
                        return _origToDataURL.apply(tmp, arguments);
                    } catch(_) {
                        return _origToDataURL.apply(this, arguments);
                    }
                };
            } catch(_) {}

            // WebGL fingerprint: скрываем «Google SwiftShader» — маркер headless Chrome.
            // Каждая сессия получает случайный, но реалистичный GPU из типичных конфигураций Windows.
            try {
                var _gpuList = [
                    ['Google Inc. (NVIDIA)', 'ANGLE (NVIDIA, NVIDIA GeForce GTX 1060 6GB Direct3D11 vs_5_0 ps_5_0, D3D11)'],
                    ['Google Inc. (NVIDIA)', 'ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)'],
                    ['Google Inc. (Intel)',  'ANGLE (Intel, Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0, D3D11)'],
                    ['Google Inc. (Intel)',  'ANGLE (Intel, Intel(R) Iris(R) Xe Graphics Direct3D11 vs_5_0 ps_5_0, D3D11)'],
                    ['Google Inc. (AMD)',    'ANGLE (AMD, AMD Radeon RX 580 Direct3D11 vs_5_0 ps_5_0, D3D11)'],
                ];
                var _gpu = _gpuList[Math.floor(Math.random() * _gpuList.length)];
                var _wv = _gpu[0], _wr = _gpu[1];
                [WebGLRenderingContext, WebGL2RenderingContext].forEach(function(Ctx) {
                    try {
                        var _orig = Ctx.prototype.getParameter;
                        Ctx.prototype.getParameter = function(param) {
                            if (param === 37445) return _wv;
                            if (param === 37446) return _wr;
                            return _orig.call(this, param);
                        };
                    } catch(_) {}
                });
            } catch(_) {}

        })();
        """)
        self._apply_playwright_stealth(page)

    def _apply_playwright_stealth(self, page: Page) -> None:
        try:
            from playwright_stealth import stealth_sync
            stealth_sync(page)
        except ImportError:
            pass

    def _apply_browserforge(self, page: Page) -> None:
        try:
            from browserforge.fingerprints import FingerprintGenerator
            from browserforge.injector import inject_fingerprint
            generator = FingerprintGenerator(
                browser=('chrome',),
                os=('windows',),
                device='desktop',
            )
            fingerprint = generator.generate()
            inject_fingerprint(page, fingerprint)
        except Exception:
            self._apply_playwright_stealth(page)


# ========== Менеджер решения капчи ==========
class CaptchaSolverManager:
    """Поддержка 2Captcha и CapSolver с fallback."""
    def __init__(self, config: dict, log_func: Callable[[str, str], None]):
        self.config = config.get('captcha', {})
        self.log = log_func
        self.primary = self.config.get('primary_service', 'CapSolver')
        self.fallback = self.config.get('fallback_service', '2Captcha')
        self.api_keys = {
            '2Captcha': self.config.get('twocaptcha_api_key', ''),
            'CapSolver': self.config.get('capsolver_api_key', ''),
            'Anti-Captcha': self.config.get('anticaptcha_api_key', ''),
        }
        self.timeout = self.config.get('timeout', 120)

    def has_any_key(self) -> bool:
        """Возвращает True если хотя бы один сервис имеет API-ключ."""
        return any(bool(k) for k in self.api_keys.values())

    def _active_services(self) -> list:
        """Строит упорядоченный список сервисов с ключами: primary → fallback → остальные."""
        seen: set = set()
        result: list = []
        for svc in [self.primary, self.fallback, '2Captcha', 'CapSolver', 'Anti-Captcha']:
            if svc and svc not in seen:
                seen.add(svc)
                if self.api_keys.get(svc):
                    result.append(svc)
        return result

    def solve_turnstile(self, page: Page, url: str) -> Optional[str]:
        """Пытается решить Turnstile капчу через выбранные сервисы."""
        site_key = self._extract_site_key(page)
        if not site_key:
            self.log('WARNING', 'Не удалось извлечь sitekey для Turnstile')
            return None

        for service in self._active_services():
            token = self._solve_with_service(service, url, site_key)
            if token:
                self._inject_token(page, token)
                return token
        return None

    def _extract_site_key(self, page: Page) -> Optional[str]:
        try:
            # Ищем в iframe или data-атрибутах
            site_key = page.evaluate("""
                () => {
                    const iframe = document.querySelector('iframe[src*="turnstile"]');
                    if (iframe) {
                        const src = iframe.getAttribute('src');
                        const match = src.match(/sitekey=([^&]+)/);
                        if (match) return match[1];
                    }
                    const div = document.querySelector('[data-sitekey]');
                    if (div) return div.getAttribute('data-sitekey');
                    return null;
                }
            """)
            return site_key
        except Exception:
            return None

    def _solve_with_service(self, service: str, url: str, site_key: str) -> Optional[str]:
        api_key = self.api_keys.get(service)
        if not api_key:
            self.log('WARNING', f'API ключ для {service} не задан')
            return None

        self.log('INFO', f'Отправка капчи в {service}...')
        try:
            if service == '2Captcha':
                from twocaptcha import TwoCaptcha
                solver = TwoCaptcha(api_key)
                result = solver.turnstile(sitekey=site_key, url=url)
                token = result['code']
            elif service == 'CapSolver':
                import capsolver
                capsolver.api_key = api_key
                result = capsolver.solve({
                    "type": "AntiTurnstileTaskProxyLess",
                    "websiteURL": url,
                    "websiteKey": site_key
                })
                token = result['token']
            elif service == 'Anti-Captcha':
                from anticaptchaofficial.turnstileproxyless import turnstileProxyless
                solver = turnstileProxyless()
                solver.set_verbose(0)
                solver.set_key(api_key)
                token = solver.solve_and_return_solution(
                    websiteURL=url,
                    websiteKey=site_key,
                )
                if token == 0:
                    raise Exception(f'Anti-Captcha error: {solver.error_code}')
            else:
                return None
            self.log('INFO', f'Токен получен от {service}')
            return token
        except Exception as e:
            self.log('ERROR', f'{service} ошибка: {e}')
            return None

    def _inject_token(self, page: Page, token: str) -> None:
        page.evaluate(f"""
            () => {{
                const input = document.querySelector('input[name="cf-turnstile-response"]');
                if (input) {{
                    input.value = '{token}';
                }}
                // Вызов callback если есть
                if (typeof window.turnstile !== 'undefined') {{
                    window.turnstile.render = (container, params) => {{
                        params.callback('{token}');
                    }};
                }}
            }}
        """)
        self.log('INFO', 'Токен капчи вставлен в страницу')

    def solve_image_coordinates(self, image_bytes: bytes) -> Optional[Tuple[int, int]]:
        """Отправляет скриншот капчи в сервис, получает x,y координаты целевой позиции."""
        img_b64 = base64.b64encode(image_bytes).decode()
        for service in self._active_services():
            result = self._coordinates_with_service(service, img_b64)
            if result:
                return result
        return None

    @staticmethod
    def _parse_coord_item(coords) -> Optional[Tuple[int, int]]:
        """Разбирает координаты из любого формата ответа сервиса."""
        if not coords:
            return None
        first = coords[0]
        if isinstance(first, dict):
            return (int(first.get('x', 0)), int(first.get('y', 0)))
        if isinstance(first, (int, float)):
            y = int(coords[1]) if len(coords) > 1 else 0
            return (int(first), y)
        if isinstance(first, (list, tuple)) and len(first) >= 2:
            return (int(first[0]), int(first[1]))
        return None

    def _coordinates_with_service(self, service: str, img_b64: str) -> Optional[Tuple[int, int]]:
        api_key = self.api_keys.get(service)
        if not api_key:
            return None
        self.log('INFO', f'Отправка изображения капчи в {service} для определения координат...')
        try:
            if service == '2Captcha':
                from twocaptcha import TwoCaptcha
                solver = TwoCaptcha(api_key)
                # Сохраняем во временный файл — SDK ожидает путь к файлу или URL
                with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
                    f.write(base64.b64decode(img_b64))
                    tmp_path = f.name
                try:
                    result = solver.coordinates(tmp_path)
                finally:
                    try:
                        os.unlink(tmp_path)
                    except Exception:
                        pass
                # Формат ответа: {'code': 'click:x=150,y=75', ...}
                code = result.get('code', '')
                if 'click:' in code:
                    parts = code.replace('click:', '').split(',')
                    x = int(parts[0].split('=')[1])
                    y = int(parts[1].split('=')[1]) if len(parts) > 1 else 0
                    self.log('INFO', f'2Captcha вернул координаты: x={x}, y={y}')
                    return (x, y)

            elif service == 'CapSolver':
                import capsolver
                capsolver.api_key = api_key
                result = capsolver.solve({
                    'type': 'ImageToCoordinatesTask',
                    'imagecontent': img_b64,
                    'module': 'slide',
                })
                solution = result.get('solution') if isinstance(result, dict) else result
                coords = solution if isinstance(solution, list) else (solution or {}).get('coordinates', [])
                xy = self._parse_coord_item(coords)
                if xy:
                    self.log('INFO', f'CapSolver вернул координаты: x={xy[0]}, y={xy[1]}')
                    return xy

            elif service == 'Anti-Captcha':
                import requests as _req

                def _ac_create_task():
                    r = _req.post(
                        'https://api.anti-captcha.com/createTask',
                        json={
                            'clientKey': api_key,
                            'task': {
                                'type': 'ImageToCoordinatesTask',
                                'body': img_b64,
                                'comment': 'Click on the position where the puzzle piece fits in the gap',
                                'mode': 'points',
                            },
                        },
                        timeout=30,
                    )
                    d = r.json()
                    if d.get('errorId', 1) != 0:
                        raise Exception(f'createTask error: {d.get("errorDescription")}')
                    return d['taskId']

                def _ac_wait_result(task_id):
                    for _ in range(self.timeout // 5):
                        time.sleep(5)
                        res = _req.post(
                            'https://api.anti-captcha.com/getTaskResult',
                            json={'clientKey': api_key, 'taskId': task_id},
                            timeout=30,
                        ).json()
                        if res.get('status') == 'ready':
                            solution = res.get('solution')
                            coords = solution if isinstance(solution, list) \
                                else (solution or {}).get('coordinates', [])
                            return self._parse_coord_item(coords), solution
                    return None, None

                for attempt in range(2):
                    task_id = _ac_create_task()
                    xy, solution = _ac_wait_result(task_id)
                    if xy:
                        self.log('INFO', f'Anti-Captcha вернул координаты: x={xy[0]}, y={xy[1]}')
                        return xy
                    self.log('WARNING', f'Anti-Captcha: solution без координат (попытка {attempt+1}): {solution}')

        except Exception as e:
            self.log('ERROR', f'{service} coordinates ошибка: {e}')
        return None


# ========== Основной класс парсера ==========
class ParserCore:
    def __init__(
        self,
        *,
        base_dir: Path,
        profile_name: str | None = None,
        config: dict,
        stop_requested: Callable[[], bool],
        log: Callable[[str, str], None],
        stats_callback: Callable[[RunStats], None] | None = None,
    ) -> None:
        self.base_dir = base_dir
        self.profile_name = profile_name
        self.config = config
        self.stop_requested = stop_requested
        # Оригинальная функция логирования (вывод в GUI)
        self._original_log = log

        # Оборачиваем логирование: добавляем временную метку и запись в файл
        def _wrapped_log(level: str, message: str) -> None:
            timestamp = now_str()
            self._original_log(level, f'[{time_str()}] {message}')
            self._file_log(level, f'[{timestamp}] [{level}] {message}')

        self.log = _wrapped_log
        # ------------------------------------------------------------------
        self.stats_callback = stats_callback
        self.output = RunOutput()
        self.queue_manager = QueueManager()
        self.parser_cfg = config.get('parser', {})
        self.proxy_cfg = config.get('proxy', {})
        self.antidetect_cfg = config.get('antidetect', {})
        self.proxy_manager = ProxyManager(self.proxy_cfg)
        self.stealth_manager = StealthManager(config, log)
        self.captcha_solver = CaptchaSolverManager(config, log)
        self.stats = self.output.stats
        self.access_denied_streak = 0
        self._proxy_retries_for_current_item = 0
        self._proxy_stats: dict[str, dict[str, int]] = {}  # накапливает статистику по маскированным прокси
        self._current_proxy_masked: str = ''
        self._current_proxy_host: str = ''   # хост прокси для GEO-запроса
        self._geo_cache: dict[str, str] = {}  # кеш GEO по хосту, чтобы не дёргать API повторно
        self._proxy_seq_idx: int = 0         # счётчик ротации прокси из файла между сессиями
        self._proxy_label: str = ''  # метка для потоков (устанавливается извне)
        self._camoufox_ctx = None  # хранит экземпляр Camoufox для корректной очистки
        self._partial_stamp: str = ''
        self._partial_output_file: str = ''

    def _validate_proxy_server(self, server: str) -> None:
        server = (server or "").strip()
        if not server:
            raise ValueError("Прокси включен, но адрес прокси пустой")
        if not (server.startswith("http://") or server.startswith("https://") or server.startswith("socks5://")):
            raise ValueError("Неверный формат прокси. Пример: http://127.0.0.1:8080 или socks5://127.0.0.1:1080")
        parsed = urlparse(server)
        if not parsed.hostname or not parsed.port:
            raise ValueError("Неверный формат прокси. Должно быть так: http://IP:PORT или socks5://IP:PORT")

    def _mask_proxy(self, proxy: dict) -> str:
        """Создаёт безопасную для лога версию адреса прокси."""
        server = proxy.get('server', '')
        if len(server) > 12:
            return server[:6] + '***' + server[-6:]
        return server

    def _parse_single_proxy_line(self, raw: str) -> dict:
        raw = (raw or "").strip()
        if not raw:
            raise ValueError("Строка прокси пустая")
        if "://" in raw:
            parsed = urlparse(raw)
            if not parsed.scheme or not parsed.hostname or not parsed.port:
                raise ValueError(f"Неверная строка прокси: {raw}")
            server = f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"
            proxy = {"server": server}
            if parsed.username:
                proxy["username"] = parsed.username
            if parsed.password:
                proxy["password"] = parsed.password
            self._validate_proxy_server(proxy["server"])
            return proxy
        parts = raw.split(":")
        if len(parts) == 4:
            host, port, username, password = parts
            server = f"http://{host.strip()}:{port.strip()}"
            proxy = {"server": server, "username": username.strip(), "password": password.strip()}
            self._validate_proxy_server(proxy["server"])
            return proxy
        if len(parts) == 2:
            host, port = parts
            server = f"http://{host.strip()}:{port.strip()}"
            proxy = {"server": server}
            self._validate_proxy_server(proxy["server"])
            return proxy
        raise ValueError("Не удалось распознать формат прокси. Поддерживаются: http://host:port, socks5://host:port, http://login:pass@host:port, host:port, host:port:login:password")

    def _resolve_proxy_config(self) -> dict | None:
        proxy_enabled = bool(self.proxy_cfg.get("enabled", False))
        if not proxy_enabled:
            return None
        use_single_proxy = bool(self.proxy_cfg.get("use_single_proxy", True))
        single_proxy = str(self.proxy_cfg.get("single_proxy", "")).strip()
        proxy_file = str(self.proxy_cfg.get("proxy_file", "")).strip()
        if use_single_proxy:
            if not single_proxy:
                raise ValueError("Прокси включен, но поле single_proxy пустое")
            proxy = self._parse_single_proxy_line(single_proxy)
            self._current_proxy_masked = self._mask_proxy(proxy)
            self._current_proxy_host = urlparse(proxy['server']).hostname or ''
            return proxy
        if not proxy_file:
            raise ValueError("Прокси включен, но путь к proxy_file пустой")
        proxy_path = Path(proxy_file)
        if not proxy_path.is_absolute():
            proxy_path = self.base_dir / proxy_path
        if not proxy_path.exists():
            raise ValueError(f"Файл прокси не найден: {proxy_path}")
        lines = [line.strip() for line in proxy_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not lines:
            raise ValueError(f"Файл прокси пустой: {proxy_path}")

        # Последовательная ротация: каждая сессия берёт следующую прокси по кругу
        total = len(lines)
        errors = []
        for offset in range(total):
            seq_idx = (self._proxy_seq_idx + offset) % total
            line = lines[seq_idx]
            try:
                proxy = self._parse_single_proxy_line(line)
                masked_line = line if len(line) <= 12 else line[:6] + '***' + line[-6:]
                self.log('INFO', f'Proxy из файла: строка {seq_idx + 1}/{total} (ротация)')
                self.log('INFO', f'Строка proxy: {masked_line}')
                self._current_proxy_masked = self._mask_proxy(proxy)
                self._current_proxy_host = urlparse(proxy['server']).hostname or ''
                self._proxy_seq_idx = (seq_idx + 1) % total  # сдвигаем для следующей сессии
                return proxy
            except ValueError as exc:
                errors.append(f"строка {seq_idx + 1}: {line} -> {exc}")
        joined = "\n".join(errors[:5])
        raise ValueError(f"В файле proxy не найдено ни одной валидной строки. Примеры ошибок:\n{joined}")

    def _build_launch_kwargs(self) -> dict:
        launch_kwargs = {
            "headless": not bool(self.parser_cfg.get("headed", True)),
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process,TranslateUI,BlockInsecurePrivateNetworkRequests",
                "--no-sandbox",
                "--disable-web-security",
                "--lang=ru-RU",
            ],
        }
        if self.stealth_manager.strategy == 'chrome':
            chrome_path = find_chrome_executable()
            if chrome_path:
                launch_kwargs['executable_path'] = chrome_path
                self.log('INFO', f'Используется реальный Chrome: {chrome_path}')
            else:
                self.log('WARNING', 'Real Chrome не найден — используем Chromium')
        proxy = self._resolve_proxy_config()
        if proxy:
            if proxy['server'].startswith('socks5://') and proxy.get('username'):
                raise ValueError(
                    'SOCKS5 прокси с логином/паролем не поддерживается используемым методом антидетекта. '
                    'Замените протокол на HTTP или используйте SOCKS5 без авторизации.'
                )
            launch_kwargs["proxy"] = proxy
            safe_proxy = proxy["server"]
            if proxy.get("username"):
                self.log("INFO", f"Использую proxy: {safe_proxy} с авторизацией")
            else:
                self.log("INFO", f"Использую proxy: {safe_proxy}")
        else:
            self.log("INFO", "Proxy отключен")
        return launch_kwargs

    def _create_browser_and_page(self, playwright):
        """Создаёт браузер, контекст и страницу с учётом текущих настроек."""
        # Ротация стратегии выполняется до открытия with-блока (чтобы выбрать нужный лаунчер).
        # Здесь только логируем уже выбранную стратегию.
        strategy_name = self.stealth_manager.STRATEGY_NAMES.get(self.stealth_manager.strategy, self.stealth_manager.strategy)
        self.log('INFO', f'Выбрана стратегия: {strategy_name}')

        # Camoufox запускает собственный Firefox — отдельный путь
        if self.stealth_manager.strategy == 'camoufox':
            return self._create_camoufox_browser_and_page()

        # Стандартный путь: Chromium через Playwright
        launch_kwargs = self._build_launch_kwargs()
        browser = playwright.chromium.launch(**launch_kwargs)

        viewport = random_viewport()
        ua_profile = random_ua_profile()
        user_agent = ua_profile['ua']
        geo = random_geolocation()
        self.log('INFO', f'Viewport: {viewport["width"]}x{viewport["height"]}')
        self.log('INFO', f'User-Agent: {user_agent}')

        context = browser.new_context(
            viewport=viewport,
            user_agent=user_agent,
            locale="ru-RU",
            timezone_id="Europe/Moscow",
            geolocation=geo,
            permissions=["geolocation"],
            device_scale_factor=1,
            is_mobile=False,
            has_touch=False,
            ignore_https_errors=True,
            extra_http_headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
                "Accept-Encoding": "gzip, deflate, br, zstd",
                "Sec-Ch-Ua": ua_profile['sec_ch_ua'],
                "Sec-Ch-Ua-Full-Version-List": ua_profile['sec_ch_ua_full'],
                "Sec-Ch-Ua-Mobile": "?0",
                "Sec-Ch-Ua-Platform": '"Windows"',
                "Sec-Ch-Ua-Platform-Version": '"15.0.0"',
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                "Upgrade-Insecure-Requests": "1",
            }
        )
        if not self.parser_cfg.get('disable_shared_cookies', True):
            load_cookies(context, self.base_dir, self.profile_name, log=self.log)
        page = context.new_page()
        self.stealth_manager.apply(page)
        return browser, context, page

    def _create_camoufox_browser_and_page(self):
        """Запускает Firefox через Camoufox — антидетект на уровне браузера."""
        from camoufox.sync_api import Camoufox
        headless = not bool(self.parser_cfg.get('headed', True))
        proxy = self._resolve_proxy_config()

        kwargs = {'headless': headless, 'locale': ['ru-RU', 'ru']}
        if proxy:
            kwargs['proxy'] = proxy

        camoufox_instance = Camoufox(**kwargs)
        browser = camoufox_instance.__enter__()
        self._camoufox_ctx = camoufox_instance

        viewport = random_viewport()
        self.log('INFO', f'Viewport: {viewport["width"]}x{viewport["height"]}')

        context = browser.new_context(
            viewport=viewport,
            locale='ru-RU',
            timezone_id='Europe/Moscow',
            geolocation={'latitude': 55.7558, 'longitude': 37.6176},
            permissions=['geolocation'],
            ignore_https_errors=True,
        )
        if not self.parser_cfg.get('disable_shared_cookies', True):
            load_cookies(context, self.base_dir, self.profile_name, log=self.log)
        page = context.new_page()
        return browser, context, page

    def _cleanup_browser(self, browser, context) -> None:
        """Закрывает браузер и контекст, включая очистку Camoufox если он был запущен."""
        try:
            context.close()
        except Exception as exc:
            self.log('WARNING', f'Ошибка при закрытии контекста браузера: {exc}')
        browser_closed = False
        try:
            browser.close()
            browser_closed = True
        except Exception as exc:
            self.log('WARNING', f'Ошибка при закрытии браузера: {exc}')
        if not browser_closed:
            try:
                import psutil
                current = psutil.Process()
                for child in current.children(recursive=True):
                    if 'chrom' in child.name().lower():
                        try:
                            child.kill()
                        except psutil.NoSuchProcess:
                            pass
            except Exception:
                pass
        if self._camoufox_ctx is not None:
            try:
                self._camoufox_ctx.__exit__(None, None, None)
            except Exception:
                pass
            self._camoufox_ctx = None

    def run(self, input_ids: list[str]) -> RunOutput:
        cleaned_input_ids = [x.strip() for x in input_ids if x and x.strip()]
        self.stats.total_input_ids = len(cleaned_input_ids)

        # Этап 5: резервируем input IDs чтобы варианты из других чанков не дублировали их
        self.queue_manager.reserve_input_ids(set(cleaned_input_ids))

        # Этап 1: инициализация partial-снимка
        _output_dir = self.base_dir / 'output'
        if _output_dir.exists():
            for _pf in _output_dir.glob('parsing_partial_*.xlsx'):
                try:
                    _pf.unlink()
                except Exception:
                    pass
        self._partial_stamp = stamp_for_filename()
        self._partial_output_file = ''

        max_pages_per_run = int(self.parser_cfg.get('max_pages_per_run', 0) or 0)
        parsed_pages = 0
        self._proxy_retries_for_current_item = 0

        # Формируем сессии случайного размера (20–50 товаров)
        chunks = []
        idx = 0
        total = len(cleaned_input_ids)
        while idx < total:
            chunk_size = random.randint(20, 50)
            chunks.append(cleaned_input_ids[idx:idx + chunk_size])
            idx += chunk_size
        self.log('INFO', f'Будет обработано сессий: {len(chunks)} (размер сессий случайный: 20–50 товаров)')

        used_strategies: list[str] = []  # цикл patchright→chrome→xdriver→browserforge→stealth_js→...
        for chunk_idx, chunk in enumerate(chunks, start=1):
            if self.stop_requested():
                self.log('WARNING', 'Остановка запрошена пользователем перед началом сессии')
                break

            self.log('INFO', f'=== Запуск сессии {chunk_idx}/{len(chunks)}, товаров в сессии: {len(chunk)} ===')

            # Добавляем товары текущей порции в очередь (очищать очередь между сессиями не нужно, она сама опустеет)
            for product_id in chunk:
                added = self.queue_manager.add_seed(product_id)
                relation = self.queue_manager.add_relation(
                    root_input_id=product_id, parent_product_id='',
                    current_product_id=product_id, source_type='input'
                )
                if relation:
                    self.output.relation_rows.append(relation.to_row())
                if added:
                    self.log('INFO', f'Добавлен input_id {product_id}')

            self.stats.unique_seed_ids = len(self.queue_manager.queued_ids)   # обновим статистику
            self._push_stats()

            # Ротацию выполняем здесь — до открытия with-блока, чтобы выбрать правильный лаунчер
            # (Patchright требует своего sync_playwright вместо стандартного Playwright).
            if self.antidetect_cfg.get('rotate', False):
                _strategy = proxy_check_strategy(exclude=used_strategies)
                self.antidetect_cfg['strategy'] = _strategy
                self.stealth_manager = StealthManager({'antidetect': self.antidetect_cfg}, self.log)
                used_strategies.append(_strategy)
                if len(used_strategies) >= 5:   # сброс после полного цикла из 5 стратегий
                    used_strategies = []
            _sync_pw = get_sync_playwright(self.antidetect_cfg.get('strategy', 'stealth_js'))

            with _sync_pw() as playwright:
                try:
                    browser, context, page = self._create_browser_and_page(playwright)
                except ValueError as exc:
                    self.log('ERROR', f'Ошибка настройки прокси в сессии {chunk_idx}: {exc}')
                    raise

                try:
                    # Обрабатываем очередь, пока есть элементы и не превышен лимит страниц (если задан)
                    while len(self.queue_manager) > 0:
                        if self.stop_requested():
                            self.log('WARNING', 'Остановка запрошена пользователем')
                            break
                        if max_pages_per_run and parsed_pages >= max_pages_per_run:
                            self.log('WARNING', f'Достигнут лимит страниц за запуск: {max_pages_per_run}')
                            break

                        entry = self.queue_manager.pop()
                        if entry is None:
                            break

                        # Засекаем время
                        t_start = time.time()
                        result = self._parse_one(page, entry)
                        t_end = time.time()
                        elapsed = t_end - t_start
                        result.parse_time = round(elapsed, 2)   # сохраняем в результат

                        parsed_pages += 1
                        self.queue_manager.mark_visited(entry.current_product_id)
                        required_ok = bool(
                            result.seller and
                            result.price_current
                        )

                        if result.sold_out == 'Да':
                            required_ok = True

                        if not required_ok and result.parse_status == 'ok':
                            missing = []
                            if not result.seller:
                                missing.append('seller')
                            if not result.price_current:
                                missing.append('price_current')
                            result.parse_status = 'missing_required_fields'
                            result.error = 'Не найдены обязательные поля: ' + ', '.join(missing)

                        if not result.proxy_geo and self._current_proxy_host:
                            result.proxy_geo = self._geoip_lookup(self._current_proxy_host)
                        self.stats.processed += 1
                        if result.parse_status == 'ok':
                            self.output.data_rows.append(result.to_row())
                            self.stats.rows = len(self.output.data_rows)
                        else:
                            self.stats.errors += 1
                            friendly = self._friendly_error(result.parse_status, result.error)
                            err_row = ErrorRow(
                                date=now_str(),
                                current_product_id=result.current_product_id,
                                url=result.new_url or result.url_old,
                                error=friendly,
                                error_detail=result.error.splitlines()[0] if result.error else '',
                                parse_status=result.parse_status,
                                incident_id=result.incident_id,
                            )
                            self.output.error_rows.append(err_row.to_row())

                        # Логируем результат
                        self._log_item_result(entry.current_product_id, elapsed, result.parse_status, result.error)
                        if self._current_proxy_masked:
                            self._update_proxy_stats(self._current_proxy_masked, result.parse_status)

                        # --- Автоматическая смена прокси при ошибках доступа ---
                        need_switch = (
                            result.parse_status in ('access_denied', 'timeout', 'open_error', 'missing_required_fields')
                            and self.proxy_cfg.get('enabled')
                            and self.proxy_cfg.get('mode') == 'file'
                        )
                        if need_switch:
                            max_retries = int(self.parser_cfg.get('max_proxy_retries_per_item', 3))
                            if self._proxy_retries_for_current_item < max_retries:
                                self._proxy_retries_for_current_item += 1
                                self.log('WARNING',
                                         f'Переключение прокси (попытка {self._proxy_retries_for_current_item}/{max_retries}) '
                                         f'для товара {entry.current_product_id}')
                                # Закрываем текущий браузер и создаём новый со следующим прокси
                                self._cleanup_browser(browser, context)
                                browser, context, page = self._create_browser_and_page(playwright)
                                # Возвращаем товар в начало очереди
                                self.queue_manager.push_front(entry)
                                self.access_denied_streak = 0
                                continue   # повторно обрабатываем этот же товар с новым прокси
                            else:
                                self.log('ERROR',
                                         f'Превышен лимит попыток смены прокси для товара {entry.current_product_id}. Пропускаем.')
                                self._proxy_retries_for_current_item = 0
                        else:
                            # Если ошибка не связана с сетью, сбрасываем счётчик для следующего товара
                            self._proxy_retries_for_current_item = 0
                        # ---------------------------------------------------------------

                        if result.parse_status == 'access_denied':
                            self.stats.access_denied += 1
                            self.access_denied_streak += 1
                            self.log('ERROR', f'Access denied для {entry.current_product_id}. Серия: {self.access_denied_streak}')
                            if self.access_denied_streak >= int(self.parser_cfg.get('max_access_denied_streak', 3)):
                                self.log('ERROR', 'Остановка запуска из-за серии access_denied')
                                break
                        else:
                            self.access_denied_streak = 0
                            self._expand_variants(result)

                        self._push_stats()
                        _snap_interval = int(self.parser_cfg.get('snapshot_interval', 200) or 200)
                        if _snap_interval > 0 and self.stats.processed > 0 and self.stats.processed % _snap_interval == 0:
                            self._save_partial_snapshot()
                        if len(self.queue_manager) > 0:
                            pause_seconds = random_pause_seconds(
                                float(self.parser_cfg.get('pause_min', 1.2)),
                                float(self.parser_cfg.get('pause_max', 2.8)),
                            )
                            time.sleep(pause_seconds)
                finally:
                    save_cookies(context, self.base_dir, self.profile_name, log=self.log)
                    self._cleanup_browser(browser, context)

            self.log('INFO', f'=== Завершение сессии {chunk_idx} ===')

        # Итоговый экспорт
        spp_pct = int(self.config.get('parser', {}).get('wb_spp_percent', 25))
        self.output.output_file = export_snapshot(
            self.base_dir, self.output.data_rows,
            error_rows=self.output.error_rows or None,
            spp_percent=spp_pct,
        )
        self.log('INFO', f'Excel сохранен: {self.output.output_file}')
        if self._partial_output_file:
            try:
                Path(self._partial_output_file).unlink(missing_ok=True)
            except Exception:
                pass
            self._partial_output_file = ''
        return self.output

    def _parse_one(self, page: Page, entry) -> ParseResult:
        current_url = entry.url_old or build_wb_product_url(entry.current_product_id)
        result = ParseResult(
            root_input_id=entry.root_input_id,
            current_product_id=entry.current_product_id,
            source_type=entry.source_type,
            parent_product_id=entry.parent_product_id,
            url_old=current_url,
            date=now_str(),
        )
        retry_count = int(self.parser_cfg.get('retry_count', 3) or 3)

        for attempt in range(1, retry_count + 1):
            if self.stop_requested():
                result.parse_status = 'stopped'
                result.error = 'Остановка запрошена пользователем'
                return result
            try:
                self.log('INFO', f'Открываю {current_url} (попытка {attempt}/{retry_count})')
                page.goto(current_url, wait_until='domcontentloaded')
                try:
                    networkidle_ms = int(self.parser_cfg.get('networkidle_timeout', 3000) or 3000)
                    page.wait_for_load_state('networkidle', timeout=networkidle_ms)
                except _TIMEOUT_EXC:
                    self.log('DEBUG', 'networkidle timeout — продолжаем')

                # Проверка на WB slider-капчу
                if self._is_wb_captcha_present(page):
                    self.log('WARNING', 'Обнаружена WB slider-капча')
                    if self.captcha_solver.has_any_key():
                        solved = self._solve_wb_slider_captcha(page)
                        if solved is True:
                            if not re.search(r'/catalog/\d+/', page.url):
                                page.goto(current_url, wait_until='domcontentloaded')
                            else:
                                page.wait_for_timeout(1000)
                            try:
                                page.wait_for_selector(
                                    'ins.price-block__final-price, [class*="price-block__final-price"]',
                                    timeout=6000,
                                )
                            except Exception:
                                pass
                        elif solved is None:
                            result.parse_status = 'captcha'
                            result.error = 'Slider-капча: CDN заблокирован прокси, изображение не загружается'
                            break
                        else:
                            result.parse_status = 'captcha'
                            result.error = 'Slider-капча не решена после всех попыток'
                            break
                    else:
                        result.parse_status = 'captcha'
                        result.error = 'Slider-капча — API ключи не настроены'
                        break

                # Проверка на Turnstile (Cloudflare)
                if self._is_turnstile_present(page):
                    self.log('WARNING', 'Обнаружена капча Turnstile, пытаемся решить...')
                    token = self.captcha_solver.solve_turnstile(page, current_url)
                    if token:
                        self.stats.captcha_solved += 1
                        page.wait_for_timeout(3000)
                        page.goto(current_url, wait_until='domcontentloaded')
                    else:
                        self._handle_cloudflare_challenge(page)

                # Обычная проверка Cloudflare без Turnstile
                self._handle_cloudflare_challenge(page)

                page.evaluate(f'window.scrollBy(0, {random.randint(300, 800)})')
                time.sleep(random.uniform(0.5, 1.5))

                # Читаем текст страницы до захвата URL — к этому моменту JS-редиректы завершились
                page_text = page.locator('body').inner_text(timeout=5000)
                result.new_url = page.url

                if not re.search(r'/catalog/\d+/', result.new_url):
                    if detect_sold_out_wb(page_text):
                        result.sold_out = 'Да'
                        result.parse_status = 'ok'
                        result.error = ''
                        return result
                    if detect_404_wb(page_text, result.new_url):
                        result.parse_status = '404'
                        result.error = 'Страница не найдена'
                        return result
                    result.parse_status = 'redirect_unknown'
                    result.error = f'Редирект: {result.new_url}'
                    return result

                # Страница товара
                if detect_sold_out_wb(page_text):
                    result.sold_out = 'Да'
                    result.parse_status = 'ok'
                    result.error = ''
                    return result

                # CSS-fallback: React мог не отрендерить текст к моменту чтения body
                try:
                    if page.locator('[class*="soldOutProduct"]').count() > 0:
                        result.sold_out = 'Да'
                        result.parse_status = 'ok'
                        result.error = ''
                        return result
                except Exception:
                    pass

                result.sold_out = 'Нет'

                is_denied, incident_id = detect_access_denied_wb(page_text)
                if is_denied:
                    result.incident_id = incident_id
                    result.error = 'Доступ ограничен'
                    result.parse_status = 'access_denied'
                    return result

                if detect_404_wb(page_text, page.url):
                    result.parse_status = '404'
                    result.error = 'Страница не найдена'
                    return result

                # Ждём рендер цены
                try:
                    page.wait_for_selector(
                        'ins.price-block__final-price, [class*="price-block__final-price"]',
                        timeout=6000,
                    )
                except Exception:
                    pass

                resolved_id = self._extract_current_product_id(page)
                if resolved_id:
                    result.current_product_id = resolved_id

                # CDN: загружаем один раз для бренда, продавца, вариантов
                cdn_data: dict = {}
                if result.current_product_id:
                    try:
                        cdn_data = fetch_wb_cdn(int(result.current_product_id))
                    except Exception:
                        pass

                self._fill_prices(page, result)
                self._fill_seller_wb(page, result, cdn_data)

                if not result.seller:
                    try:
                        page.wait_for_timeout(2500)
                    except PlaywrightError:
                        pass
                    self._fill_seller_wb(page, result, cdn_data)

                self._fill_brand_wb(page, result, cdn_data)
                self._fill_product_name_wb(page, result, cdn_data)
                self._fill_sizes(page, result, cdn_data)
                self._fill_colors(page, result, cdn_data)

                missing = []
                if not result.seller:
                    missing.append('seller')
                if not result.price_current:
                    missing.append('price_current')

                if missing:
                    result.parse_status = 'missing_required_fields'
                    result.error = 'Не найдены обязательные поля: ' + ', '.join(missing)
                else:
                    result.parse_status = 'ok'
                    result.error = ''
                return result
            except _TIMEOUT_EXC as exc:
                result.error = f'Timeout: {exc}'
                result.parse_status = 'timeout'
                if self.stop_requested():
                    return result
            except _PLAYWRIGHT_EXC as exc:
                result.error = f'Playwright error: {exc}'
                result.parse_status = 'open_error'
                if self.stop_requested():
                    return result
            except Exception as exc:
                result.error = f'{type(exc).__name__}: {exc}'
                result.parse_status = 'parse_error'
                if self.stop_requested():
                    return result
        return result

    def _is_turnstile_present(self, page: Page) -> bool:
        try:
            return page.locator('iframe[src*="turnstile"]').count() > 0
        except Exception:
            return False

    def _is_wb_captcha_present(self, page: Page) -> bool:
        try:
            text = page.locator('body').inner_text(timeout=2000)
            if 'Подтвердите, что вы не бот' in text:
                try:
                    if page.locator('input[type="range"]').count() > 0:
                        return True
                except Exception:
                    pass
        except Exception:
            pass
        return False

    def _dump_captcha_page(self, page: Page) -> None:
        """Сохраняет скриншот и HTML страницы капчи в logs/debug/ (только если debug_log включён)."""
        if not self.config.get('debug_log', False):
            return

        debug_dir = self.base_dir / 'logs' / 'debug'
        debug_dir.mkdir(parents=True, exist_ok=True)
        ts = stamp_for_filename()

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
            self.log('DEBUG', f'DOM элементы: {dom_info}')
        except Exception as e:
            self.log('DEBUG', f'DOM dump — ошибка: {e}')

        try:
            shot_path = debug_dir / f'captcha_screenshot_{ts}.png'
            page.screenshot(path=str(shot_path), full_page=True)
            self.log('DEBUG', f'Скриншот: {shot_path}')
        except Exception as e:
            self.log('DEBUG', f'Скриншот — ошибка: {e}')

        try:
            html = page.evaluate("""() => {
                const clone = document.body.cloneNode(true);
                clone.querySelectorAll('input[type="hidden"]').forEach(
                    el => el.setAttribute('value', '[STRIPPED]'));
                return clone.innerHTML;
            }""")
            html_path = debug_dir / f'captcha_debug_{ts}.html'
            html_path.write_text(html, encoding='utf-8')
            self.log('DEBUG', f'HTML: {html_path}')
        except Exception as e:
            self.log('DEBUG', f'HTML dump — ошибка: {e}')

    def _solve_wb_slider_captcha(self, page: Page) -> Optional[bool]:
        """Решает WB slider-капчу через сервис антикапчи.

        Возвращает:
            True  — капча решена
            None  — CDN заблокирован прокси, img.image не загрузился (повторять бесполезно)
            False — не решена после всех попыток (CDN работал, но сервис/позиция неверны)
        """
        try:
            self.log('INFO', 'Ожидаем загрузки изображения пазла...')

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
                self._dump_captcha_page(page)
                self.log('WARNING', 'img.image не найден — CDN заблокирован или страница не загрузила пазл')
                return None  # CDN заблокирован — повторять бессмысленно

            img_box = img_loc.bounding_box()
            if not img_box or img_box['width'] < 50 or img_box['height'] < 50:
                self.log('WARNING', f'img.image слишком мало ({img_box}) — CDN блокирует изображения капчи')
                return None  # CDN заблокирован — повторять бессмысленно

            self.log('INFO', f'Пазл найден: {img_box["width"]:.0f}×{img_box["height"]:.0f}px')

            # Ищем кнопку-ползунок один раз — не зависит от попытки решения
            btn_center_x: Optional[float] = None
            y: Optional[float] = None

            for sel in ('#slider', '[id="slider"]', '[id*="slider"]:not(#slider-background)',
                        'button', '[role="button"]', '[class*="slider"]', '[class*="arrow"]',
                        '[class*="handle"]', '[class*="control"]', '[draggable="true"]', '[tabindex]'):
                try:
                    loc = page.locator(sel).first
                    if loc.is_visible(timeout=500):
                        box = loc.bounding_box()
                        if box and 10 < box['width'] < 300 and 10 < box['height'] < 300:
                            btn_center_x = box['x'] + box['width'] / 2
                            y = box['y'] + box['height'] / 2
                            self.log('DEBUG', f'Слайдер найден по {sel}: {box["width"]:.0f}×{box["height"]:.0f}px')
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
                                    id: el.id,
                                    cls: [...el.classList].join('.').substring(0, 80),
                                    cx: Math.round(r.x + r.width / 2),
                                    cy: Math.round(r.y + r.height / 2),
                                    w: Math.round(r.width), h: Math.round(r.height)});
                            }
                        });
                        return res;
                    }""")
                    self.log('DEBUG', f'JS-элементы ниже img.image: {candidates}')
                    if candidates:
                        handles = [c for c in candidates
                                   if c['tag'] not in ('svg', 'path', 'SCRIPT', 'STYLE')
                                   and 20 <= c['w'] <= 150 and 20 <= c['h'] <= 80]
                        pick = min(handles, key=lambda c: c['w'] * c['h']) if handles else \
                               min(candidates, key=lambda c: c['w'] * c['h'])
                        btn_center_x = pick['cx']
                        y = pick['cy']
                        self.log('DEBUG', f'JS-слайдер: {pick}')
                except Exception as e:
                    self.log('DEBUG', f'JS-поиск слайдера — ошибка: {e}')

            if btn_center_x is None:
                btn_center_x = img_box['x'] + 24
                y = img_box['y'] + img_box['height'] + 24
                self.log('WARNING', f'Слайдер не найден, расчётная позиция: ({btn_center_x:.0f}, {y:.0f})')

            initial_handle_x = btn_center_x
            self.log('DEBUG', f'Ручка (начало): cx={btn_center_x:.0f}, img_box_x={img_box["x"]:.0f}')

            # Внешний цикл: повторный запрос к сервису с новым скриншотом
            max_solve_attempts = int(self.parser_cfg.get('captcha_solve_retries', 2))

            for solve_attempt in range(1, max_solve_attempts + 1):
                self.log('INFO', f'Запрос к сервису капчи: попытка {solve_attempt}/{max_solve_attempts}')

                img_bytes = page.screenshot(clip={
                    'x': img_box['x'], 'y': img_box['y'],
                    'width': img_box['width'], 'height': img_box['height'],
                })
                coords = self.captcha_solver.solve_image_coordinates(img_bytes)
                if not coords:
                    self.log('WARNING', f'Попытка {solve_attempt}: сервис не вернул координаты')
                    if solve_attempt < max_solve_attempts:
                        page.wait_for_timeout(3000)
                    continue

                target_x, _ = coords
                self.log('INFO', f'Целевая позиция: x={target_x} (из {img_box["width"]:.0f}px)')

                # Две формулы расчёта экранной позиции для одного набора координат
                target_formulas = [
                    img_box['x'] + target_x,
                    initial_handle_x + target_x,
                ]

                for formula_i, target_x_screen in enumerate(target_formulas):
                    self.log('DEBUG', f'Формула {formula_i+1}: тащим ({btn_center_x:.0f},{y:.0f}) → x={target_x_screen:.0f}')

                    page.mouse.move(btn_center_x, y)
                    page.mouse.down()
                    steps = 30
                    for i in range(1, steps + 1):
                        cur_x = btn_center_x + (target_x_screen - btn_center_x) * i / steps
                        page.mouse.move(cur_x, y + random.uniform(-1.5, 1.5))
                        page.wait_for_timeout(random.randint(15, 45))
                    page.mouse.up()
                    page.wait_for_timeout(2500)

                    if not self._is_wb_captcha_present(page):
                        self.log('INFO', f'Slider-капча решена (попытка {solve_attempt}, формула {formula_i+1})!')
                        self.stats.captcha_solved += 1
                        save_cookies(page.context, self.base_dir, self.profile_name, log=self.log)
                        return True

                    self.log('WARNING', f'Формула {formula_i+1}: позиция неверна (x={target_x_screen:.0f})')
                    # Возвращаем ползунок в исходное положение
                    page.mouse.move(target_x_screen, y)
                    page.mouse.down()
                    steps_back = 15
                    for i in range(1, steps_back + 1):
                        cur_x = target_x_screen - (target_x_screen - btn_center_x) * i / steps_back
                        page.mouse.move(cur_x, y)
                        page.wait_for_timeout(random.randint(10, 30))
                    page.mouse.up()
                    page.wait_for_timeout(500)

                # Обе формулы не сработали — ждём перед следующим запросом к сервису
                if solve_attempt < max_solve_attempts:
                    self.log('WARNING', f'Попытка {solve_attempt} не решена — повторяем запрос к сервису через 3 сек...')
                    page.wait_for_timeout(3000)

            self.log('WARNING', f'Slider-капча не решена после {max_solve_attempts} попыток')
            return False

        except Exception as e:
            self.log('WARNING', f'Ошибка при решении slider-капчи: {e}')
            return False

    def _handle_cloudflare_challenge(self, page: Page) -> None:
        """Обрабатывает ручное ожидание решения капчи (ползунок или другая)."""
        import time
        selectors = [
            '#challenge-form', '#challenge-stage', '.cf-browser-verification',
            'iframe[src*="challenge"]', '#cf-challenge-running',
            'iframe[src*="turnstile"]', '#turnstile-wrapper',
            '.challenge-container', 'div[data-challenge]', 'iframe[title*="Cloudflare"]',
        ]
        time.sleep(1)
        challenge_detected = False
        detected_selector = None
        for selector in selectors:
            try:
                if page.locator(selector).count() > 0:
                    challenge_detected = True
                    detected_selector = selector
                    break
            except Exception:
                continue
        if not challenge_detected:
            return
        timeout = int(self.parser_cfg.get('captcha_timeout_sec', 300))
        self.log('WARNING', '')
        self.log('WARNING', '=' * 50)
        self.log('WARNING', f'⚠️  ОБНАРУЖЕНА КАПЧА (селектор: {detected_selector})')
        self.log('WARNING', '🖱️  ПОЖАЛУЙСТА, ПЕРЕДВИНЬТЕ ПОЛЗУНОК ВРУЧНУЮ В ОКНЕ БРАУЗЕРА!')
        self.log('WARNING', f'⏳  Ожидание решения до {timeout} секунд...')
        self.log('WARNING', '=' * 50)
        self.log('WARNING', '')
        start_time = time.time()
        check_interval = 2
        while time.time() - start_time < timeout:
            if self.stop_requested():
                self.log('WARNING', 'Остановка запрошена пользователем во время ожидания капчи')
                raise Exception('Остановка парсера по требованию')
            try:
                still_present = False
                for selector in selectors:
                    try:
                        if page.locator(selector).count() > 0:
                            still_present = True
                            break
                    except Exception:
                        continue
                if not still_present:
                    self.log('INFO', '✅  Капча успешно пройдена!')
                    time.sleep(3)
                    save_cookies(page.context, self.base_dir, self.profile_name, log=self.log)
                    return
                current_url = page.url
                if re.search(r'/catalog/\d+/', current_url) and 'challenge' not in current_url.lower():
                    self.log('INFO', '✅  Капча пройдена, загружена страница товара')
                    save_cookies(page.context, self.base_dir, self.profile_name, log=self.log)
                    return
            except Exception as e:
                self.log('WARNING', f'Ошибка при проверке капчи: {e}')
            time.sleep(check_interval)
        self.log('ERROR', f'❌  Время ожидания капчи истекло ({timeout} секунд)')
        raise Exception('Капча не была решена вовремя')

    def _extract_current_product_id(self, page) -> str:
        # Из URL /catalog/{nmId}/ — первый и основной источник
        url_id = extract_wb_product_id_from_url(page.url)
        if url_id:
            return url_id
        # Фоллбэк: поле «Артикул» на странице
        try:
            body_text = page.locator('body').inner_text(timeout=1500)
            if 'Артикул:' in body_text:
                tail = body_text.split('Артикул:', 1)[1][:40]
                digits = ''.join(ch for ch in tail if ch.isdigit())
                if digits:
                    return digits
        except PlaywrightError:
            pass
        return ''

    def _fill_prices(self, page, result: ParseResult) -> None:
        current = ''
        original = ''
        wallet = ''
        discount_pct = 0

        # === Новый WB-дизайн (mo-typography) ===

        # Блок цен: первая = кошелёк, последняя = обычная
        try:
            loc = page.locator('span[class*="priceBlockPrice"]')
            if loc.count() > 0:
                text = loc.first.inner_text(timeout=2000)
                prices = [normalize_price(x) for x in re.findall(r'(\d[\d\s ]*)\s*₽', normalize_space(text))]
                prices = [p for p in prices if p]
                if len(prices) >= 2:
                    wallet = prices[0]    # самая низкая — цена с кошельком (красная)
                    current = prices[-1]  # обычная цена (чёрная)
                elif len(prices) == 1:
                    current = prices[0]
        except PlaywrightError:
            pass

        # Цена с WB-кошельком — отдельный селектор (запасной)
        if not wallet:
            for sel in ['[class*="walletPrice"]', '[class*="wallet-price"]', '[class*="priceBlockSmall"]']:
                try:
                    loc = page.locator(sel)
                    if loc.count() > 0:
                        text = loc.first.inner_text(timeout=2000)
                        m = re.search(r'(\d[\d\s ]*)\s*₽', normalize_space(text))
                        if m:
                            wallet = normalize_price(m.group(1))
                            break
                except PlaywrightError:
                    continue

        # Зачёркнутая оригинальная цена
        try:
            loc = page.locator('span[class*="strikethrough"]')
            if loc.count() > 0:
                text = loc.first.inner_text(timeout=2000)
                m = re.search(r'(\d[\d\s ]*)\s*₽', normalize_space(text))
                if m:
                    original = normalize_price(m.group(1))
        except PlaywrightError:
            pass

        # === Fallback: старый WB-дизайн (price-block классы) ===
        if not current:
            texts: list[str] = []
            old_sels = [
                '[class*="price-block"]', '.price-block',
                '[class*="product-page__price"]', '[class*="priceContainer"]',
                'ins.price-block__final-price', '[class*="price-block__final-price"]',
                '[class*="price-block__price"]', 'del.price-block__price',
                '[class*="price-block__old-price"]', '[class*="price-block__discount"]',
                '[class*="finalPrice"]', '[class*="priceDown"]',
            ]
            for selector in old_sels:
                try:
                    locator = page.locator(selector)
                    if locator.count() > 0:
                        texts.append(locator.first.inner_text(timeout=2000))
                except PlaywrightError:
                    continue
            if texts:
                current, original, discount_pct = parse_prices_wb(' '.join(texts))

        # === Последний резерв: body-text ===
        if not current:
            try:
                body = page.locator('body').inner_text(timeout=3000)
                m = re.search(r'(\d[\d\s ]*)\s*₽', normalize_space(body))
                if m:
                    current = normalize_price(m.group(1))
            except Exception:
                pass

        # Если wallet оказалась не меньше обычной — это не кошелёк, сбрасываем
        if wallet and current:
            try:
                if int(wallet) >= int(current):
                    wallet = ''
            except (ValueError, TypeError):
                pass

        # Считаем скидку из цен если не найдена иначе
        if not discount_pct and current and original:
            try:
                c = int(current)
                o = int(original)
                if o > c > 0:
                    discount_pct = round((o - c) / o * 100)
            except (ValueError, ZeroDivisionError):
                pass

        result.price_current = current
        result.price_original = original
        result.price_wallet = wallet
        result.discount_pct = discount_pct

    def _fill_outofstock_seller(self, page: Page, result: ParseResult) -> None:
        selectors = ['[class*="seller-info__name"]', 'a[href*="/seller/"]']
        for sel in selectors:
            try:
                loc = page.locator(sel)
                if loc.count() > 0:
                    text = loc.first.inner_text(timeout=2000).strip()
                    if text:
                        result.seller = text
                        return
            except PlaywrightError:
                continue

    def _geoip_lookup(self, host: str) -> str:
        """Возвращает 'Страна, Регион, Город' для IP/хоста прокси через ip-api.com.
        Результат кешируется — повторный вызов с тем же хостом не делает сетевой запрос."""
        if not host:
            return ''
        if host in self._geo_cache:
            return self._geo_cache[host]
        geo = ''
        try:
            import urllib.request as _urlreq
            url = f'http://ip-api.com/json/{host}?fields=status,country,regionName,city&lang=ru'
            req = _urlreq.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with _urlreq.urlopen(req, timeout=6) as resp:
                data = json.loads(resp.read().decode())
            if data.get('status') == 'success':
                parts = [data.get('country', ''), data.get('regionName', ''), data.get('city', '')]
                geo = ', '.join(p for p in parts if p)
        except Exception as exc:
            self.log('DEBUG', f'GEO-запрос для {host} не удался: {exc}')
        self._geo_cache[host] = geo
        return geo

    def _fill_seller_wb(self, page, result: ParseResult, cdn_data: dict) -> None:
        def _clean(t: str) -> str:
            # inner_text() склеивает имя + рейтинг (Elaria4.9) — обрезаем число в конце
            return re.sub(r'\s*\d[.,]\d\s*$', '', t).strip()

        # Находим ссылку продавца по supplierId — это фильтрует рекламные баннеры
        supplier_id = str((cdn_data.get('sellers') or {}).get('supplierId', ''))
        if supplier_id:
            try:
                loc = page.locator('a[href*="/seller/"][href*="' + supplier_id + '"]')
                if loc.count() > 0:
                    text = _clean(loc.first.inner_text(timeout=2000))
                    if text:
                        result.seller = text
                        return
            except PlaywrightError:
                pass
        # Fallback: общий селектор (может поймать баннер, но лучше чем ничего)
        for sel in ['[class*="seller-info__name"]', 'a[href*="/seller/"]']:
            try:
                loc = page.locator(sel)
                if loc.count() > 0:
                    text = _clean(loc.first.inner_text(timeout=2000))
                    if text:
                        result.seller = text
                        return
            except PlaywrightError:
                continue
        # CDN fallback: supplierName или trademark
        seller = extract_seller_from_cdn(cdn_data)
        if seller:
            result.seller = seller

    def _fill_brand_wb(self, page, result: ParseResult, cdn_data: dict) -> None:
        brand = extract_brand_from_cdn(cdn_data)
        if brand:
            result.brand = brand
            return
        selectors = ['[class*="product-page__brand"]', 'a[href*="/brands/"]']
        for sel in selectors:
            try:
                loc = page.locator(sel)
                if loc.count() > 0:
                    text = loc.first.inner_text(timeout=2000).strip()
                    if text:
                        result.brand = text
                        return
            except PlaywrightError:
                continue

    def _fill_product_name_wb(self, page, result: ParseResult, cdn_data: dict) -> None:
        # WB changed their HTML: h1 now shows rating, not product name.
        # Primary source: imt_name from CDN card.json (already fetched).
        name = extract_product_name_from_cdn(cdn_data)
        if name:
            result.product_name = name
            return
        # HTML fallback — older WB layout
        selectors = ['[class*="product-page__header"]', '[class*="product-page__name"]']
        for sel in selectors:
            try:
                loc = page.locator(sel)
                if loc.count() > 0:
                    text = loc.first.inner_text(timeout=2000).strip()
                    if text and not re.match(r'^\d[,\.]\d$', text):
                        result.product_name = text
                        return
            except PlaywrightError:
                continue

    def _fill_sizes(self, page, result: ParseResult, cdn_data: dict) -> None:
        variants = extract_sizes_from_cdn(cdn_data, result.current_product_id or '')
        if not variants:
            # HTML fallback
            try:
                items = page.locator('[class*="sizes-list__item"]')
                for i in range(min(items.count(), 50)):
                    text = items.nth(i).inner_text(timeout=500).strip()
                    if text:
                        from parsers.wb.models import VariantInfo
                        variants.append(VariantInfo(sku=text, link='', text=text))
            except PlaywrightError:
                pass
        result.count_size = count_unique_texts(variants)
        result.size_variant_map = [
            {'sku': item.sku, 'link': item.link, 'text': item.text, 'active': '1' if item.active else '0'}
            for item in variants
        ]

    def _fill_colors(self, page, result: ParseResult, cdn_data: dict) -> None:
        if result.sold_out == 'Да':
            result.count_color = 0
            result.color_variants = ''
            result.color_variant_ids = []
            return

        color_variants = extract_color_variants_from_cdn(cdn_data, result.current_product_id or '')

        if not color_variants:
            hrefs: list[str] = []
            try:
                hrefs = page.evaluate(
                    "() => [...new Set(Array.from(document.querySelectorAll('a[href*=\"/catalog/\"]'))"
                    ".map(a => a.href).filter(h => /\\/catalog\\/\\d+\\//.test(h)))]"
                )
            except _PLAYWRIGHT_EXC:
                pass
            color_variants = extract_color_variants_from_links(hrefs, result.current_product_id or '')

        result.count_color = count_unique_texts(color_variants)
        result.color_variants = join_variant_texts(color_variants)
        result.color_variant_ids = [item.sku for item in color_variants]

    def _expand_variants(self, result: ParseResult) -> None:
        if result.sold_out == 'Да':
            return

        # WB: size variant = chrt_id, не nmId — в очередь НЕ добавляем
        if self.parser_cfg.get('parse_size_variants', False):
            self.stats.size_variants += result.count_size

        if self.parser_cfg.get('parse_color_variants', False):
            for color_id in result.color_variant_ids:
                relation = self.queue_manager.add_relation(
                    root_input_id=result.root_input_id,
                    parent_product_id=result.current_product_id,
                    current_product_id=color_id,
                    source_type='color_variant',
                )
                if relation:
                    self.output.relation_rows.append(relation.to_row())
                    self.stats.color_variants += 1
                self.queue_manager.add_variant(
                    root_input_id=result.root_input_id,
                    current_product_id=color_id,
                    source_type='color_variant',
                    parent_product_id=result.current_product_id,
                    url_old=build_wb_product_url(color_id),
                )

    @staticmethod
    def rotate_logs(base_dir: Path) -> None:
        """Хранит логи за последние 3 запуска (текущий + 2 предыдущих), удаляет старее 7 дней из debug/."""
        from datetime import date, timedelta
        log_dir = base_dir / 'logs'
        log_dir.mkdir(parents=True, exist_ok=True)

        for stem in ('parser', 'parser_debug'):
            log_file = log_dir / f'{stem}.log'
            for i in range(1, 0, -1):  # только .1→.2, итого 3 файла: .log + .1.log + .2.log
                old_file = log_dir / f'{stem}.{i}.log'
                new_file = log_dir / f'{stem}.{i + 1}.log'
                if old_file.exists():
                    if new_file.exists():
                        new_file.unlink()
                    old_file.rename(new_file)
            if log_file.exists():
                backup = log_dir / f'{stem}.1.log'
                if backup.exists():
                    backup.unlink()
                log_file.rename(backup)
            log_file.write_text('', encoding='utf-8')

        # Удаляем debug-файлы старше 7 дней
        cutoff = date.today() - timedelta(days=7)
        debug_dir = log_dir / 'debug'
        if debug_dir.exists():
            for f in debug_dir.iterdir():
                if not f.is_file():
                    continue
                try:
                    if date.fromtimestamp(f.stat().st_mtime) < cutoff:
                        f.unlink()
                except Exception:
                    pass

    def _save_partial_snapshot(self) -> None:
        try:
            output_dir = self.base_dir / 'output'
            output_dir.mkdir(parents=True, exist_ok=True)
            partial_path = output_dir / f'parsing_partial_{self._partial_stamp}.xlsx'
            spp_pct = int(self.config.get('parser', {}).get('wb_spp_percent', 25))
            export_snapshot(
                self.base_dir, self.output.data_rows,
                error_rows=self.output.error_rows or None,
                fixed_path=partial_path,
                spp_percent=spp_pct,
            )
            self._partial_output_file = str(partial_path)
            self.log('INFO', f'Partial Excel сохранён: {partial_path.name} ({self.stats.processed} товаров)')
        except Exception as exc:
            self.log('WARNING', f'Не удалось сохранить partial Excel: {exc}')

    def _push_stats(self) -> None:
        if self.stats_callback:
            self.stats_callback(self.stats)

    def _file_log(self, level: str, message: str) -> None:
        """Записывает сообщение в файл logs/parser.log (без вывода в GUI)."""
        try:
            log_dir = self.base_dir / 'logs'
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = log_dir / 'parser.log'
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(message + '\n')
        except Exception:
            pass

    def _debug_log(self, message: str) -> None:
        """Записывает полный текст ошибки (с многострочными дампами) в parser_debug.log."""
        try:
            log_dir = self.base_dir / 'logs'
            log_dir.mkdir(parents=True, exist_ok=True)
            with open(log_dir / 'parser_debug.log', 'a', encoding='utf-8') as f:
                f.write(f'[{now_str()}] {message}\n')
        except Exception:
            pass

    @staticmethod
    def _friendly_error(status: str, error: str) -> str:
        """Возвращает понятное описание ошибки для нетехнических пользователей."""
        if status == 'ok':
            return ''
        e = error.lower()
        if status == 'open_error':
            if 'syntaxerror' in e or 'syntax error' in e:
                return 'Ошибка скрипта на странице сайта'
            if 'timeout' in e:
                return 'Страница не загрузилась (тайм-аут)'
            if 'net::err_proxy' in e or ('proxy' in e and 'err' in e):
                return 'Прокси-сервер не отвечает'
            if 'net::err_' in e:
                return 'Сетевая ошибка при загрузке страницы'
            return 'Ошибка при открытии страницы товара'
        _map = {
            'timeout':                'Превышено время ожидания',
            'access_denied':          'Доступ закрыт (сайт блокирует запрос)',
            'captcha':                'Сайт показал капчу',
            '404':                    'Товар не найден на сайте',
            'region_unavailable':     'Товар недоступен в данном регионе',
            'missing_required_fields': 'Неполные данные (не найдены обязательные поля)',
            'parse_error':            'Ошибка разбора данных страницы',
            'redirect_unknown':       'Неожиданный редирект',
            'stopped':                'Обработка остановлена',
        }
        return _map.get(status, f'Неизвестная ошибка (код: {status})')

    def _log_item_result(self, product_id: str, parse_time: float, status: str, error: str = ''):
        proxy_label = getattr(self, '_proxy_label', '') or getattr(self, '_current_proxy_masked', '')
        prefix = f'[{proxy_label}] ' if proxy_label else ''
        if status == 'ok':
            self.log('INFO', f'{prefix}Товар {product_id} обработан за {parse_time:.1f} сек. Статус: OK')
        else:
            friendly = self._friendly_error(status, error)
            self.log('WARNING', f'{prefix}Товар {product_id} обработан за {parse_time:.1f} сек. {friendly}')
            if error:
                self._debug_log(f'{prefix}Товар {product_id} | Статус: {status} | Техническая ошибка:\n{error}')

    def _update_proxy_stats(self, proxy_masked: str, status: str) -> None:
        if not proxy_masked:
            return
        if proxy_masked not in self._proxy_stats:
            self._proxy_stats[proxy_masked] = {
                'ok': 0, 'access_denied': 0, 'timeout': 0,
                'redirect_unknown': 0, 'region_unavailable': 0,
                'missing_required_fields': 0, 'open_error': 0,
                'parse_error': 0, '404': 0, 'stopped': 0, 'other': 0,
            }
        if status in self._proxy_stats[proxy_masked]:
            self._proxy_stats[proxy_masked][status] += 1
        else:
            self._proxy_stats[proxy_masked]['other'] += 1
