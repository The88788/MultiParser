from __future__ import annotations

import os
import tempfile

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QSpinBox, QVBoxLayout, QWidget,
)


class NotificationsTab(QWidget):
    """Вкладка Telegram-уведомлений для всех событий парсера."""

    def __init__(self, ntf_cfg: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()
        self._load_from_config(ntf_cfg)
        self._connect_signals()

    # ------------------------------------------------------------------ #
    #  Build UI                                                            #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        # ── Включить + инструкция ───────────────────────────────────────
        header_row = QHBoxLayout()
        self.enabled_cb = QCheckBox('Включить Telegram-уведомления')
        guide_lbl = QLabel(
            '<a href="guide" style="color:#4aa8d8; font-size:12px; text-decoration:none;">'
            '&#9432; Инструкция по подключению</a>'
        )
        guide_lbl.setTextFormat(Qt.TextFormat.RichText)
        guide_lbl.linkActivated.connect(self._open_tg_guide)
        header_row.addWidget(self.enabled_cb)
        header_row.addStretch()
        header_row.addWidget(guide_lbl)
        root.addLayout(header_row)

        # ── Настройки бота ─────────────────────────────────────────────
        bot_group = QGroupBox('Настройки бота')
        bot_layout = QVBoxLayout(bot_group)
        bot_layout.setSpacing(5)

        token_row = QHBoxLayout()
        token_row.addWidget(QLabel('Токен бота:'))
        self.bot_token_edit = QLineEdit()
        self.bot_token_edit.setPlaceholderText('123456789:AABBccddeeff…')
        self.bot_token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        token_row.addWidget(self.bot_token_edit, 1)
        bot_layout.addLayout(token_row)

        chat_row = QHBoxLayout()
        chat_row.addWidget(QLabel('ID чата/группы:'))
        self.chat_id_edit = QLineEdit()
        self.chat_id_edit.setPlaceholderText('-100123456789 или @username')
        chat_row.addWidget(self.chat_id_edit, 1)
        bot_layout.addLayout(chat_row)

        thread_row = QHBoxLayout()
        thread_lbl = QLabel('Thread ID (Topics):')
        thread_lbl.setToolTip(
            'ID ветки (темы) в группе с включёнными Topics.\n'
            'Оставьте пустым, если группа без тем или нужно отправлять в General.'
        )
        thread_row.addWidget(thread_lbl)
        self.thread_id_edit = QLineEdit()
        self.thread_id_edit.setPlaceholderText('необязательно')
        self.test_tg_btn = QPushButton('Тест')
        self.test_tg_btn.setFixedWidth(60)
        thread_row.addWidget(self.thread_id_edit, 1)
        thread_row.addWidget(self.test_tg_btn)
        bot_layout.addLayout(thread_row)

        proxy_row = QHBoxLayout()
        proxy_lbl = QLabel('Прокси для Telegram:')
        proxy_lbl.setToolTip(
            'Прокси для отправки уведомлений, если Telegram заблокирован на сервере.\n'
            'Формат: http://login:pass@host:port\n'
            'Оставьте пустым для прямого подключения.'
        )
        proxy_row.addWidget(proxy_lbl)
        self.tg_proxy_edit = QLineEdit()
        self.tg_proxy_edit.setPlaceholderText('http://login:pass@host:port  (необязательно)')
        proxy_row.addWidget(self.tg_proxy_edit, 1)
        bot_layout.addLayout(proxy_row)

        root.addWidget(bot_group)

        # ── О каких событиях уведомлять ────────────────────────────────
        events_group = QGroupBox('Уведомлять о')
        events_layout = QVBoxLayout(events_group)
        events_layout.setSpacing(4)

        self.notify_single_done_cb = QCheckBox(
            'Одиночный парсинг — завершение работы'
        )
        self.notify_multi_done_cb = QCheckBox(
            'Мульти-парсинг — завершение работы'
        )
        self.notify_cron_done_cb = QCheckBox(
            'Cron-задачи — результат запуска'
        )
        self.notify_proxy_check_cb = QCheckBox(
            'Проверка прокси — завершение'
        )
        self.notify_error_cb = QCheckBox(
            'Ошибки парсера'
        )
        self.notify_proxy_low_cb = QCheckBox(
            'Низкий остаток прокси (при Cron)'
        )

        events_layout.addWidget(self.notify_single_done_cb)
        events_layout.addWidget(self.notify_multi_done_cb)
        events_layout.addWidget(self.notify_cron_done_cb)
        events_layout.addWidget(self.notify_proxy_check_cb)
        events_layout.addWidget(self.notify_error_cb)
        events_layout.addWidget(self.notify_proxy_low_cb)

        # Промежуточные уведомления
        progress_row = QHBoxLayout()
        self.notify_progress_cb = QCheckBox('Промежуточные — каждые')
        self.progress_interval_spin = QSpinBox()
        self.progress_interval_spin.setRange(100, 100_000)
        self.progress_interval_spin.setValue(1000)
        self.progress_interval_spin.setSingleStep(100)
        self.progress_interval_spin.setFixedWidth(90)
        progress_row.addWidget(self.notify_progress_cb)
        progress_row.addWidget(self.progress_interval_spin)
        progress_row.addWidget(QLabel('ID'))
        progress_row.addStretch()
        events_layout.addLayout(progress_row)

        root.addWidget(events_group)
        root.addStretch()

    # ------------------------------------------------------------------ #
    #  Config                                                              #
    # ------------------------------------------------------------------ #

    def _load_from_config(self, cfg: dict) -> None:
        self.enabled_cb.setChecked(bool(cfg.get('enabled', False)))
        self.bot_token_edit.setText(cfg.get('bot_token', ''))
        self.chat_id_edit.setText(cfg.get('chat_id', ''))
        self.thread_id_edit.setText(str(cfg.get('thread_id', '')))
        self.tg_proxy_edit.setText(cfg.get('tg_proxy', ''))
        self.notify_single_done_cb.setChecked(bool(cfg.get('notify_single_done', True)))
        self.notify_multi_done_cb.setChecked(bool(cfg.get('notify_multi_done', True)))
        self.notify_cron_done_cb.setChecked(bool(cfg.get('notify_cron_done', True)))
        self.notify_proxy_check_cb.setChecked(bool(cfg.get('notify_proxy_check_done', False)))
        self.notify_error_cb.setChecked(bool(cfg.get('notify_error', True)))
        self.notify_proxy_low_cb.setChecked(bool(cfg.get('notify_proxy_low', True)))
        self.notify_progress_cb.setChecked(bool(cfg.get('notify_progress', False)))
        self.progress_interval_spin.setValue(int(cfg.get('progress_interval', 1000)))

    def to_dict(self) -> dict:
        return {
            'enabled': self.enabled_cb.isChecked(),
            'bot_token': self.bot_token_edit.text().strip(),
            'chat_id': self.chat_id_edit.text().strip(),
            'thread_id': self.thread_id_edit.text().strip(),
            'tg_proxy': self.tg_proxy_edit.text().strip(),
            'notify_single_done': self.notify_single_done_cb.isChecked(),
            'notify_multi_done': self.notify_multi_done_cb.isChecked(),
            'notify_cron_done': self.notify_cron_done_cb.isChecked(),
            'notify_proxy_check_done': self.notify_proxy_check_cb.isChecked(),
            'notify_error': self.notify_error_cb.isChecked(),
            'notify_proxy_low': self.notify_proxy_low_cb.isChecked(),
            'notify_progress': self.notify_progress_cb.isChecked(),
            'progress_interval': self.progress_interval_spin.value(),
        }

    # ------------------------------------------------------------------ #
    #  Signals                                                             #
    # ------------------------------------------------------------------ #

    def _connect_signals(self) -> None:
        self.notify_progress_cb.toggled.connect(
            self.progress_interval_spin.setEnabled
        )
        self.progress_interval_spin.setEnabled(self.notify_progress_cb.isChecked())

    def _open_tg_guide(self, _link: str) -> None:
        from gui.tg_guide_template import TG_GUIDE_HTML
        try:
            from parsers.ozon.version import (
                APP_TITLE, APP_VERSION, APP_DEVELOPER, APP_SITE_URL, APP_TELEGRAM_URL,
            )
        except ImportError:
            from parsers.wb.version import (
                APP_TITLE, APP_VERSION, APP_DEVELOPER, APP_SITE_URL, APP_TELEGRAM_URL,
            )
        tg_html = (TG_GUIDE_HTML
                   .replace('{{APP_TITLE}}', APP_TITLE)
                   .replace('{{APP_VERSION}}', APP_VERSION)
                   .replace('{{APP_DEVELOPER}}', APP_DEVELOPER)
                   .replace('{{APP_SITE_URL}}', APP_SITE_URL)
                   .replace('{{APP_TELEGRAM_URL}}', APP_TELEGRAM_URL))
        out_path = os.path.join(tempfile.gettempdir(), 'ozon_parser_tg_guide.html')
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(tg_html)
        QDesktopServices.openUrl(QUrl.fromLocalFile(out_path))
