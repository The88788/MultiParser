from __future__ import annotations

import calendar
import json
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable


def validate_cron_conditions(
    config: dict,
    input_text: str,
    source_path: str,
) -> tuple[bool, list[str]]:
    """
    Проверяет выполнение условий для активации Cron-задачи.
    Возвращает (ok, список_ошибок).
    """
    errors: list[str] = []

    # --- ID/SKU ---
    has_direct = bool(input_text.strip())
    has_source = False
    sp = (source_path or '').strip()
    if sp:
        if sp.startswith('http://') or sp.startswith('https://'):
            has_source = True
        else:
            has_source = Path(sp).is_file()
    if not has_direct and not has_source:
        errors.append('Нет ID/SKU: вставьте список или укажите файл/ссылку')

    # --- Прокси ---
    proxy_cfg = config.get('proxy', {})
    proxy_enabled = proxy_cfg.get('enabled', False)
    multi_mode = config.get('parser', {}).get('multi_parsing_enabled', False)

    if proxy_enabled or multi_mode:
        mode = proxy_cfg.get('mode', 'file')
        proxy_file = (proxy_cfg.get('proxy_file') or '').strip()

        if multi_mode:
            # Мульти-режим требует файл с прокси; если прокси < 5 — запустится в одиночном режиме
            if not proxy_file:
                errors.append(
                    'Для работы в мульти-режиме укажите файл с прокси '
                    'во вкладке «Капча / Прокси»'
                )
            elif not Path(proxy_file).is_file():
                errors.append(f'Файл прокси не найден: {proxy_file}')
        elif mode == 'file':
            if not proxy_file:
                errors.append('Укажите файл с прокси во вкладке «Капча / Прокси»')
            elif not Path(proxy_file).is_file():
                errors.append(f'Файл прокси не найден: {proxy_file}')
        else:
            single = (proxy_cfg.get('single_proxy') or '').strip()
            if not single:
                errors.append('Укажите строку прокси во вкладке «Капча / Прокси»')

    return len(errors) == 0, errors


class CronManager:
    """
    Планировщик автозапуска парсера по расписанию.

    config['cron'] поля:
        mode: "daily" | "weekly" | "monthly" | "interval"
        time: "HH:MM"
        weekday: 0–6 (0=пн)
        day_of_month: 1–31
        interval_days: int
        interval_hours: int
        skip_weekends: bool
        check_proxies_before_run: bool
        delete_invalid_proxies: bool
        proxy_low_threshold: int
        skip_or_wait: "skip" | "wait"
        telegram: { enabled, bot_token, chat_id, notify_proxy_low, notify_done, notify_error }
    """

    def __init__(
        self,
        *,
        base_dir: Path,
        config: dict,
        get_gui_state: Callable[[], dict],
        launch_parser: Callable[[dict, list[str], list[str]], None],
        log: Callable[[str, str], None],
        is_parser_running: Callable[[], bool],
        save_config_fn: Callable[[dict], None],
        history_filename: str = 'cron_history.json',
        proxy_checker_class=None,
    ) -> None:
        self.base_dir = base_dir
        self.config = config
        self.get_gui_state = get_gui_state
        self.launch_parser = launch_parser
        self.log = log
        self.is_parser_running = is_parser_running
        self.save_config_fn = save_config_fn
        self._proxy_checker_class = proxy_checker_class

        self._timer: threading.Timer | None = None
        self._active = False
        self._lock = threading.Lock()
        self._history_file = base_dir / 'logs' / history_filename
        self._iteration_running = False
        self._stop_iteration_flag = False

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def activate(self) -> None:
        with self._lock:
            if self._active:
                return
            self._active = True
        self._save_enabled(True)
        self._schedule_next()
        self.log('CRON', 'Планировщик активирован')

    def deactivate(self) -> None:
        with self._lock:
            self._active = False
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
        self._save_enabled(False)
        cron_cfg = self.config.setdefault('cron', {})
        cron_cfg['next_run_iso'] = None
        self.save_config_fn(self.config)
        self.log('CRON', 'Планировщик деактивирован')

    def is_active(self) -> bool:
        return self._active

    def next_run_time(self) -> datetime | None:
        iso = self.config.get('cron', {}).get('next_run_iso')
        if iso:
            try:
                return datetime.fromisoformat(iso)
            except Exception:
                pass
        return None

    def last_run_time(self) -> datetime | None:
        iso = self.config.get('cron', {}).get('last_run_iso')
        if iso:
            try:
                return datetime.fromisoformat(iso)
            except Exception:
                pass
        return None

    def get_history(self) -> list[dict]:
        if not self._history_file.exists():
            return []
        try:
            return json.loads(self._history_file.read_text(encoding='utf-8'))
        except Exception:
            return []

    def run_now(self) -> None:
        """Немедленная одна итерация (кнопка «Запустить сейчас»)."""
        threading.Thread(target=self._run_iteration, daemon=True).start()

    def is_iteration_running(self) -> bool:
        return self._iteration_running

    def stop_iteration(self) -> None:
        self._stop_iteration_flag = True

    def record_parse_result(self, payload: dict) -> None:
        """Вызывается из GUI-потока после завершения парсера запущенного cron-ом."""
        rows = payload.get('rows', 0)
        errors_count = payload.get('errors', 0)
        self._record_history('success', rows=rows, errors=errors_count)

    # ------------------------------------------------------------------ #
    #  Scheduling                                                          #
    # ------------------------------------------------------------------ #

    def _schedule_next(self) -> None:
        now = datetime.now()
        next_dt = self._calc_next_run(now)
        delay = max(1.0, (next_dt - now).total_seconds())

        cron_cfg = self.config.setdefault('cron', {})
        cron_cfg['next_run_iso'] = next_dt.isoformat()
        self.save_config_fn(self.config)

        self.log('CRON', f'Следующий автозапуск парсера: {next_dt.strftime("%d.%m.%Y %H:%M")}')

        self._timer = threading.Timer(delay, self._on_trigger)
        self._timer.daemon = True
        self._timer.start()

    def _calc_next_run(self, after: datetime) -> datetime:
        cron_cfg = self.config.get('cron', {})
        mode = cron_cfg.get('mode', 'daily')
        skip_weekends = cron_cfg.get('skip_weekends', False)

        if mode == 'interval':
            days = max(0, int(cron_cfg.get('interval_days', 0)))
            hours = max(0, int(cron_cfg.get('interval_hours', 1)))
            delta = timedelta(days=days, hours=hours)
            if delta.total_seconds() <= 0:
                delta = timedelta(hours=1)
            candidate = after + delta
        else:
            time_str = cron_cfg.get('time', '09:00')
            try:
                h, m = map(int, time_str.split(':'))
            except Exception:
                h, m = 9, 0
            h = max(0, min(23, h))
            m = max(0, min(59, m))

            candidate = after.replace(hour=h, minute=m, second=0, microsecond=0)
            if candidate <= after:
                candidate += timedelta(days=1)

            if mode == 'weekly':
                target_wd = int(cron_cfg.get('weekday', 0)) % 7
                while candidate.weekday() != target_wd:
                    candidate += timedelta(days=1)

            elif mode == 'monthly':
                target_day = max(1, min(31, int(cron_cfg.get('day_of_month', 1))))
                year, month = after.year, after.month
                last_day = calendar.monthrange(year, month)[1]
                candidate = after.replace(
                    year=year, month=month,
                    day=min(target_day, last_day),
                    hour=h, minute=m, second=0, microsecond=0,
                )
                if candidate <= after:
                    month = month % 12 + 1
                    year = year + (1 if month == 1 else 0)
                    last_day = calendar.monthrange(year, month)[1]
                    candidate = candidate.replace(
                        year=year, month=month, day=min(target_day, last_day)
                    )

        if skip_weekends:
            candidate = self._advance_past_weekend(candidate)

        return candidate

    @staticmethod
    def _advance_past_weekend(dt: datetime) -> datetime:
        """Сдвигает дату на понедельник, если попадает на субботу (5) или воскресенье (6)."""
        wd = dt.weekday()
        if wd == 5:
            return dt + timedelta(days=2)
        if wd == 6:
            return dt + timedelta(days=1)
        return dt

    def _on_trigger(self) -> None:
        with self._lock:
            if not self._active:
                return
        mode = self.config.get('cron', {}).get('mode', 'daily')
        now_str = datetime.now().strftime('%d.%m.%Y %H:%M')
        if mode == 'interval':
            self.log('CRON', f'Автозапуск парсера по интервалу {now_str}')
        else:
            self.log('CRON', f'{self._mode_label()} автозапуск парсера {now_str}')
        try:
            self._run_iteration()
        except Exception as exc:
            import traceback
            self.log('ERROR', f'Ошибка итерации: {exc}\n{traceback.format_exc()}')
        finally:
            with self._lock:
                if self._active:
                    self._schedule_next()

    # ------------------------------------------------------------------ #
    #  Iteration                                                           #
    # ------------------------------------------------------------------ #

    def _run_iteration(self) -> None:
        import time as _time
        from core.telegram_notifier import TelegramNotifier

        self._iteration_running = True
        self._stop_iteration_flag = False
        try:
            self._run_iteration_body(_time, TelegramNotifier)
        finally:
            self._iteration_running = False
            self._stop_iteration_flag = False

    def _run_iteration_body(self, _time, TelegramNotifier) -> None:
        # 0. Выходные дни
        if self.config.get('cron', {}).get('skip_weekends', False):
            wd = datetime.now().weekday()
            if wd >= 5:  # 5=суббота, 6=воскресенье
                day_name = 'суббота' if wd == 5 else 'воскресенье'
                self.log('CRON', f'Выходной день ({day_name}) — автозапуск пропущен')
                self._record_history('skipped', message=f'Выходной день ({day_name})')
                return

        # 1. Состояние GUI
        try:
            gui_state = self.get_gui_state()
        except Exception as exc:
            self.log('ERROR', f'Не удалось получить состояние GUI: {exc}')
            self._record_history('error', message=str(exc))
            return

        input_text = gui_state.get('input_text', '')
        source_path = gui_state.get('source_path', '')
        runtime_config = gui_state.get('runtime_config', self.config)
        input_ids = gui_state.get('input_ids', [])

        cron_cfg = runtime_config.get('cron', {})
        ntf_cfg = runtime_config.get('notifications', {})
        tg_on = ntf_cfg.get('enabled', False)
        notifier: TelegramNotifier | None = TelegramNotifier(
            ntf_cfg.get('bot_token', ''), ntf_cfg.get('chat_id', ''),
            thread_id=ntf_cfg.get('thread_id', ''),
            parser_name=gui_state.get('parser_name', 'Parser'),
        ) if tg_on else None

        def _tg_err(msg: str) -> None:
            if notifier and ntf_cfg.get('notify_error', True):
                notifier.notify_error(msg)

        # 2. Валидация
        ok, errs = validate_cron_conditions(runtime_config, input_text, source_path)
        if not ok:
            msg = '; '.join(errs)
            self.log('ERROR', f'Условия не выполнены: {msg}')
            _tg_err(f'Условия не выполнены: {msg}')
            self._record_history('error', message=msg)
            return

        # 3. Парсер занят?
        if self.is_parser_running():
            skip_or_wait = cron_cfg.get('skip_or_wait', 'skip')
            if skip_or_wait == 'skip':
                self.log('WARNING', 'Парсер занят — итерация пропущена')
                self._record_history('skipped', message='Парсер занят')
                return
            self.log('CRON', 'Парсер занят — ожидание (до 30 мин)...')
            deadline = _time.time() + 1800
            while self.is_parser_running() and _time.time() < deadline and not self._stop_iteration_flag:
                _time.sleep(5)
            if self._stop_iteration_flag:
                self.log('CRON', 'Итерация остановлена пользователем')
                return
            if self.is_parser_running():
                self.log('WARNING', 'Парсер занят > 30 мин — итерация пропущена')
                self._record_history('skipped', message='Парсер занят > 30 мин')
                return

        # 4. Проверка прокси
        valid_proxy_lines: list[str] = []
        deleted_count = 0
        proxy_cfg = runtime_config.get('proxy', {})
        proxy_enabled = proxy_cfg.get('enabled', False)
        multi_mode = runtime_config.get('parser', {}).get('multi_parsing_enabled', False)
        check_proxies = cron_cfg.get('check_proxies_before_run', True)
        delete_invalid = cron_cfg.get('delete_invalid_proxies', True)
        proxy_file = ''
        if proxy_cfg.get('mode') == 'file':
            proxy_file = (proxy_cfg.get('proxy_file') or '').strip()

        if (proxy_enabled or multi_mode) and check_proxies and proxy_file:
            self.log('CRON', 'Проверка прокси перед запуском...')
            checker_cls = self._proxy_checker_class
            if checker_cls is None:
                from core.proxy_checker_ozon import OzonProxyChecker
                checker_cls = OzonProxyChecker
            checker = checker_cls(
                base_dir=self.base_dir,
                config=runtime_config,
                log=self.log,
                stop_requested=lambda: not self._active or self._stop_iteration_flag,
            )
            checker.run()
            valid_proxy_lines = checker.valid_proxy_lines
            invalid_lines = checker.invalid_proxy_lines
            self.log('CRON',
                     f'Прокси: рабочих {len(valid_proxy_lines)}, '
                     f'нерабочих {len(invalid_lines)}')
            if notifier:
                notifier.proxies = list(valid_proxy_lines)

            if delete_invalid and invalid_lines:
                pf = Path(proxy_file)
                if pf.exists():
                    try:
                        content = '\n'.join(valid_proxy_lines)
                        if content:
                            content += '\n'
                        tmp = pf.with_suffix('.tmp')
                        tmp.write_text(content, encoding='utf-8')
                        tmp.replace(pf)
                        deleted_count = len(invalid_lines)
                        self.log('CRON', f'Удалено нерабочих прокси: {deleted_count}')
                    except Exception as exc:
                        self.log('ERROR', f'Ошибка обновления файла прокси: {exc}')

            low = int(cron_cfg.get('proxy_low_threshold', 5))
            if len(valid_proxy_lines) == 0:
                self.log('ERROR', 'Нет рабочих прокси — запуск отменён')
                if notifier and ntf_cfg.get('notify_proxy_low', True):
                    notifier.notify_proxy_empty()
                self._record_history('error', message='Нет рабочих прокси')
                return
            if len(valid_proxy_lines) <= low:
                self.log('WARNING', f'Осталось мало прокси: {len(valid_proxy_lines)} шт.')
                if notifier and ntf_cfg.get('notify_proxy_low', True):
                    notifier.notify_proxy_low(len(valid_proxy_lines))

        # 5. Автовыбор количества потоков (мульти-режим)
        auto_threads = 1
        if multi_mode and valid_proxy_lines:
            if len(valid_proxy_lines) < 5:
                # Недостаточно прокси для мульти-режима — запускаем в одиночном режиме
                runtime_config.setdefault('parser', {})['multi_parsing_enabled'] = False
                multi_mode = False
                self.log('WARNING',
                         f'Рабочих прокси < 5 ({len(valid_proxy_lines)} шт.) — '
                         f'запуск в одиночном режиме с ротацией прокси')
            else:
                auto_threads = self._calc_auto_threads(len(valid_proxy_lines))
                runtime_config.setdefault('parser', {})['threads_count'] = auto_threads
                self.log('CRON',
                         f'Мульти-парсинг: {auto_threads} потоков '
                         f'({len(valid_proxy_lines)} рабочих прокси)')

        # 6. TG уведомление о старте
        if notifier:
            notifier.notify_cron_start(
                ids_count=len(input_ids),
                valid_proxies=len(valid_proxy_lines),
                deleted_proxies=deleted_count,
                threads=auto_threads,
                mode_label=self._mode_label(),
            )

        # 7. Запуск парсера
        if self._stop_iteration_flag:
            self.log('CRON', 'Итерация остановлена пользователем')
            return

        cron_cfg['last_run_iso'] = datetime.now().isoformat()
        self.save_config_fn(self.config)

        try:
            self.launch_parser(runtime_config, input_ids, valid_proxy_lines)
        except Exception as exc:
            import traceback
            self.log('ERROR', f'Ошибка запуска: {exc}')
            _tg_err(f'Ошибка запуска парсера: {exc}')
            self._record_history('error', message=str(exc))

    # ------------------------------------------------------------------ #
    #  History                                                             #
    # ------------------------------------------------------------------ #

    def _record_history(
        self,
        status: str,
        *,
        rows: int = 0,
        errors: int = 0,
        message: str = '',
    ) -> None:
        entry = {
            'timestamp': datetime.now().isoformat(),
            'status': status,
            'rows': rows,
            'errors': errors,
            'message': message,
        }
        history = self.get_history()
        history.append(entry)
        history = history[-20:]
        try:
            self._history_file.parent.mkdir(parents=True, exist_ok=True)
            self._history_file.write_text(
                json.dumps(history, ensure_ascii=False, indent=2),
                encoding='utf-8',
            )
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    #  Helpers                                                             #
    # ------------------------------------------------------------------ #

    def _save_enabled(self, value: bool) -> None:
        cron_cfg = self.config.setdefault('cron', {})
        cron_cfg['enabled'] = value
        self.save_config_fn(self.config)

    def _mode_label(self) -> str:
        mode = self.config.get('cron', {}).get('mode', 'daily')
        return {
            'daily': 'Ежедневный',
            'weekly': 'Еженедельный',
            'monthly': 'Ежемесячный',
            'interval': 'по интервалу',
        }.get(mode, 'Ежедневный')

    @staticmethod
    def _calc_auto_threads(valid_count: int) -> int:
        if valid_count <= 2:
            return 1
        if valid_count <= 5:
            return 2
        if valid_count <= 10:
            return 3
        if valid_count <= 15:
            return 4
        if valid_count <= 20:
            return 5
        if valid_count <= 25:
            return 6
        if valid_count <= 30:
            return 7
        if valid_count <= 35:
            return 8
        if valid_count <= 40:
            return 9
        return 10
