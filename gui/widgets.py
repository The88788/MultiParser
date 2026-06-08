from __future__ import annotations

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox, QWidget,
    QSizePolicy,
)

def setup_form_layout(layout: QFormLayout) -> None:
    layout.setContentsMargins(14, 12, 14, 12)
    layout.setHorizontalSpacing(12)
    layout.setVerticalSpacing(10)
    layout.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    layout.setFormAlignment(Qt.AlignTop)

class ParserSettingsGroup(QGroupBox):
    def __init__(self, parser_config: dict, parent=None) -> None:
        super().__init__('Настройки парсера', parent)
        layout = QFormLayout(self)
        layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        layout.setHorizontalSpacing(12)
        layout.setVerticalSpacing(8)
        setup_form_layout(layout)

        self.headed_checkbox = QCheckBox('Headed режим')
        self.headed_checkbox.setChecked(bool(parser_config.get('headed', True)))

        self.captcha_timeout_spin = QSpinBox()
        self.captcha_timeout_spin.setRange(30, 1800)
        self.captcha_timeout_spin.setValue(int(parser_config.get('captcha_timeout_sec', 300)))

        self.retry_spin = QSpinBox()
        self.retry_spin.setRange(1, 10)
        self.retry_spin.setValue(int(parser_config.get('retry_count', 3)))

        self.pause_min_spin = QDoubleSpinBox()
        self.pause_min_spin.setRange(0.1, 60.0)
        self.pause_min_spin.setDecimals(1)
        self.pause_min_spin.setValue(float(parser_config.get('pause_min', 1.2)))

        self.pause_max_spin = QDoubleSpinBox()
        self.pause_max_spin.setRange(0.1, 60.0)
        self.pause_max_spin.setDecimals(1)
        self.pause_max_spin.setValue(float(parser_config.get('pause_max', 2.8)))

        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(1000, 180000)
        self.timeout_spin.setValue(int(parser_config.get('timeout_ms', 30000)))

        self.access_denied_spin = QSpinBox()
        self.access_denied_spin.setRange(1, 20)
        self.access_denied_spin.setValue(int(parser_config.get('max_access_denied_streak', 3)))

        self.ozon_bank_discount_spin = QDoubleSpinBox()
        self.ozon_bank_discount_spin.setRange(0.0, 100.0)
        self.ozon_bank_discount_spin.setDecimals(1)
        self.ozon_bank_discount_spin.setSuffix(' %')
        self.ozon_bank_discount_spin.setValue(float(parser_config.get('ozon_bank_discount_percent', 9.4)))
        for spin in (
                self.captcha_timeout_spin,
                self.retry_spin,
                self.pause_min_spin,
                self.pause_max_spin,
                self.timeout_spin,
                self.access_denied_spin,
                self.ozon_bank_discount_spin,
        ):
            spin.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            spin.setMinimumWidth(0)
        self.size_variants_checkbox = QCheckBox('Size variant в очередь')
        self.size_variants_checkbox.setChecked(bool(parser_config.get('parse_size_variants', True)))

        self.color_variants_checkbox = QCheckBox('Color variant в очередь')
        self.color_variants_checkbox.setChecked(bool(parser_config.get('parse_color_variants', True)))

        # --- Мульти-парсинг ---
        self.multi_parsing_checkbox = QCheckBox('Мульти-парсинг')
        self.multi_parsing_checkbox.setChecked(bool(parser_config.get('multi_parsing_enabled', False)))
        self.multi_parsing_checkbox.setToolTip('Включить параллельную обработку несколькими браузерами (только для режима proxy-файл)')

        self.threads_spin = QSpinBox()
        self.threads_spin.setRange(1, 10)
        self.threads_spin.setValue(int(parser_config.get('threads_count', 1) or 1))
        self.threads_spin.setEnabled(False)
        self.threads_spin.setToolTip('Количество потоков (будет обновлено после проверки proxy)')

        # Виджет-строка
        multi_row = QWidget()
        multi_layout = QHBoxLayout(multi_row)
        multi_layout.setContentsMargins(0, 0, 0, 0)
        multi_layout.addWidget(self.multi_parsing_checkbox)
        multi_layout.addWidget(self.threads_spin)
        multi_layout.addStretch(1)
        layout.addRow(multi_row)

        top_checkboxes_row = QWidget()
        top_checkboxes_layout = QHBoxLayout(top_checkboxes_row)
        top_checkboxes_layout.setContentsMargins(0, 0, 0, 0)
        top_checkboxes_layout.setSpacing(12)

        top_checkboxes_layout.addWidget(self.headed_checkbox)
        top_checkboxes_layout.addWidget(self.size_variants_checkbox)
        top_checkboxes_layout.addWidget(self.color_variants_checkbox)
        top_checkboxes_layout.addStretch(1)

        layout.addRow(top_checkboxes_row)
        layout.addRow('Таймаут капчи (сек)', self.captcha_timeout_spin)
        layout.addRow('Retry', self.retry_spin)
        layout.addRow('Pause min', self.pause_min_spin)
        layout.addRow('Pause max', self.pause_max_spin)
        layout.addRow('Timeout ms', self.timeout_spin)
        layout.addRow('Max access_denied', self.access_denied_spin)
        layout.addRow('Скидка Ozon Банка', self.ozon_bank_discount_spin)

    def to_dict(self) -> dict:
        return {
            'headed': self.headed_checkbox.isChecked(),
            'captcha_timeout_sec': self.captcha_timeout_spin.value(),
            'retry_count': self.retry_spin.value(),
            'pause_min': self.pause_min_spin.value(),
            'pause_max': self.pause_max_spin.value(),
            'timeout_ms': self.timeout_spin.value(),
            'max_access_denied_streak': self.access_denied_spin.value(),
            'ozon_bank_discount_percent': self.ozon_bank_discount_spin.value(),
            'snapshot_mode': True,
            'parse_size_variants': self.size_variants_checkbox.isChecked(),
            'parse_color_variants': self.color_variants_checkbox.isChecked(),
            'multi_parsing_enabled': self.multi_parsing_checkbox.isChecked(),
            'threads_count': self.threads_spin.value(),
            'max_pages_per_run': 0,
        }


class ProxySettingsGroup(QGroupBox):
    def __init__(self, proxy_config: dict, parent=None) -> None:
        super().__init__('Прокси', parent)
        form = QFormLayout(self)
        setup_form_layout(form)
        self.enabled_checkbox = QCheckBox('Включить прокси')
        self.enabled_checkbox.setChecked(bool(proxy_config.get('enabled', False)))

        self.single_proxy_input = QLineEdit(proxy_config.get('single_proxy', ''))
        self.single_proxy_input.setPlaceholderText('http://login:pass@host:port или socks5://login:pass@host:port')

        self.proxy_file_input = QLineEdit(proxy_config.get('proxy_file', ''))
        self.proxy_file_input.setPlaceholderText('Путь к txt файлу с прокси')

        self.choose_file_button = QPushButton('Выбрать txt-файл')
        self.open_file_button = QPushButton('Открыть файл')
        self.open_file_button.setToolTip('Открыть файл прокси в текстовом редакторе')
        self.check_proxy_button = QPushButton('Проверить proxy')
        self.delete_bad_button = QPushButton('')
        self.delete_bad_button.setEnabled(False)
        self.delete_bad_button.setToolTip('Удалить нерабочие proxy. Доступно после проверки proxy')
        self.delete_bad_button.setProperty('compactIconButton', True)
        self.delete_bad_button.setFixedSize(28, 28)

        self.cleanup_profiles_button = QPushButton('Очистить профили')
        self.cleanup_profiles_button.setToolTip(
            'Удалить сохранённые профили прокси, которых нет в текущем файле прокси'
        )

        file_row = QWidget()
        file_layout = QHBoxLayout(file_row)
        file_layout.setContentsMargins(0, 0, 0, 0)
        file_layout.setSpacing(6)
        file_layout.addWidget(self.choose_file_button)
        file_layout.addWidget(self.open_file_button)
        file_layout.addWidget(self.check_proxy_button)
        file_layout.addWidget(self.delete_bad_button)
        file_layout.addWidget(self.cleanup_profiles_button)
        file_layout.addStretch(1)

        form.addRow(self.enabled_checkbox)
        form.addRow('Single proxy', self.single_proxy_input)
        form.addRow('Proxy file', self.proxy_file_input)
        form.addRow('', file_row)

        self.open_file_button.clicked.connect(self._open_proxy_file)

    def _open_proxy_file(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        path = self.proxy_file_input.text().strip()
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def to_dict(self) -> dict:
        use_single_proxy = not bool(self.proxy_file_input.text().strip())
        mode = 'single' if use_single_proxy else 'file'
        return {
            'enabled': self.enabled_checkbox.isChecked(),
            'mode': mode,
            'use_single_proxy': use_single_proxy,
            'single_proxy': self.single_proxy_input.text().strip(),
            'proxy_file': self.proxy_file_input.text().strip(),
        }


class AntidetectSettingsGroup(QGroupBox):
    def __init__(self, antidetect_config: dict, parent=None) -> None:
        super().__init__('Антидетект стратегия', parent)
        layout = QFormLayout(self)
        setup_form_layout(layout)

        self.strategy_combo = QComboBox()
        self.strategy_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        for _id, _name in [
            ('stealth_js',   'Стандартная'),
            ('xdriver',      'Расширенная'),
            ('browserforge', 'Профильная'),
            ('patchright',   'Максимальная'),
            ('camoufox',     'Firefox'),
            ('chrome',       'Chrome'),
        ]:
            self.strategy_combo.addItem(_name, userData=_id)
        current = antidetect_config.get('strategy', 'stealth_js')
        for i in range(self.strategy_combo.count()):
            if self.strategy_combo.itemData(i) == current:
                self.strategy_combo.setCurrentIndex(i)
                break

        self.rotate_checkbox = QCheckBox('Случайная стратегия для каждой сессии')
        self.rotate_checkbox.setChecked(bool(antidetect_config.get('rotate', False)))

        layout.addRow(self.strategy_combo)
        layout.addRow(self.rotate_checkbox)

    def to_dict(self) -> dict:
        return {
            'strategy': self.strategy_combo.currentData() or self.strategy_combo.currentText(),
            'rotate': self.rotate_checkbox.isChecked(),
        }

class _BalanceCheckThread(QThread):
    result_ready = Signal(str, str)  # service, result_text

    def __init__(self, service: str, api_key: str, parent=None):
        super().__init__(parent)
        self._service = service
        self._api_key = api_key

    def run(self):
        try:
            import requests as _req
            if self._service == 'Anti-Captcha':
                resp = _req.post(
                    'https://api.anti-captcha.com/getBalance',
                    json={'clientKey': self._api_key},
                    timeout=15,
                ).json()
                if resp.get('errorId') == 0:
                    balance = float(resp.get('balance', 0))
                    self.result_ready.emit(self._service, f'{balance:.2f}')
                else:
                    err = resp.get('errorDescription', str(resp.get('errorCode', 'Неизвестная ошибка')))
                    self.result_ready.emit(self._service, f'Ошибка: {err}')
            else:
                self.result_ready.emit(self._service, 'Проверка баланса не реализована')
        except Exception as e:
            self.result_ready.emit(self._service, f'Ошибка: {type(e).__name__}')


class CaptchaSettingsGroup(QGroupBox):
    log_message = Signal(str, str)

    def __init__(self, captcha_config: dict, parent=None) -> None:
        super().__init__('Решение капчи', parent)
        layout = QFormLayout(self)

        self.available_services = ['CapSolver', '2Captcha', 'Anti-Captcha']

        self.twocaptcha_key = QLineEdit(captcha_config.get('twocaptcha_api_key', ''))
        self.twocaptcha_key.setPlaceholderText('API ключ 2captcha')
        self.twocaptcha_key.setEchoMode(QLineEdit.Password)

        self.capsolver_key = QLineEdit(captcha_config.get('capsolver_api_key', ''))
        self.capsolver_key.setPlaceholderText('API ключ CapSolver')
        self.capsolver_key.setEchoMode(QLineEdit.Password)

        self.anticaptcha_key = QLineEdit(captcha_config.get('anticaptcha_api_key', ''))
        self.anticaptcha_key.setPlaceholderText('API ключ Anti-Captcha')
        self.anticaptcha_key.setEchoMode(QLineEdit.Password)

        self._balance_thread: _BalanceCheckThread | None = None
        self.balance_btn = QPushButton('Проверить баланс')
        self.balance_btn.clicked.connect(lambda: self._check_balance('Anti-Captcha'))

        self.primary_service = QComboBox()
        self.primary_service.addItems(self.available_services)

        primary = captcha_config.get('primary_service', 'capsolver')
        if primary not in self.available_services:
            primary = 'capsolver'
        self.primary_service.setCurrentText(primary)

        self.fallback_service = QComboBox()
        self._sync_fallback_options()

        fallback = captcha_config.get('fallback_service', '2captcha')
        current_fallback_items = [self.fallback_service.itemText(i) for i in range(self.fallback_service.count())]
        if fallback in current_fallback_items:
            self.fallback_service.setCurrentText(fallback)
        elif current_fallback_items:
            self.fallback_service.setCurrentIndex(0)

        self.primary_service.currentTextChanged.connect(self._sync_fallback_options)

        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(30, 600)
        self.timeout_spin.setValue(int(captcha_config.get('timeout', 120)))

        layout.addRow('2Captcha API ключ', self.twocaptcha_key)
        layout.addRow('CapSolver API ключ', self.capsolver_key)
        layout.addRow('Anti-Captcha API ключ', self.anticaptcha_key)
        layout.addRow(self.balance_btn)
        layout.addRow('Основной сервис', self.primary_service)
        layout.addRow('Резервный сервис', self.fallback_service)
        layout.addRow('Таймаут решения (сек)', self.timeout_spin)

    def _sync_fallback_options(self) -> None:
        primary = self.primary_service.currentText().strip()
        current_fallback = self.fallback_service.currentText().strip()

        allowed_fallbacks = [service for service in self.available_services if service != primary]

        self.fallback_service.blockSignals(True)
        self.fallback_service.clear()
        self.fallback_service.addItems(allowed_fallbacks)

        if current_fallback in allowed_fallbacks:
            self.fallback_service.setCurrentText(current_fallback)
        elif allowed_fallbacks:
            self.fallback_service.setCurrentIndex(0)

        self.fallback_service.blockSignals(False)

    def _check_balance(self, service: str) -> None:
        key_map = {
            'Anti-Captcha': self.anticaptcha_key.text().strip(),
            # '2Captcha': self.twocaptcha_key.text().strip(),
            # 'CapSolver': self.capsolver_key.text().strip(),
        }
        key = key_map.get(service, '')
        if not key:
            self.log_message.emit('WARNING', f'{service}: ключ не указан')
            return
        self.balance_btn.setEnabled(False)
        self._balance_thread = _BalanceCheckThread(service, key, self)
        self._balance_thread.result_ready.connect(self._on_balance_result)
        self._balance_thread.start()

    def _on_balance_result(self, service: str, text: str) -> None:
        self.log_message.emit('BALANCE', f'{service} баланс: {text}')
        self.balance_btn.setEnabled(True)

    def to_dict(self) -> dict:
        return {
            'twocaptcha_api_key': self.twocaptcha_key.text().strip(),
            'capsolver_api_key': self.capsolver_key.text().strip(),
            'anticaptcha_api_key': self.anticaptcha_key.text().strip(),
            'primary_service': self.primary_service.currentText(),
            'fallback_service': self.fallback_service.currentText(),
            'timeout': self.timeout_spin.value(),
        }