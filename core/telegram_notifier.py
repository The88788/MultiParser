from __future__ import annotations

import queue
import threading
import time
from pathlib import Path
from typing import Callable


def _normalize_proxy(p: str) -> str:
    p = p.strip()
    if p and '://' not in p:
        p = 'http://' + p
    return p


class TelegramNotifier:
    """Отправляет уведомления через Telegram Bot API через очередь с единым воркером."""

    _RATE_DELAY = 1.1  # Telegram ограничивает ~1 msg/сек на чат

    def __init__(
        self,
        token: str,
        chat_id: str,
        proxies: list[str] | None = None,
        thread_id: str | int | None = None,
        parser_name: str = 'Parser',
    ) -> None:
        self.token = (token or '').strip()
        self.chat_id = (chat_id or '').strip()
        self.proxies: list[str] = list(proxies) if proxies else []
        _tid = str(thread_id).strip() if thread_id is not None else ''
        self.thread_id: int | None = int(_tid) if _tid.lstrip('-').isdigit() else None
        self.parser_name = parser_name or 'Parser'

        self._queue: queue.Queue = queue.Queue()
        self._worker: threading.Thread | None = None
        self._lock = threading.Lock()

    def _ready(self) -> bool:
        return bool(self.token and self.chat_id)

    def _post_sync(self, text: str, proxy: str = '') -> tuple[bool, str, float]:
        """Возвращает (ok, msg, retry_after_seconds)."""
        import requests
        url = f'https://api.telegram.org/bot{self.token}/sendMessage'
        proxies = {'https': proxy, 'http': proxy} if proxy else {}
        payload: dict = {'chat_id': self.chat_id, 'text': text, 'parse_mode': 'HTML'}
        if self.thread_id is not None:
            payload['message_thread_id'] = self.thread_id
        try:
            r = requests.post(url, json=payload, timeout=(5, 15), proxies=proxies)
            data = r.json()
            if data.get('ok'):
                return True, 'OK', 0.0
            retry_after = 0.0
            if r.status_code == 429:
                retry_after = float(data.get('parameters', {}).get('retry_after', 5))
            return False, data.get('description', 'Неизвестная ошибка'), retry_after
        except Exception as exc:
            return False, str(exc), 0.0

    def _post_with_retry(
        self, text: str, max_retries: int = 3, retry_delay: float = 3.0
    ) -> tuple[bool, str]:
        last_msg = ''
        if self.proxies:
            # Dedicated proxy configured — use it directly, skip no-proxy attempts
            for proxy in self.proxies[:5]:
                for attempt in range(max_retries):
                    ok, msg, retry_after = self._post_sync(text, proxy)
                    if ok:
                        return True, 'OK'
                    last_msg = msg
                    if retry_after > 0:
                        time.sleep(retry_after + 0.5)
                    elif attempt < max_retries - 1:
                        time.sleep(retry_delay)
            return False, last_msg
        # No proxy — single attempt (connect timeouts won't improve on retry)
        ok, msg, retry_after = self._post_sync(text)
        if ok:
            return True, 'OK'
        if retry_after > 0:
            time.sleep(retry_after + 0.5)
            ok, msg, _ = self._post_sync(text)
            if ok:
                return True, 'OK'
        return False, msg

    def _ensure_worker(self) -> None:
        with self._lock:
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(
                    target=self._worker_loop, daemon=False, name='tg-notifier'
                )
                self._worker.start()

    def _worker_loop(self) -> None:
        import logging as _logging
        log = _logging.getLogger(__name__)
        last_send = 0.0

        while True:
            try:
                item = self._queue.get(timeout=5.0)
            except queue.Empty:
                break  # Нет сообщений 5 сек — воркер завершается

            if item is None:  # sentinel для явной остановки
                self._queue.task_done()
                break

            text, callback = item

            # Соблюдаем паузу между отправками
            elapsed = time.monotonic() - last_send
            if elapsed < self._RATE_DELAY:
                time.sleep(self._RATE_DELAY - elapsed)

            ok, msg = self._post_with_retry(text)
            last_send = time.monotonic()

            if not ok:
                hint = ''
                if self.thread_id is None and self.chat_id.startswith('-100'):
                    hint = (
                        ' Если группа использует темы (Topics), '
                        'укажите Thread ID в настройках уведомлений.'
                    )
                log.warning(
                    '[TELEGRAM ERROR] Не удалось отправить: %s%s', msg, hint
                )

            if callback:
                callback(ok, msg)

            self._queue.task_done()

    def send(
        self,
        text: str,
        callback: Callable[[bool, str], None] | None = None,
        daemon: bool = True,  # параметр сохранён для совместимости, воркер сам non-daemon
    ) -> None:
        if not self._ready():
            return
        self._ensure_worker()
        self._queue.put((text, callback))

    def test(self) -> tuple[bool, str]:
        """Синхронная проверка — вызывать только из не-GUI потока или через QThread."""
        if not self._ready():
            return False, 'Токен бота или ID чата/группы не заполнены'
        test_text = f'🤖 <b>{self.parser_name}</b> — тест уведомлений работает.'
        ok, msg = self._post_with_retry(test_text)
        return ok, msg

    def notify_proxy_low(self, count: int) -> None:
        self.send(
            f'⚠️ <b>{self.parser_name}</b>\n'
            f'Осталось прокси: <b>{count} шт.</b>\n'
            f'Пополните список прокси!'
        )

    def notify_proxy_empty(self) -> None:
        self.send(
            f'🚫 <b>{self.parser_name}</b>\n'
            'Прокси закончились!\n'
            'Запуск по расписанию пропущен. Добавьте рабочие прокси.'
        )

    def notify_parse_done(self, stats: dict) -> None:
        rows = stats.get('rows', 0)
        errors = stats.get('errors', 0)
        output_file = stats.get('output_file', '')
        filename = Path(output_file).name if output_file else ''
        self.send(
            f'✅ <b>{self.parser_name}</b> — Парсинг завершён\n'
            f'Строк в Excel: <b>{rows}</b>\n'
            f'Ошибок: <b>{errors}</b>'
            + (f'\nФайл: {filename}' if filename else '')
        )

    def notify_error(self, message: str) -> None:
        short = message[:400] if len(message) > 400 else message
        self.send(f'❌ <b>{self.parser_name}</b> — Ошибка\n{short}')

    # ------------------------------------------------------------------ #
    #  Режимные уведомления о завершении                                   #
    # ------------------------------------------------------------------ #

    def _notify_done_labeled(self, stats: dict, label: str) -> None:
        rows = stats.get('rows', 0)
        errors = stats.get('errors', 0)
        output_file = stats.get('output_file', '')
        elapsed = stats.get('elapsed', 0)
        filename = Path(output_file).name if output_file else ''
        lines = [
            f'✅ <b>{self.parser_name}</b> — {label}',
            f'Строк в Excel: <b>{rows}</b>',
            f'Ошибок: <b>{errors}</b>',
        ]
        if elapsed:
            s = int(elapsed)
            m, s = divmod(s, 60)
            if m:
                lines.append(f'Время: <b>{m} мин {s} сек</b>')
            else:
                lines.append(f'Время: <b>{s} сек</b>')
        if filename:
            lines.append(f'Файл: {filename}')
        self.send('\n'.join(lines))

    def notify_cron_start(
        self,
        ids_count: int,
        valid_proxies: int,
        deleted_proxies: int,
        threads: int,
        mode_label: str,
    ) -> None:
        lines = [
            f'🚀 <b>{self.parser_name}</b> — {mode_label} запуск',
            f'ID на парсинг: <b>{ids_count}</b>',
        ]
        if valid_proxies > 0:
            lines.append(f'Прокси рабочих: <b>{valid_proxies}</b>')
        if deleted_proxies > 0:
            lines.append(f'Прокси удалено: <b>{deleted_proxies}</b>')
        if threads > 1:
            lines.append(f'Потоков: <b>{threads}</b>')
        self.send('\n'.join(lines))

    def notify_single_done(self, stats: dict) -> None:
        self._notify_done_labeled(stats, 'Одиночный парсинг завершён')

    def notify_multi_done(self, stats: dict) -> None:
        self._notify_done_labeled(stats, 'Мульти-парсинг завершён')

    def notify_cron_done(self, stats: dict) -> None:
        self._notify_done_labeled(stats, 'Cron: парсинг завершён')

    def notify_proxy_check_done(self, valid: int, invalid: int) -> None:
        self.send(
            f'🔍 <b>{self.parser_name}</b> — Проверка прокси завершена\n'
            f'Рабочих: <b>{valid}</b>\n'
            f'Нерабочих: <b>{invalid}</b>'
        )

    def notify_proxy_status_after_cron(self, valid_count: int) -> None:
        if valid_count > 10:
            emoji = '🟢'
            status = 'достаточно'
        elif valid_count >= 5:
            emoji = '🟡'
            status = 'мало — пополните список'
        else:
            emoji = '🔴'
            status = 'критично — срочно пополните!'
        self.send(
            f'{emoji} <b>{self.parser_name}</b> — Прокси после сбора\n'
            f'Рабочих прокси: <b>{valid_count}</b>\n'
            f'Статус: {status}'
        )

    def notify_startup(
        self,
        cron_active: bool,
        next_run: 'datetime | None',
        version: str = '',
    ) -> None:
        from datetime import datetime
        now = datetime.now().strftime('%d.%m.%Y %H:%M')
        title = f'{self.parser_name}' + (f' {version}' if version else '')
        lines = [f'🟢 <b>{title}</b> — приложение запущено\n{now}']
        if cron_active and next_run:
            lines.append(
                f'📅 Расписание: активно\n'
                f'Следующий запуск: <b>{next_run.strftime("%d.%m.%Y %H:%M")}</b>'
            )
        elif cron_active:
            lines.append('📅 Расписание: активно')
        else:
            lines.append('📅 Расписание: выключено')
        self.send('\n'.join(lines))

    def notify_progress(self, processed: int, total: int, interval: int) -> None:
        self.send(
            f'📊 <b>{self.parser_name}</b> — Прогресс парсинга\n'
            f'Обработано: <b>{processed}</b> из <b>{total}</b> ID'
            + (f'\n(каждые {interval} ID)' if interval else '')
        )
