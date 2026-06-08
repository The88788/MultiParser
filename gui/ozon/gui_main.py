from __future__ import annotations

import datetime
import html
from pathlib import Path
from urllib.request import urlopen

from PySide6.QtCore import QUrl, QSize, QPropertyAnimation, QEasingCurve, Qt, QEvent, QObject, Signal, QTimer
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QTextCursor
from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QFrame, QGroupBox, QHBoxLayout, QHeaderView,
    QLabel, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton,
    QScrollArea, QStatusBar, QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout,
    QWidget, QTabWidget, QLineEdit,
)

from core.cron_manager import CronManager, validate_cron_conditions
from core.proxy_checker import cleanup_stale_profiles
from parsers.ozon.parser_core import ParserCore
from core.utils import save_config, ensure_runtime_dirs
from core import autostart as _autostart
from parsers.ozon.version import APP_SITE_URL, APP_TELEGRAM_URL, APP_TITLE, APP_VERSION
from gui.cron_widget import CronTab
from gui.notifications_widget import NotificationsTab
from gui.log_handler import LogEmitter
from gui.styles import APP_QSS
from gui.widgets import (
    ParserSettingsGroup, ProxySettingsGroup,
    AntidetectSettingsGroup, CaptchaSettingsGroup
)
from gui.ozon.workers import ParserWorker, ProxyTestWorker
from typing import List, Tuple


class _CronBridge(QObject):
    """Передаёт команды из daemon-потока CronManager в GUI-поток через QueuedConnection."""
    launch_requested = Signal(object, object, object)  # (config, input_ids, valid_proxy_lines)
    log_requested = Signal(str, str)

def build_app_icon(resources_dir: Path) -> QIcon:
    path = resources_dir / 'assets' / 'ozon.ico'
    if path.exists():
        return QIcon(str(path))
    return QIcon()



class MainWindow(QMainWindow):
    def __init__(self, *, base_dir: Path, config: dict, resources_dir: Path | None = None) -> None:
        super().__init__()
        self.base_dir = base_dir
        self.resources_dir = resources_dir if resources_dir is not None else base_dir
        self.config = config
        self.last_output_file = ''
        self._proxy_check_in_progress = False
        self.worker: ParserWorker | None = None
        self.proxy_test_worker: ProxyTestWorker | None = None
        self.log_emitter = LogEmitter()
        self._did_center = False
        self.last_valid_proxy_lines: list[str] = []
        self.last_invalid_proxy_lines: list[str] = []
        self.last_proxy_file_path: str = ''
        self._cron_started_by_cron = False
        self._cron_bridge = _CronBridge()
        self._last_parse_was_multi = False
        self._last_progress_milestone = 0
        self._last_stats_total = 0
        self._stop_requested_once = False
        self._parser_ran_since_proxy_check: bool = False

        self.setWindowTitle(f'{APP_TITLE} {APP_VERSION}')
        self.resize(1100, 700)
        self.setMinimumSize(980, 620)
        self.setStyleSheet(APP_QSS)

        app_icon = build_app_icon(self.base_dir)
        if not app_icon.isNull():
            self.setWindowIcon(app_icon)

        self._build_ui()
        self._connect_signals()
        self._init_cron_manager()

        # Обновляем метки Cron-вкладки каждые 30 сек
        self._cron_ui_timer = QTimer(self)
        self._cron_ui_timer.timeout.connect(self._update_cron_labels)
        self._cron_ui_timer.start(30_000)

    def _svg_icon(self, name: str) -> QIcon:
        return QIcon(str(self.resources_dir / 'assets' / name))

    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        self._top_section = QWidget()
        top_vbox = QVBoxLayout(self._top_section)
        top_vbox.setContentsMargins(0, 0, 0, 0)
        top_vbox.setSpacing(8)

        right_panel = QTabWidget()
        top_vbox.addWidget(right_panel, 2)

        # === Вкладка ID / SKU ===
        input_tab = QWidget()
        input_layout = QVBoxLayout(input_tab)
        input_layout.setContentsMargins(8, 8, 8, 8)
        self.input_edit = QPlainTextEdit()
        self.input_edit.setPlaceholderText('Вставь список ID / SKU, по одному в строке')
        input_layout.addWidget(self.input_edit, 1)

        source_row = QHBoxLayout()
        self.source_input = QLineEdit(self.config.get('source', {}).get('path', ''))
        self.source_input.setPlaceholderText('Путь к txt-файлу или ссылка на txt-файл')
        self.choose_source_button = QPushButton('Выбрать txt-файл')
        source_row.addWidget(self.source_input, 1)
        source_row.addWidget(self.choose_source_button)
        source_hint = QLabel(
            'Подсказка: выберите текстовый файл (Windows блокнот) или вставьте ссылку на файл для загрузки с внешнего сайта.')
        source_hint.setWordWrap(True)
        input_layout.addLayout(source_row)
        input_layout.addWidget(source_hint)

        right_panel.addTab(input_tab, 'ID / SKU')

        parser_tab = QWidget()
        _parser_outer = QVBoxLayout(parser_tab)
        _parser_outer.setContentsMargins(0, 0, 0, 0)
        _parser_scroll = QScrollArea()
        _parser_scroll.setWidgetResizable(True)
        _parser_scroll.setFrameShape(QFrame.Shape.NoFrame)
        _parser_content = QWidget()
        parser_layout = QVBoxLayout(_parser_content)
        parser_layout.setContentsMargins(4, 4, 4, 4)

        self.parser_settings = ParserSettingsGroup(self.config.get('parser', {}))
        parser_layout.addWidget(self.parser_settings)

        self.antidetect_settings = AntidetectSettingsGroup(self.config.get('antidetect', {}))
        parser_layout.addWidget(self.antidetect_settings)

        parser_layout.addStretch(1)
        _parser_scroll.setWidget(_parser_content)
        _parser_outer.addWidget(_parser_scroll)

        right_panel.addTab(parser_tab, 'Парсер')

        anti_tab = QWidget()
        _anti_outer = QVBoxLayout(anti_tab)
        _anti_outer.setContentsMargins(0, 0, 0, 0)
        _anti_scroll = QScrollArea()
        _anti_scroll.setWidgetResizable(True)
        _anti_scroll.setFrameShape(QFrame.Shape.NoFrame)
        _anti_content = QWidget()
        anti_layout = QVBoxLayout(_anti_content)
        anti_layout.setContentsMargins(4, 4, 4, 4)

        self.captcha_settings = CaptchaSettingsGroup(self.config.get('captcha', {}))
        self.proxy_settings = ProxySettingsGroup(self.config.get('proxy', {}))

        trash_icon_path = self.resources_dir / 'assets' / 'trash.ico'
        if trash_icon_path.exists():
            self.proxy_settings.delete_bad_button.setIcon(QIcon(str(trash_icon_path)))
            self.proxy_settings.delete_bad_button.setIconSize(QSize(16, 16))
        else:
            self.proxy_settings.delete_bad_button.setText('×')

        anti_layout.addWidget(self.captcha_settings)
        anti_layout.addWidget(self.proxy_settings)
        anti_layout.addStretch(1)
        _anti_scroll.setWidget(_anti_content)
        _anti_outer.addWidget(_anti_scroll)
        right_panel.addTab(anti_tab, 'Капча / Прокси')

        self.cron_tab = CronTab(self.config.get('cron', {}))
        right_panel.addTab(self.cron_tab, 'Cron')

        self.notifications_tab = NotificationsTab(self.config.get('notifications', {}))
        right_panel.addTab(self.notifications_tab, 'Уведомления')

        stats_tab = QWidget()
        stats_layout = QVBoxLayout(stats_tab)
        stats_group = QGroupBox('Статистика')
        stats_form = QVBoxLayout(stats_group)
        self.stats_labels = {}
        for key, label in [
            ('total_input_ids', 'Всего input ID'),
            ('unique_seed_ids', 'Уникальных к обходу'),
            ('processed', 'Обработано'),
            ('errors', 'Ошибок'),
            ('size_variants', 'Найдено size_variant'),
            ('color_variants', 'Найдено color_variant'),
            ('rows', 'Строк в Excel'),
            ('access_denied', 'Access denied'),
            ('captcha_solved', 'Капч решено'),
        ]:
            widget = QLabel(f'{label}: 0')
            self.stats_labels[key] = widget
            stats_form.addWidget(widget)
        stats_layout.addWidget(stats_group)

        hist_group = QGroupBox('История запусков (последние 20)')
        hist_layout = QVBoxLayout(hist_group)
        hist_layout.setContentsMargins(6, 18, 6, 6)
        self.history_table = QTableWidget(0, 4)
        self.history_table.setHorizontalHeaderLabels(
            ['Дата / время', 'Статус', 'Строк', 'Сообщение']
        )
        hh = self.history_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.history_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.history_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.history_table.verticalHeader().setDefaultSectionSize(22)
        hist_layout.addWidget(self.history_table)
        stats_layout.addWidget(hist_group)

        stats_layout.addStretch(1)
        right_panel.addTab(stats_tab, 'Статистика')

        about_tab = QWidget()
        about_layout = QVBoxLayout(about_tab)
        about_group = QGroupBox('О программе')
        about_group_layout = QVBoxLayout(about_group)
        program_label = QLabel(f'{APP_TITLE} {APP_VERSION}')
        developer_label = QLabel('Разработчик:')
        site_label = QLabel(f'www: <a href="{APP_SITE_URL}">the88788.com</a>')
        tg_label = QLabel(f'tg: <a href="{APP_TELEGRAM_URL}">@The88788</a>')
        site_label.setOpenExternalLinks(True)
        tg_label.setOpenExternalLinks(True)
        about_group_layout.addWidget(program_label)
        about_group_layout.addWidget(developer_label)
        about_group_layout.addWidget(site_label)
        about_group_layout.addWidget(tg_label)
        about_layout.addWidget(about_group)

        autostart_group = QGroupBox('Автозагрузка')
        autostart_layout = QVBoxLayout(autostart_group)
        self.autostart_checkbox = QCheckBox('Запускать при старте Windows')
        self.autostart_checkbox.setChecked(_autostart.is_enabled(APP_TITLE))
        autostart_hint = QLabel(
            'При включении приложение будет автоматически запускаться после перезагрузки компьютера.'
        )
        autostart_hint.setWordWrap(True)
        autostart_layout.addWidget(self.autostart_checkbox)
        autostart_layout.addWidget(autostart_hint)
        about_layout.addWidget(autostart_group)

        about_layout.addStretch(1)
        right_panel.addTab(about_tab, 'О программе')

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.start_button = QPushButton('Запустить')
        self.stop_button = QPushButton('Остановить')
        self.open_excel_button = QPushButton('Открыть Excel')
        self.open_output_button = QPushButton('Открыть папку output')
        buttons.addWidget(self.start_button)
        buttons.addWidget(self.stop_button)
        buttons.addStretch(1)
        buttons.addWidget(self.open_excel_button)
        buttons.addWidget(self.open_output_button)
        top_vbox.addLayout(buttons)

        root.addWidget(self._top_section, 2)

        log_group = QGroupBox('Логи')
        log_layout = QVBoxLayout(log_group)

        log_toolbar = QHBoxLayout()
        self.copy_log_button = QPushButton('Копировать логи')
        self.clear_log_button = QPushButton('Очистить')
        self.debug_log_checkbox = QCheckBox('Debug-лог в файл')
        self.debug_log_checkbox.setChecked(bool(self.config.get('debug_log', False)))
        self.debug_log_checkbox.setToolTip('Записывать DEBUG-сообщения в logs/debug/')
        self.expand_log_button = QPushButton()
        self.expand_log_button.setIcon(self._svg_icon('spin_up.svg'))
        self.expand_log_button.setIconSize(QSize(14, 14))
        self.expand_log_button.setFixedSize(28, 28)
        self.expand_log_button.setToolTip('Развернуть логи на весь экран')
        log_toolbar.addWidget(self.copy_log_button)
        log_toolbar.addWidget(self.clear_log_button)
        log_toolbar.addWidget(self.debug_log_checkbox)
        log_toolbar.addStretch(1)
        log_toolbar.addWidget(self.expand_log_button)
        log_layout.addLayout(log_toolbar)

        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        log_layout.addWidget(self.log_edit)
        root.addWidget(log_group, 1)

        self._scroll_bottom_btn = QPushButton(self.log_edit)
        self._scroll_bottom_btn.setIcon(self._svg_icon('spin_down.svg'))
        self._scroll_bottom_btn.setIconSize(QSize(12, 12))
        self._scroll_bottom_btn.setFixedSize(26, 26)
        self._scroll_bottom_btn.setToolTip('Прокрутить в конец')
        self._scroll_bottom_btn.setProperty('compactIconButton', True)
        self._scroll_bottom_btn.setCursor(Qt.PointingHandCursor)
        self._scroll_bottom_btn.raise_()
        self.log_edit.installEventFilter(self)

        self._log_expanded = False
        self._log_animating = False
        self._log_anim = QPropertyAnimation(self._top_section, b'maximumHeight')
        self._log_anim.setDuration(260)
        self._log_anim.setEasingCurve(QEasingCurve.InOutCubic)
        self._log_anim.finished.connect(self._on_log_anim_finished)

        status = QStatusBar(self)
        self.setStatusBar(status)
        self.statusBar().showMessage('Готово')

    def _fit_window_to_available_screen(self) -> None:
        screen = self.screen()
        if screen is None:
            return

        available = screen.availableGeometry()

        margin_x = 24
        margin_y = 24

        preferred_width = 1100
        preferred_height = 700

        width = min(preferred_width, available.width() - margin_x * 2)
        height = min(preferred_height, available.height() - margin_y * 2)

        width = max(980, width)
        height = max(620, height)

        width = min(width, available.width() - 8)
        height = min(height, available.height() - 8)

        self.resize(width, height)

        frame = self.frameGeometry()
        x = available.left() + (available.width() - frame.width()) // 2
        y = available.top() + (available.height() - frame.height()) // 2

        x = max(available.left(), x)
        y = max(available.top(), y)

        self.move(x, y)

    def _connect_signals(self) -> None:
        self.start_button.clicked.connect(self.start_parsing)
        self.stop_button.clicked.connect(self.stop_parsing)
        self.proxy_settings.check_proxy_button.clicked.connect(self.check_proxy)
        self.proxy_settings.delete_bad_button.clicked.connect(self.delete_bad_proxies)
        self.open_excel_button.clicked.connect(self.open_excel)
        self.open_output_button.clicked.connect(self.open_output_folder)
        self.proxy_settings.choose_file_button.clicked.connect(self.choose_proxy_file)
        self.choose_source_button.clicked.connect(self.choose_source_file)
        self.source_input.editingFinished.connect(self.save_source_path)
        self.log_emitter.log_signal.connect(self.append_log)
        self.captcha_settings.log_message.connect(self.append_log)
        self.log_emitter.stats_signal.connect(self.update_stats)
        self.log_emitter.finished_signal.connect(self.on_finished)
        self.log_emitter.error_signal.connect(self.on_worker_error)
        self.parser_settings.multi_parsing_checkbox.toggled.connect(self.on_multi_parsing_toggled)
        self.copy_log_button.clicked.connect(self.copy_logs)
        self.clear_log_button.clicked.connect(self.log_edit.clear)
        self.debug_log_checkbox.toggled.connect(self._on_debug_log_toggled)
        self.expand_log_button.clicked.connect(self.toggle_log_expand)
        self.log_edit.verticalScrollBar().valueChanged.connect(self._on_log_scroll_changed)
        self._scroll_bottom_btn.clicked.connect(self._scroll_log_to_bottom)
        # Cron-вкладка
        self.cron_tab.activate_btn.clicked.connect(self._on_cron_activate_toggled)
        self.cron_tab.run_now_btn.clicked.connect(self._on_cron_run_now)
        # Вкладка Уведомления
        self.notifications_tab.test_tg_btn.clicked.connect(self._on_notifications_test_tg)
        # Автозагрузка
        self.autostart_checkbox.toggled.connect(self._on_autostart_toggled)
        # Мост: сигнал из daemon-потока → слот в GUI-потоке
        self._cron_bridge.launch_requested.connect(self._start_parsing_from_cron)
        self._cron_bridge.log_requested.connect(self.append_log)
        self.append_log('DATE', datetime.date.today().strftime('%Y-%m-%d'))

    def _on_autostart_toggled(self, checked: bool) -> None:
        try:
            if checked:
                _autostart.enable(APP_TITLE)
            else:
                _autostart.disable(APP_TITLE)
        except Exception as exc:
            self.append_log('ERROR', f'Автозагрузка: {exc}')
            self.autostart_checkbox.blockSignals(True)
            self.autostart_checkbox.setChecked(not checked)
            self.autostart_checkbox.blockSignals(False)

    def on_multi_parsing_toggled(self, checked: bool) -> None:
        if not checked:
            self.parser_settings.threads_spin.setEnabled(False)
            self.parser_settings.threads_spin.setValue(1)
            return
        # Проверяем, что прокси включен и используется файл
        proxy_cfg = self.proxy_settings.to_dict()
        if not proxy_cfg['enabled'] or proxy_cfg['mode'] != 'file':
            QMessageBox.warning(self, APP_TITLE,
                                'Мульти-парсинг требует включенного прокси в режиме файла.\n'
                                'Пожалуйста, настройте прокси-файл во вкладке "Антидетект / Капча / Прокси".')
            self.parser_settings.multi_parsing_checkbox.setChecked(False)
            return
        # Проверяем путь к файлу прокси до запуска проверки
        proxy_file = (proxy_cfg.get('proxy_file') or '').strip()
        if not proxy_file:
            QMessageBox.warning(self, APP_TITLE,
                                'Файл прокси не указан.\n'
                                'Укажите путь к файлу во вкладке "Антидетект / Капча / Прокси".')
            self.parser_settings.multi_parsing_checkbox.setChecked(False)
            return
        proxy_path = Path(proxy_file)
        if not proxy_path.exists():
            QMessageBox.warning(self, APP_TITLE,
                                f'Файл прокси не найден:\n{proxy_file}\n\n'
                                'Обновите путь к файлу во вкладке "Антидетект / Капча / Прокси".\n'
                                '(При переносе программы на другой ПК путь к файлу мог измениться.)')
            self.parser_settings.multi_parsing_checkbox.setChecked(False)
            return
        lines = [ln for ln in proxy_path.read_text(encoding='utf-8', errors='ignore').splitlines() if ln.strip()]
        if not lines:
            QMessageBox.warning(self, APP_TITLE,
                                f'Файл прокси пустой:\n{proxy_file}\n\n'
                                'Добавьте прокси в файл и повторите попытку.')
            self.parser_settings.multi_parsing_checkbox.setChecked(False)
            return
        # Если прокси уже проверены, файл не менялся, парсер не запускался
        # и рабочих прокси больше 3 — повторная проверка не нужна
        proxy_file_same = (
            bool(self.last_proxy_file_path)
            and str(proxy_path.resolve()) == str(Path(self.last_proxy_file_path).resolve())
        )
        if (
            not self._parser_ran_since_proxy_check
            and len(self.last_valid_proxy_lines) > 3
            and proxy_file_same
        ):
            valid_count = len(self.last_valid_proxy_lines)
            self.append_log(
                'INFO',
                f'Прокси уже проверены ({valid_count} рабочих). Повторная проверка не требуется.'
            )
            self._activate_threads_spin()
            return
        # Запускаем проверку прокси
        self.check_proxy()
        # На время проверки делаем спиннер неактивным
        self.parser_settings.threads_spin.setEnabled(False)
        self.parser_settings.threads_spin.setToolTip('Дождитесь завершения проверки proxy...')

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._did_center:
            return
        self._did_center = True
        self._fit_window_to_available_screen()

    def choose_proxy_file(self) -> None:
        proxies_dir = self.base_dir / 'proxies'
        proxies_dir.mkdir(exist_ok=True)
        path, _ = QFileDialog.getOpenFileName(self, 'Выбор файла с прокси', str(proxies_dir), 'Text files (*.txt);;All files (*)')
        if path:
            self.proxy_settings.proxy_file_input.setText(path)

    def choose_source_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            'Выбор txt-файла с ID / SKU',
            str(self.base_dir),
            'Text files (*.txt);;All files (*)'
        )
        if path:
            self.source_input.setText(path)
            self.save_source_path()

    def save_source_path(self) -> None:
        self.config.setdefault('source', {})
        self.config['source']['path'] = self.source_input.text().strip()
        save_config(self.base_dir / 'config_ozon.json', self.config)

    def append_log(self, level: str, message: str) -> None:
        sb = self.log_edit.verticalScrollBar()
        at_bottom = sb.maximum() == 0 or sb.value() >= sb.maximum() - 4
        saved_scroll = sb.value()

        safe_message = html.escape(message).replace('\n', '<br>')
        if level == 'DATE':
            self.log_edit.append(
                f'<span style="color:#000000; font-weight:700;">[DATE] [{safe_message}]</span>'
            )
            if at_bottom:
                sb.setValue(sb.maximum())
            else:
                sb.setValue(saved_scroll)
            return
        if level == 'CRON':
            color = '#6a1b9a'
            weight = '700'
        elif level == 'BALANCE':
            color = '#1565c0'
            weight = '700'
        elif 'Прокси валидна' in message:
            color = '#2e7d32'
            weight = '700'
        elif level == 'ERROR':
            color = '#c62828'
            weight = '700'
        elif level == 'WARNING':
            color = '#ef6c00'
            weight = '600'
        else:
            color = '#1f2933'
            weight = '400'
        self.log_edit.append(
            f'<span style="color:{color}; font-weight:{weight};">[{html.escape(level)}]</span> '
            f'<span style="color:{color}; font-weight:{weight};">{safe_message}</span>'
        )
        if level == 'DEBUG' and self.debug_log_checkbox.isChecked():
            self._write_debug_log(message)
        if at_bottom:
            sb.setValue(sb.maximum())
        else:
            sb.setValue(saved_scroll)
        self.statusBar().showMessage(message.splitlines()[0] if message else '')

    def update_stats(self, payload: dict) -> None:
        for key, value in payload.items():
            if key in self.stats_labels:
                text = self.stats_labels[key].text().split(':', 1)[0]
                self.stats_labels[key].setText(f'{text}: {value}')
        processed = payload.get('processed', 0)
        total = payload.get('total_input_ids', 0)
        if total:
            self._last_stats_total = total
        ntf = self.config.get('notifications', {})
        if ntf.get('enabled', False) and ntf.get('notify_progress', False) and processed > 0:
            interval = int(ntf.get('progress_interval', 1000))
            if interval > 0:
                current_milestone = (processed // interval) * interval
                if current_milestone > 0 and current_milestone > self._last_progress_milestone:
                    self._last_progress_milestone = current_milestone
                    notifier = self._get_notifier()
                    if notifier:
                        notifier.notify_progress(current_milestone, self._last_stats_total or total, interval)

    def _collect_input_ids(self) -> list[str]:
        direct = [line.strip() for line in self.input_edit.toPlainText().splitlines() if line.strip()]
        source_ids = self._load_ids_from_source(self.source_input.text().strip())
        combined = []
        seen = set()
        for item in direct + source_ids:
            if item and item not in seen:
                seen.add(item)
                combined.append(item)
        return combined

    def _load_ids_from_source(self, source: str) -> list[str]:
        if not source:
            return []
        try:
            if source.startswith('http://') or source.startswith('https://'):
                with urlopen(source, timeout=20) as response:
                    content = response.read().decode('utf-8', errors='ignore')
                self.append_log('INFO', f'Загружен внешний txt-файл: {source}')
            else:
                path = Path(source)
                if not path.is_absolute():
                    path = self.base_dir / path
                content = path.read_text(encoding='utf-8', errors='ignore')
                self.append_log('INFO', f'Загружен локальный txt-файл: {path}')
            return [line.strip() for line in content.splitlines() if line.strip()]
        except Exception as exc:
            self.append_log('ERROR', f'Не удалось загрузить источник ID / SKU: {type(exc).__name__}: {exc}')
            return []

    def _build_runtime_config(self) -> dict:
        runtime = dict(self.config)
        runtime['parser'] = self.parser_settings.to_dict()
        runtime['proxy'] = self.proxy_settings.to_dict()
        runtime['antidetect'] = self.antidetect_settings.to_dict()
        runtime['captcha'] = self.captcha_settings.to_dict()
        runtime['source'] = {
            'path': self.source_input.text().strip(),
        }
        runtime['notifications'] = self.notifications_tab.to_dict()
        save_config(self.base_dir / 'config.json', runtime)
        self.config = runtime
        self.cron_manager.config = runtime
        return runtime

    def start_parsing(self) -> None:
        # Если включён мульти-парсинг – проверяем, что всё готово
        if self.parser_settings.multi_parsing_checkbox.isChecked():
            if self._proxy_check_in_progress:
                QMessageBox.warning(self, APP_TITLE,
                                    'Дождитесь завершения проверки proxy перед запуском мульти-парсинга.')
                return
            if not self.parser_settings.threads_spin.isEnabled():
                QMessageBox.warning(self, APP_TITLE,
                                    'Сначала выполните проверку proxy (включите чекбокс "Мульти-парсинг") или отключите для одиночного режима парсинга.')
                return
            if len(self.last_valid_proxy_lines) == 0:
                QMessageBox.warning(self, APP_TITLE,
                                    'Не найдено рабочих прокси. Мульти-парсинг невозможен.')
                return
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, APP_TITLE, 'Парсер уже запущен')
            return
        input_ids = self._collect_input_ids()
        if not input_ids:
            QMessageBox.warning(self, APP_TITLE, 'Добавь хотя бы один product id или укажи txt-файл')
            return
        runtime_config = self._build_runtime_config()
        self._last_parse_was_multi = bool(runtime_config.get('parser', {}).get('multi_parsing_enabled', False))
        self._last_progress_milestone = 0
        self._last_stats_total = 0
        self._stop_requested_once = False
        self.log_edit.clear()
        self.append_log('DATE', datetime.date.today().strftime('%Y-%m-%d'))
        self.append_log('INFO', f'Старт версии {APP_VERSION}')
        self.worker = ParserWorker(base_dir=self.base_dir, config=runtime_config, input_ids=input_ids,
                                   emitter=self.log_emitter, valid_proxy_lines=self.last_valid_proxy_lines)
        self.worker.start()
        self._parser_ran_since_proxy_check = True
        self.statusBar().showMessage('Парсинг запущен')

    def stop_parsing(self) -> None:
        stopped_something = False
        if self.worker and self.worker.isRunning():
            if self._stop_requested_once:
                self.worker.terminate()
                self.append_log('WARNING', 'Принудительная остановка. Данные могут быть частично сохранены.')
            else:
                self.worker.stop()
                self.append_log('WARNING', 'Запрошена остановка после текущей задачи. Повторное нажатие — принудительная остановка.')
                self._stop_requested_once = True
            stopped_something = True
        if self.proxy_test_worker and self.proxy_test_worker.isRunning():
            self.proxy_test_worker.stop()
            self.append_log('WARNING', 'Запрошена остановка проверки прокси после текущей прокси')
            stopped_something = True
        if not stopped_something:
            self.append_log('INFO', 'Сейчас ничего не выполняется')

    def _activate_threads_spin(self) -> None:
        valid_count = len(self.last_valid_proxy_lines)
        if valid_count <= 2:
            max_threads = 1
        elif valid_count <= 5:
            max_threads = 2
        elif valid_count <= 10:
            max_threads = 3
        elif valid_count <= 15:
            max_threads = 4
        elif valid_count <= 20:
            max_threads = 5
        elif valid_count <= 25:
            max_threads = 6
        elif valid_count <= 30:
            max_threads = 7
        elif valid_count <= 35:
            max_threads = 8
        elif valid_count <= 40:
            max_threads = 9
        else:
            max_threads = 10
        self.parser_settings.threads_spin.setMaximum(max_threads)
        self.parser_settings.threads_spin.setValue(max_threads)
        self.parser_settings.threads_spin.setEnabled(True)
        self.parser_settings.threads_spin.setToolTip(f'Доступно потоков: 1–{max_threads}')

    def check_proxy(self) -> None:
        if self.proxy_test_worker and self.proxy_test_worker.isRunning():
            self.append_log('WARNING', 'Проверка proxy уже выполняется')
            return
        runtime_config = self._build_runtime_config()
        self.append_log('INFO', 'Запущена проверка proxy')
        self._proxy_check_in_progress = True
        self.start_button.setEnabled(False)
        self.last_valid_proxy_lines = []
        self.last_invalid_proxy_lines = []
        self.last_proxy_file_path = ''
        self.proxy_settings.delete_bad_button.setEnabled(False)

        self.proxy_test_worker = ProxyTestWorker(
            base_dir=self.base_dir,
            config=runtime_config,
            emitter=self.log_emitter
        )
        self.proxy_test_worker.finished.connect(self.on_proxy_test_finished)
        self.proxy_test_worker.start()

    def on_proxy_test_finished(self) -> None:
        self._proxy_check_in_progress = False
        self._parser_ran_since_proxy_check = False
        self.start_button.setEnabled(True)
        if not self.proxy_test_worker:
            return

        self.last_valid_proxy_lines = list(getattr(self.proxy_test_worker, 'valid_proxy_lines', []))
        self.last_invalid_proxy_lines = list(getattr(self.proxy_test_worker, 'invalid_proxy_lines', []))
        # Обновляем лимит потоков для мульти-парсинга
        if self.parser_settings.multi_parsing_checkbox.isChecked():
            if len(self.last_valid_proxy_lines) == 0:
                self.append_log('WARNING', 'Рабочих proxy не найдено. Мульти-парсинг ограничен 1 потоком.')
            self._activate_threads_spin()
        # Путь к файлу с прокси
        self.last_proxy_file_path = str(getattr(self.proxy_test_worker, 'checked_proxy_file_path', '') or '')

        enable_delete = bool(self.last_proxy_file_path and self.last_invalid_proxy_lines)
        self.proxy_settings.delete_bad_button.setEnabled(enable_delete)

        if enable_delete:
            self.append_log(
                'INFO',
                f'Доступно удаление нерабочих proxy: {len(self.last_invalid_proxy_lines)} шт.'
            )
        else:
            self.append_log('INFO', 'Нерабочие proxy не найдены. Удаление не требуется')

        all_servers = self.last_valid_proxy_lines + self.last_invalid_proxy_lines
        removed = cleanup_stale_profiles(self.base_dir, all_servers)
        if removed:
            self.append_log('INFO', f'Очистка профилей: удалено {removed} устаревших директорий')

        ntf = self.config.get('notifications', {})
        notifier = self._get_notifier()
        valid_count = len(self.last_valid_proxy_lines)
        invalid_count = len(self.last_invalid_proxy_lines)
        if notifier and ntf.get('notify_proxy_check_done', False) and (valid_count > 0 or invalid_count > 0):
            notifier.notify_proxy_check_done(valid_count, invalid_count)

    def delete_bad_proxies(self) -> None:
        if not self.last_proxy_file_path:
            self.append_log('WARNING', 'Файл proxy не выбран или не использовался при последней проверке')
            return

        if not self.last_invalid_proxy_lines:
            self.append_log('INFO', 'Нерабочих proxy для удаления нет')
            self.proxy_settings.delete_bad_button.setEnabled(False)
            return

        proxy_path = Path(self.last_proxy_file_path)
        if not proxy_path.exists():
            self.append_log('ERROR', f'Файл proxy не найден: {proxy_path}')
            return

        tmp_path = proxy_path.with_suffix('.tmp')
        try:
            content = '\n'.join(self.last_valid_proxy_lines)
            if content:
                content += '\n'
            tmp_path.write_text(content, encoding='utf-8')
            tmp_path.replace(proxy_path)

            removed_count = len(self.last_invalid_proxy_lines)
            kept_count = len(self.last_valid_proxy_lines)

            self.append_log(
                'INFO',
                f'Файл proxy пересобран. Оставлено рабочих: {kept_count}. Удалено нерабочих: {removed_count}'
            )

            self.last_invalid_proxy_lines = []
            self.proxy_settings.delete_bad_button.setEnabled(False)
        except Exception as exc:
            tmp_path.unlink(missing_ok=True)
            self.append_log('ERROR', f'Не удалось пересобрать файл proxy: {type(exc).__name__}: {exc}')

    @staticmethod
    def _format_elapsed(seconds: float) -> str:
        s = int(seconds)
        if s < 60:
            return f'{s} сек'
        m, s = divmod(s, 60)
        if m < 60:
            return f'{m} мин {s} сек'
        h, m = divmod(m, 60)
        return f'{h} ч {m} мин {s} сек'

    def on_finished(self, payload: dict) -> None:
        self.last_output_file = payload.get('output_file', '')
        elapsed_str = self._format_elapsed(payload.get('elapsed', 0))
        self.append_log(
            'CRON' if self._cron_started_by_cron else 'INFO',
            f'Готово. Строк: {payload.get("rows", 0)}. '
            f'Ошибок: {payload.get("errors", 0)}. Время: {elapsed_str}'
        )
        self.statusBar().showMessage('Парсинг завершен')

        # Telegram-уведомление о завершении
        ntf = self.config.get('notifications', {})
        notifier = self._get_notifier()
        if notifier:
            if self._cron_started_by_cron:
                if ntf.get('notify_cron_done', True):
                    notifier.notify_cron_done(payload)
            elif self._last_parse_was_multi:
                if ntf.get('notify_multi_done', True):
                    notifier.notify_multi_done(payload)
            else:
                if ntf.get('notify_single_done', True):
                    notifier.notify_single_done(payload)

        if self._cron_started_by_cron:
            self._cron_started_by_cron = False
            self.cron_manager.record_parse_result(payload)
            self._update_cron_history(self.cron_manager.get_history())
            self._update_cron_labels()

    def on_worker_error(self, message: str) -> None:
        self.append_log('ERROR', message)
        self.statusBar().showMessage('Ошибка')
        ntf = self.config.get('notifications', {})
        notifier = self._get_notifier()
        if notifier and ntf.get('notify_error', True):
            notifier.notify_error(message)

    def open_excel(self) -> None:
        if not self.last_output_file:
            QMessageBox.information(self, APP_TITLE, 'Файл Excel еще не создан')
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.last_output_file))

    def open_output_folder(self) -> None:
        path = self.base_dir / 'output'
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def toggle_log_expand(self) -> None:
        if self._log_animating:
            return
        self._log_animating = True
        if not self._log_expanded:
            current_h = self._top_section.height()
            self._top_section.setMaximumHeight(current_h)
            self._log_anim.setStartValue(current_h)
            self._log_anim.setEndValue(0)
            self._log_anim.start()
            self.expand_log_button.setIcon(self._svg_icon('spin_down.svg'))
            self.expand_log_button.setToolTip('Свернуть логи')
            self._log_expanded = True
        else:
            self._log_anim.setStartValue(0)
            self._log_anim.setEndValue(16777215)
            self._log_anim.start()
            self.expand_log_button.setIcon(self._svg_icon('spin_up.svg'))
            self.expand_log_button.setToolTip('Развернуть логи на весь экран')
            self._log_expanded = False

    def _on_log_anim_finished(self) -> None:
        self._log_animating = False

    def eventFilter(self, obj, event) -> bool:
        if obj is self.log_edit and event.type() == QEvent.Type.Resize:
            self._reposition_scroll_btn()
        return super().eventFilter(obj, event)

    def _reposition_scroll_btn(self) -> None:
        btn = self._scroll_bottom_btn
        sb = self.log_edit.verticalScrollBar()
        sb_w = sb.sizeHint().width()  # всегда резервируем место под скроллбар
        margin = 10
        x = self.log_edit.width() - btn.width() - sb_w - margin
        y = self.log_edit.height() - btn.height() - margin
        btn.move(max(0, x), max(0, y))

    def _on_log_scroll_changed(self, value: int) -> None:
        self._reposition_scroll_btn()
        self._scroll_bottom_btn.raise_()

    def _scroll_log_to_bottom(self) -> None:
        sb = self.log_edit.verticalScrollBar()
        sb.setValue(sb.maximum())

    def copy_logs(self) -> None:
        from PySide6.QtGui import QGuiApplication
        text = self.log_edit.toPlainText()
        if text:
            QGuiApplication.clipboard().setText(text)
            self.statusBar().showMessage('Логи скопированы в буфер обмена', 3000)
        else:
            self.statusBar().showMessage('Логи пусты', 2000)

    def _on_debug_log_toggled(self, checked: bool) -> None:
        self.config['debug_log'] = checked
        save_config(self.base_dir / 'config_ozon.json', self.config)

    def _write_debug_log(self, message: str) -> None:
        debug_dir = self.base_dir / 'logs' / 'debug'
        debug_dir.mkdir(parents=True, exist_ok=True)
        log_file = debug_dir / f'debug_{datetime.date.today().strftime("%Y-%m-%d")}.log'
        with log_file.open('a', encoding='utf-8') as f:
            f.write(f'{message}\n')

    def _get_notifier(self):
        """Возвращает TelegramNotifier если уведомления включены, иначе None."""
        ntf = self.config.get('notifications', {})
        if not ntf.get('enabled', False):
            return None
        from core.telegram_notifier import TelegramNotifier
        return TelegramNotifier(
            ntf.get('bot_token', ''), ntf.get('chat_id', ''),
            self.last_valid_proxy_lines, ntf.get('thread_id', ''),
            parser_name='OZON Parser',
        )

    # ------------------------------------------------------------------ #
    #  Cron                                                                #
    # ------------------------------------------------------------------ #

    def _init_cron_manager(self) -> None:
        self.cron_manager = CronManager(
            base_dir=self.base_dir,
            config=self.config,
            get_gui_state=self._get_gui_state_for_cron,
            launch_parser=self._cron_request_launch,
            log=self._cron_bridge.log_requested.emit,
            is_parser_running=lambda: bool(self.worker and self.worker.isRunning()),
            save_config_fn=lambda cfg: save_config(self.base_dir / 'config_ozon.json', cfg),
        )
        # Восстановить активное расписание если было включено при последнем сеансе
        if self.config.get('cron', {}).get('enabled', False):
            self.cron_manager.activate()
            self.cron_tab.set_active(True)
        self._update_cron_labels()
        self._update_cron_history(self.cron_manager.get_history())

    def _get_gui_state_for_cron(self) -> dict:
        """Снимок состояния GUI для CronManager (вызывается из daemon-потока)."""
        return {
            'input_text': self.input_edit.toPlainText(),
            'source_path': self.source_input.text().strip(),
            'runtime_config': dict(self.config),
            'input_ids': self._collect_input_ids(),
            'parser_name': 'OZON Parser',
        }

    def _cron_request_launch(
        self,
        runtime_config: dict,
        input_ids: list,
        valid_proxy_lines: list,
    ) -> None:
        """Вызывается из daemon-потока — эмитирует сигнал в GUI-поток."""
        self._cron_bridge.launch_requested.emit(runtime_config, input_ids, valid_proxy_lines)

    def _start_parsing_from_cron(
        self,
        runtime_config: dict,
        input_ids: list,
        valid_proxy_lines: list,
    ) -> None:
        """Слот, выполняется в GUI-потоке. Запускает ParserWorker от имени Cron."""
        if self.worker and self.worker.isRunning():
            self.append_log('WARNING', 'Парсер уже занят — запуск от планировщика отложен')
            return
        if not input_ids:
            self.append_log('ERROR', 'Нет ID/SKU для парсинга')
            return
        self._cron_started_by_cron = True
        self._last_progress_milestone = 0
        self._last_stats_total = 0
        # Лог не очищаем — пользователь должен видеть результаты проверки прокси
        self.worker = ParserWorker(
            base_dir=self.base_dir,
            config=runtime_config,
            input_ids=input_ids,
            emitter=self.log_emitter,
            valid_proxy_lines=valid_proxy_lines,
        )
        self.worker.start()
        self.statusBar().showMessage('[Cron] Парсинг запущен по расписанию')

    def _on_cron_activate_toggled(self) -> None:
        # Синхронизируем настройки из виджетов в config перед активацией
        cron_settings = self.cron_tab.to_dict()
        cfg = self.config.setdefault('cron', {})
        # Сохраняем поля расписания, не трогая next_run_iso / last_run_iso
        for k, v in cron_settings.items():
            cfg[k] = v
        self.config['notifications'] = self.notifications_tab.to_dict()
        self.cron_manager.config = self.config
        save_config(self.base_dir / 'config_ozon.json', self.config)

        if self.cron_manager.is_active():
            self.cron_manager.deactivate()
            self.cron_tab.set_active(False)
            self.cron_tab.set_validation(True, [])
            self._update_cron_labels()
        else:
            # Валидация перед активацией
            ok, errors = validate_cron_conditions(
                self.config,
                self.input_edit.toPlainText(),
                self.source_input.text().strip(),
            )
            self.cron_tab.set_validation(ok, errors)
            if not ok:
                self.cron_tab.activate_btn.setChecked(False)
                return
            self.cron_manager.activate()
            self.cron_tab.set_active(True)
            self._update_cron_labels()

    def _on_cron_run_now(self) -> None:
        """Немедленный запуск одной Cron-итерации (кнопка «Запустить сейчас»)."""
        cron_settings = self.cron_tab.to_dict()
        cfg = self.config.setdefault('cron', {})
        for k, v in cron_settings.items():
            cfg[k] = v
        self.config['notifications'] = self.notifications_tab.to_dict()
        self.cron_manager.config = self.config
        save_config(self.base_dir / 'config_ozon.json', self.config)

        ok, errors = validate_cron_conditions(
            self.config,
            self.input_edit.toPlainText(),
            self.source_input.text().strip(),
        )
        self.cron_tab.set_validation(ok, errors)
        if not ok:
            return
        self.append_log('CRON', 'Ручной запуск итерации...')
        self.cron_manager.run_now()

    def _on_notifications_test_tg(self) -> None:
        """Тест Telegram-уведомления из вкладки Уведомления."""
        from core.telegram_notifier import TelegramNotifier
        import threading

        token = self.notifications_tab.bot_token_edit.text().strip()
        chat_id = self.notifications_tab.chat_id_edit.text().strip()
        thread_id = self.notifications_tab.thread_id_edit.text().strip()
        self.notifications_tab.test_tg_btn.setEnabled(False)
        self.notifications_tab.test_tg_btn.setText('...')

        proxies = list(self.last_valid_proxy_lines)
        if not proxies:
            proxy_file = self.proxy_settings.proxy_file_input.text().strip()
            if proxy_file:
                try:
                    with open(proxy_file, encoding='utf-8') as _f:
                        proxies = [line.strip() for line in _f if line.strip()]
                except Exception:
                    pass

        def _run() -> None:
            ok, msg = TelegramNotifier(token, chat_id, proxies, thread_id, parser_name='OZON Parser').test()
            self._cron_bridge.log_requested.emit(
                'INFO' if ok else 'ERROR',
                f'[Telegram] {"OK — тестовое сообщение отправлено" if ok else f"Ошибка: {msg}"}',
            )

        def _restore() -> None:
            self.notifications_tab.test_tg_btn.setEnabled(True)
            self.notifications_tab.test_tg_btn.setText('Тест')

        QTimer.singleShot(4000, _restore)
        threading.Thread(target=_run, daemon=True).start()

    def _update_cron_labels(self) -> None:
        self.cron_tab.update_labels(
            self.cron_manager.next_run_time(),
            self.cron_manager.last_run_time(),
        )

    def closeEvent(self, event) -> None:
        # Flush cron tab settings (not flushed by _build_runtime_config)
        cron_settings = self.cron_tab.to_dict()
        cfg = self.config.setdefault('cron', {})
        for k, v in cron_settings.items():
            cfg[k] = v
        # Save all settings (parser, proxy, antidetect, captcha, notifications)
        self._build_runtime_config()
        super().closeEvent(event)

    def _update_cron_history(self, history: list[dict]) -> None:
        _STATUS = {
            'success': ('Успех',    '#2e7d32'),
            'error':   ('Ошибка',   '#c62828'),
            'skipped': ('Пропущен', '#ef6c00'),
        }
        self.history_table.setRowCount(0)
        for entry in reversed(history):
            row = self.history_table.rowCount()
            self.history_table.insertRow(row)
            ts = entry.get('timestamp', '')
            try:
                ts_str = datetime.datetime.fromisoformat(ts).strftime('%d.%m.%Y %H:%M')
            except Exception:
                ts_str = ts
            status_key = entry.get('status', '')
            label, color = _STATUS.get(status_key, (status_key, '#1f2933'))
            for col, text in enumerate([
                ts_str,
                label,
                str(entry.get('rows', '') or ''),
                entry.get('message', ''),
            ]):
                item = QTableWidgetItem(text)
                item.setForeground(QColor(color if col == 1 else '#1f2933'))
                self.history_table.setItem(row, col, item)
