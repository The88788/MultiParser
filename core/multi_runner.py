# core/multi_runner.py by the88788.com
from __future__ import annotations

import json
import threading
import time
import random
from queue import Queue, Empty
from pathlib import Path
from typing import Callable

from core.browser_utils import get_sync_playwright
from parsers.ozon.models import RunStats, RunOutput, QueueEntry


def _proxy_profile_name(proxy: dict) -> str:
    """Stable filesystem-safe profile name derived from the proxy's server address."""
    server = proxy.get('server', 'unknown')
    for proto in ('socks5://', 'https://', 'http://'):
        if server.startswith(proto):
            server = server[len(proto):]
            break
    safe = ''.join(c if c.isalnum() else '_' for c in server)
    return f'proxy_{safe}'


def _expand_variants_into_queue(
    result,
    task_queue: Queue,
    seen_ids: set,
    seen_lock: threading.Lock,
    config: dict,
    can_add: bool,
) -> tuple[int, int]:
    """Добавляет size/color варианты в общую очередь задач.
    Возвращает (size_added, color_added)."""
    if not can_add or result.sold_out == 'Да':
        return 0, 0
    # Варианты раскрываем только для исходных input-товаров, чтобы не было рекурсии
    if result.source_type != 'input':
        return 0, 0
    parser_cfg = config.get('parser', {})
    size_added = 0
    color_added = 0

    if parser_cfg.get('parse_size_variants', False):
        for item in (result.size_variant_map or []):
            sku = (item.get('sku') or '').strip()
            if not sku or sku == result.current_product_id:
                continue
            with seen_lock:
                if sku in seen_ids:
                    continue
                seen_ids.add(sku)
            task_queue.put(QueueEntry(
                root_input_id=result.root_input_id,
                current_product_id=sku,
                source_type='size_variant',
                parent_product_id=result.current_product_id,
                url_old='',
            ))
            size_added += 1

    if parser_cfg.get('parse_color_variants', False):
        for color_id in (result.color_variant_ids or []):
            color_id = (color_id or '').strip()
            if not color_id or color_id == result.current_product_id:
                continue
            with seen_lock:
                if color_id in seen_ids:
                    continue
                seen_ids.add(color_id)
            task_queue.put(QueueEntry(
                root_input_id=result.root_input_id,
                current_product_id=color_id,
                source_type='color_variant',
                parent_product_id=result.current_product_id,
                url_old='',
            ))
            color_added += 1

    return size_added, color_added


class WorkerThread(threading.Thread):
    def __init__(self, worker_id: int, proxy: dict, config: dict, base_dir: Path,
                 task_queue: Queue, stats: RunStats, log: Callable,
                 stop_event: threading.Event, stats_lock: threading.Lock,
                 seen_ids: set, seen_lock: threading.Lock,
                 shared_data_rows: list | None = None,
                 parser_core_class=None):
        super().__init__()
        self.worker_id = worker_id
        self.proxy = proxy
        self.config = config
        self.base_dir = base_dir
        self.profile_name = _proxy_profile_name(proxy)
        self.task_queue = task_queue
        self.stats = stats
        self.log = log
        self.stop_event = stop_event
        self.local_output = RunOutput()
        self.stats_lock = stats_lock
        self.proxy_stats = {}
        self.seen_ids = seen_ids
        self.seen_lock = seen_lock
        self.shared_data_rows: list = shared_data_rows if shared_data_rows is not None else []
        self.parser_core_class = parser_core_class

    def run(self):
        def thread_log(level, message):
            self.log(level, f'[Поток {self.worker_id}] {message}')

        # Настраиваем конфиг для этого потока: принудительно включаем single-прокси
        cfg = dict(self.config)
        cfg['proxy'] = dict(cfg.get('proxy', {}))
        cfg['proxy']['enabled'] = True
        cfg['proxy']['mode'] = 'single'
        cfg['proxy']['use_single_proxy'] = True
        if 'username' in self.proxy:
            server = self.proxy['server']
            if '://' in server:
                scheme, rest = server.split('://', 1)
                proxy_url = f"{scheme}://{self.proxy['username']}:{self.proxy['password']}@{rest}"
            else:
                proxy_url = f"http://{self.proxy['username']}:{self.proxy['password']}@{server}"
            cfg['proxy']['single_proxy'] = proxy_url
        cfg['proxy']['session'] = f"worker_{self.worker_id}"

        # Загружаем стратегию, зафиксированную при проверке этой прокси
        cfg['antidetect'] = dict(cfg.get('antidetect', {}))
        strategy_file = self.base_dir / 'profiles' / self.profile_name / 'strategy.json'
        if strategy_file.exists():
            try:
                data = json.loads(strategy_file.read_text(encoding='utf-8'))
                saved = data.get('strategy', '')
                if saved:
                    cfg['antidetect']['strategy'] = saved
                    thread_log('INFO', f'Загружена стратегия прокси из профиля: {saved}')
            except Exception:
                pass

        # Разрешаем загрузку куки из сессии проверки прокси
        cfg['parser'] = dict(cfg.get('parser', {}))
        cfg['parser']['disable_shared_cookies'] = False

        parser = self.parser_core_class(
            base_dir=self.base_dir,
            profile_name=self.profile_name,
            config=cfg,
            stop_requested=lambda: self.stop_event.is_set(),
            log=thread_log,
            stats_callback=None
        )

        server = self.proxy.get('server', '')
        masked_proxy = server[:6] + '***' + server[-6:] if len(server) > 12 else server
        parser._proxy_label = f'Proxy:{masked_proxy}'
        parser._current_proxy_masked = masked_proxy

        _strategy = cfg['antidetect'].get('strategy', 'stealth_js')
        _sync_pw = get_sync_playwright(_strategy)

        # Этап 2Б: перезапуск patchright каждые browser_restart_every_n_pages страниц
        browser_restart_n = int(parser.parser_cfg.get('browser_restart_every_n_pages', 800) or 800)
        _items_since_restart = 0

        while not self.stop_event.is_set():
            with _sync_pw() as playwright:
                try:
                    browser, context, page = parser._create_browser_and_page(playwright)
                except Exception as exc:
                    thread_log('ERROR', f'Не удалось создать браузер: {exc}')
                    break

                consecutive_errors = 0
                _need_pw_restart = False

                while not self.stop_event.is_set():
                    try:
                        entry = self.task_queue.get(timeout=1.0)
                    except Empty:
                        continue

                    try:
                        t0 = time.time()
                        result = parser._parse_one(page, entry)
                        elapsed = time.time() - t0
                        result.parse_time = round(elapsed, 2)

                        self.local_output.data_rows.append(result.to_row())
                        if result.parse_status != 'ok':
                            self.local_output.error_rows.append(result.to_row())

                        size_added, color_added = _expand_variants_into_queue(
                            result, self.task_queue, self.seen_ids, self.seen_lock,
                            self.config, not self.stop_event.is_set(),
                        )

                        with self.stats_lock:
                            self.stats.processed += 1
                            self.stats.rows += 1
                            if result.parse_status != 'ok':
                                self.stats.errors += 1
                            if result.parse_status == 'access_denied':
                                self.stats.access_denied += 1
                            self.stats.size_variants += size_added
                            self.stats.color_variants += color_added
                            self.shared_data_rows.append(result.to_row())  # Этап 1: для partial snapshot

                        parser._log_item_result(entry.current_product_id, elapsed, result.parse_status, result.error)
                        parser._update_proxy_stats(masked_proxy, result.parse_status)
                        _items_since_restart += 1

                    except Exception as exc:
                        thread_log('ERROR', f'Необработанное исключение при парсинге {entry.current_product_id}: {exc}')
                    finally:
                        self.task_queue.task_done()

                    if self.stop_event.is_set():
                        break

                    # Перезапуск браузера при серии open_error — браузер мёртв, продолжать бесполезно
                    if result.parse_status == 'open_error':
                        consecutive_errors += 1
                        if consecutive_errors >= 2:
                            thread_log('WARNING',
                                       f'Серия open_error ({consecutive_errors}), перезапускаем браузер')
                            for obj in (context, browser):
                                try:
                                    obj.close()
                                except Exception:
                                    pass
                            try:
                                browser, context, page = parser._create_browser_and_page(playwright)
                                consecutive_errors = 0
                                thread_log('INFO', 'Браузер перезапущен успешно')
                            except Exception as exc:
                                thread_log('ERROR', f'Не удалось перезапустить браузер: {exc}')
                                break
                            continue  # не спим — сразу берём следующую задачу
                    else:
                        consecutive_errors = 0

                    # Этап 2Б: плановый перезапуск patchright после N страниц
                    if browser_restart_n > 0 and _items_since_restart >= browser_restart_n:
                        thread_log('INFO', f'Плановый перезапуск patchright после {_items_since_restart} страниц')
                        _need_pw_restart = True
                        break  # выходим из внутреннего цикла, не прерывая текущую задачу

                    time.sleep(random.uniform(
                        float(parser.parser_cfg.get('pause_min', 1.2)),
                        float(parser.parser_cfg.get('pause_max', 2.8))
                    ))

                for obj in (context, browser):
                    try:
                        obj.close()
                    except Exception:
                        pass
            # end with _sync_pw()

            if _need_pw_restart:
                _items_since_restart = 0
                _need_pw_restart = False
                thread_log('INFO', 'patchright перезапущен, продолжаем парсинг')
                continue  # re-enter with _sync_pw()
            break  # stop_event is set или критическая ошибка

        # Сохраняем статистику прокси, чтобы потом агрегировать в MultiThreadRunner
        self.proxy_stats = getattr(parser, '_proxy_stats', {})


class MultiThreadRunner:
    def __init__(
        self,
        base_dir: Path,
        config: dict,
        log: Callable,
        stats_callback: Callable = None,
        stop_requested: Callable[[], bool] | None = None,
        parser_core_class=None,
        export_fn=None,
    ):
        self.base_dir = base_dir
        self.config = config
        self.log = log
        self.stats_callback = stats_callback
        self.stop_requested = stop_requested or (lambda: False)
        self.parser_core_class = parser_core_class
        self.export_fn = export_fn
        self.stats = RunStats()
        self.output = RunOutput()
        self.stop_event = threading.Event()
        self.stats_lock = threading.Lock()
        self._stop_logged = False
        # Этап 1: partial snapshot
        self._shared_data_rows: list = []
        self._partial_stamp: str = ''
        self._partial_output_file: str = ''
        self._last_snapshot_count: int = 0

    def request_stop(self) -> None:
        self.stop_event.set()

    def _do_partial_snapshot_multi(self) -> None:
        try:
            with self.stats_lock:
                data_copy = list(self._shared_data_rows)
            output_dir = self.base_dir / 'output'
            output_dir.mkdir(parents=True, exist_ok=True)
            partial_path = output_dir / f'parsing_partial_{self._partial_stamp}.xlsx'
            self.export_fn(self.base_dir, data_copy, fixed_path=partial_path)
            self._partial_output_file = str(partial_path)
            self.log('INFO', f'Partial Excel (мульти): {partial_path.name} ({len(data_copy)} строк)')
        except Exception as exc:
            self.log('WARNING', f'Не удалось сохранить partial Excel: {exc}')

    def run(self, input_ids: list[str], proxies: list[dict], threads_count: int) -> RunOutput:
        threads_count = min(threads_count, len(proxies))
        self.log('INFO', f'Запуск многопоточного парсинга: {threads_count} потоков, {len(input_ids)} товаров')

        # Этап 1: очищаем partial-файлы предыдущих запусков
        from core.utils import stamp_for_filename
        _output_dir = self.base_dir / 'output'
        if _output_dir.exists():
            for _pf in _output_dir.glob('parsing_partial_*.xlsx'):
                try:
                    _pf.unlink()
                except Exception:
                    pass
        self._partial_stamp = stamp_for_filename()
        self._last_snapshot_count = 0

        task_queue: Queue = Queue()
        seen_ids: set = set(input_ids)  # дедупликация: input IDs не добавляются повторно как варианты
        seen_lock = threading.Lock()

        for pid in input_ids:
            task_queue.put(QueueEntry(
                root_input_id=pid,
                current_product_id=pid,
                source_type='input',
                parent_product_id='',
                url_old=''
            ))

        self.stats.total_input_ids = len(input_ids)

        workers = []
        for i in range(threads_count):
            proxy = proxies[i % len(proxies)]
            worker = WorkerThread(
                worker_id=i + 1,
                proxy=proxy,
                config=self.config,
                base_dir=self.base_dir,
                task_queue=task_queue,
                stats=self.stats,
                log=self.log,
                stop_event=self.stop_event,
                stats_lock=self.stats_lock,
                seen_ids=seen_ids,
                seen_lock=seen_lock,
                shared_data_rows=self._shared_data_rows,
                parser_core_class=self.parser_core_class,
            )
            workers.append(worker)

        for w in workers:
            w.start()

        # Ждём завершения всех задач включая динамически добавленные варианты.
        # _wait_queue — daemon-поток: при user-stop он зависнет, но не заблокирует выход.
        queue_done = threading.Event()

        def _wait_queue():
            task_queue.join()
            queue_done.set()

        threading.Thread(target=_wait_queue, daemon=True).start()

        _snapshot_interval = int(self.config.get('parser', {}).get('snapshot_interval', 200) or 200)
        while not queue_done.is_set():
            if self.stop_requested() and not self.stop_event.is_set():
                self.stop_event.set()
                if not self._stop_logged:
                    self._stop_logged = True
                    self.log('WARNING', 'Остановка мульти-парсинга запрошена. Ждем завершения текущих задач в потоках')
            if self.stop_event.is_set():
                break
            time.sleep(0.5)
            if self.stats_callback:
                self.stats_callback(self.stats)
            # Этап 1: периодический partial-снимок
            if _snapshot_interval > 0:
                with self.stats_lock:
                    _current_processed = self.stats.processed
                _bucket = _current_processed // _snapshot_interval
                if _current_processed > 0 and _bucket > self._last_snapshot_count:
                    self._last_snapshot_count = _bucket
                    self._do_partial_snapshot_multi()

        if not self.stop_event.is_set():
            self.stop_event.set()

        for w in workers:
            w.join()

        all_data = []
        all_errors = []
        all_proxy_stats = {}
        for w in workers:
            all_data.extend(w.local_output.data_rows)
            all_errors.extend(w.local_output.error_rows)
            for proxy_key, counts in w.proxy_stats.items():
                if proxy_key not in all_proxy_stats:
                    all_proxy_stats[proxy_key] = dict(counts)
                else:
                    for k, v in counts.items():
                        all_proxy_stats[proxy_key][k] = all_proxy_stats[proxy_key].get(k, 0) + v

        if all_proxy_stats:
            self.log('INFO', 'Статистика по прокси (multithread):')
            for proxy, counts in all_proxy_stats.items():
                self.log('INFO', f'  {proxy}: {counts}')

        self.output.data_rows = all_data
        self.output.error_rows = all_errors
        self.output.stats = self.stats

        self.output.output_file = self.export_fn(
            self.base_dir, all_data, [], all_errors
        )
        if self._partial_output_file:
            try:
                Path(self._partial_output_file).unlink(missing_ok=True)
            except Exception:
                pass
            self._partial_output_file = ''
        return self.output
