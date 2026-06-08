from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QSize, QTimer
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QGroupBox, QHBoxLayout,
    QLabel, QPushButton, QRadioButton,
    QSizePolicy, QSpinBox, QStackedWidget, QVBoxLayout, QWidget,
)



class CronTab(QWidget):
    """Вкладка планировщика автозапуска парсера."""

    _WEEKDAYS = [
        'Понедельник', 'Вторник', 'Среда', 'Четверг',
        'Пятница', 'Суббота', 'Воскресенье',
    ]

    def __init__(self, cron_cfg: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._max_hint = None
        self._build_ui()
        self._load_from_config(cron_cfg)
        self._connect_signals()

        # Обновление метки «Следующий запуск» каждые 30 сек
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._tick)
        self._refresh_timer.start(30_000)

    def sizeHint(self):
        current = super().sizeHint()
        # Кешируем максимальную ширину пока _time_part виден.
        # Когда он скрыт (режим «По интервалу») — возвращаем кэш,
        # чтобы QSplitter не пересчитывал пропорции колонок.
        if self._time_part.isVisible():
            if self._max_hint is None or current.width() > self._max_hint.width():
                self._max_hint = QSize(current.width(), current.height())
        return self._max_hint if self._max_hint is not None else current

    # ------------------------------------------------------------------ #
    #  Build UI                                                            #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        # ── Расписание ─────────────────────────────────────────────────
        sched_group = QGroupBox('Расписание')
        sg = QVBoxLayout(sched_group)
        sg.setSpacing(5)

        mode_row = QHBoxLayout()
        mode_row.setSpacing(12)
        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)
        for key, label in [
            ('daily',    'Ежедневно'),
            ('weekly',   'Еженедельно'),
            ('monthly',  'Ежемесячно'),
            ('interval', 'По интервалу'),
        ]:
            rb = QRadioButton(label)
            rb.setProperty('cron_mode', key)
            self._mode_group.addButton(rb)
            mode_row.addWidget(rb)
        mode_row.addStretch()
        sg.addLayout(mode_row)

        # Вторая строка: время + контекст режима — всё в одной строке
        options_row = QWidget()
        ol = QHBoxLayout(options_row)
        ol.setContentsMargins(0, 0, 0, 0)
        ol.setSpacing(6)

        # Блок времени (скрыт для режима «По интервалу»)
        self._time_part = QWidget()
        tl = QHBoxLayout(self._time_part)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(4)
        tl.addWidget(QLabel('Время запуска:'))
        self.hour_spin = QSpinBox()
        self.hour_spin.setRange(0, 23)
        self.hour_spin.setFixedWidth(64)
        self.hour_spin.setWrapping(True)
        tl.addWidget(self.hour_spin)
        tl.addWidget(QLabel('ч'))
        self.minute_spin = QSpinBox()
        self.minute_spin.setRange(0, 59)
        self.minute_spin.setFixedWidth(64)
        self.minute_spin.setWrapping(True)
        tl.addWidget(self.minute_spin)
        tl.addWidget(QLabel('мин'))
        ol.addWidget(self._time_part)

        # Контекстный блок — зависит от режима, растягивается на всю оставшуюся ширину
        self._ctx_stack = QStackedWidget()
        self._ctx_stack.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )

        # Страница 0: ежедневно — ничего дополнительного
        self._ctx_stack.addWidget(QWidget())

        # Страница 1: еженедельно
        self._ctx_weekly = QWidget()
        wl = QHBoxLayout(self._ctx_weekly)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.addWidget(QLabel('День недели:'))
        self.weekday_combo = QComboBox()
        self.weekday_combo.addItems(self._WEEKDAYS)
        self.weekday_combo.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        wl.addWidget(self.weekday_combo)
        wl.addStretch()
        self._ctx_stack.addWidget(self._ctx_weekly)

        # Страница 2: ежемесячно
        self._ctx_monthly = QWidget()
        ml = QHBoxLayout(self._ctx_monthly)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.addWidget(QLabel('День месяца:'))
        self.day_of_month_spin = QSpinBox()
        self.day_of_month_spin.setRange(1, 31)
        self.day_of_month_spin.setFixedWidth(60)
        ml.addWidget(self.day_of_month_spin)
        ml.addStretch()
        self._ctx_stack.addWidget(self._ctx_monthly)

        # Страница 3: по интервалу
        self._ctx_interval = QWidget()
        il = QHBoxLayout(self._ctx_interval)
        il.setContentsMargins(0, 0, 0, 0)
        il.addWidget(QLabel('Каждые:'))
        self.interval_days_spin = QSpinBox()
        self.interval_days_spin.setRange(0, 999)
        self.interval_days_spin.setSuffix(' дн.')
        self.interval_days_spin.setFixedWidth(96)
        il.addWidget(self.interval_days_spin)
        self.interval_hours_spin = QSpinBox()
        self.interval_hours_spin.setRange(0, 23)
        self.interval_hours_spin.setSuffix(' ч.')
        self.interval_hours_spin.setFixedWidth(82)
        il.addWidget(self.interval_hours_spin)
        il.addWidget(QLabel('(например: 5 дн. 0 ч. или 0 дн. 3 ч.)'))
        il.addStretch()
        self._ctx_stack.addWidget(self._ctx_interval)

        ol.addWidget(self._ctx_stack)
        sg.addWidget(options_row)

        self.skip_weekends_cb = QCheckBox(
            'Не запускать в выходные дни (суббота и воскресенье)'
        )
        sg.addWidget(self.skip_weekends_cb)

        root.addWidget(sched_group)

        # ── Прокси ─────────────────────────────────────────────────────
        proxy_group = QGroupBox('Прокси')
        pg = QVBoxLayout(proxy_group)
        pg.setSpacing(4)

        self.check_proxies_cb = QCheckBox(
            'Проверять прокси перед каждым запуском'
        )
        self.delete_invalid_cb = QCheckBox(
            'Удалять нерабочие прокси из файла после проверки'
        )
        pg.addWidget(self.check_proxies_cb)
        pg.addWidget(self.delete_invalid_cb)

        busy_row = QHBoxLayout()
        busy_row.addWidget(QLabel('Если парсер уже запущен:'))
        self._busy_group = QButtonGroup(self)
        self.rb_skip = QRadioButton('Пропустить итерацию')
        self.rb_wait = QRadioButton('Дождаться завершения')
        self._busy_group.addButton(self.rb_skip)
        self._busy_group.addButton(self.rb_wait)
        busy_row.addWidget(self.rb_skip)
        busy_row.addWidget(self.rb_wait)
        busy_row.addStretch()
        pg.addLayout(busy_row)

        root.addWidget(proxy_group)

        # ── Нижняя панель ───────────────────────────────────────────────
        self.validation_label = QLabel('')
        self.validation_label.setWordWrap(True)
        root.addWidget(self.validation_label)

        btn_row = QHBoxLayout()
        self.activate_btn = QPushButton('Активировать расписание')
        self.activate_btn.setCheckable(True)
        self.activate_btn.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        self.run_now_btn = QPushButton('Запустить сейчас')
        self.run_now_btn.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        btn_row.addWidget(self.activate_btn)
        btn_row.addWidget(self.run_now_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        info_row = QHBoxLayout()
        self.next_run_label = QLabel('Следующий запуск: —')
        self.last_run_label = QLabel('Последний запуск: —')
        info_row.addWidget(self.next_run_label)
        info_row.addStretch()
        info_row.addWidget(self.last_run_label)
        root.addLayout(info_row)

        root.addStretch()

    # ------------------------------------------------------------------ #
    #  Config load / save                                                  #
    # ------------------------------------------------------------------ #

    def _load_from_config(self, cfg: dict) -> None:
        time_str = cfg.get('time', '09:00')
        try:
            h, m = map(int, time_str.split(':'))
        except Exception:
            h, m = 9, 0
        self.hour_spin.setValue(h)
        self.minute_spin.setValue(m)

        mode = cfg.get('mode', 'daily')
        for btn in self._mode_group.buttons():
            if btn.property('cron_mode') == mode:
                btn.setChecked(True)
                break
        self._apply_mode_visibility()

        self.weekday_combo.setCurrentIndex(max(0, min(6, int(cfg.get('weekday', 0)))))
        self.day_of_month_spin.setValue(max(1, min(31, int(cfg.get('day_of_month', 1)))))
        self.interval_days_spin.setValue(max(0, int(cfg.get('interval_days', 0))))
        self.interval_hours_spin.setValue(max(0, int(cfg.get('interval_hours', 1))))

        self.skip_weekends_cb.setChecked(bool(cfg.get('skip_weekends', False)))
        self.check_proxies_cb.setChecked(bool(cfg.get('check_proxies_before_run', True)))
        self.delete_invalid_cb.setChecked(bool(cfg.get('delete_invalid_proxies', True)))

        if cfg.get('skip_or_wait', 'skip') == 'wait':
            self.rb_wait.setChecked(True)
        else:
            self.rb_skip.setChecked(True)


    def to_dict(self) -> dict:
        checked = self._mode_group.checkedButton()
        mode = checked.property('cron_mode') if checked else 'daily'
        return {
            'mode': mode,
            'time': f'{self.hour_spin.value():02d}:{self.minute_spin.value():02d}',
            'weekday': self.weekday_combo.currentIndex(),
            'day_of_month': self.day_of_month_spin.value(),
            'interval_days': self.interval_days_spin.value(),
            'interval_hours': self.interval_hours_spin.value(),
            'skip_weekends': self.skip_weekends_cb.isChecked(),
            'check_proxies_before_run': self.check_proxies_cb.isChecked(),
            'delete_invalid_proxies': self.delete_invalid_cb.isChecked(),
            'skip_or_wait': 'wait' if self.rb_wait.isChecked() else 'skip',
            'proxy_low_threshold': 5,
        }

    # ------------------------------------------------------------------ #
    #  Signals                                                             #
    # ------------------------------------------------------------------ #

    def _connect_signals(self) -> None:
        self._mode_group.buttonClicked.connect(lambda _: self._apply_mode_visibility())

    def _apply_mode_visibility(self) -> None:
        checked = self._mode_group.checkedButton()
        mode = checked.property('cron_mode') if checked else 'daily'
        # Сбрасываем фокус со скрываемых виджетов, чтобы не «зависал» ввод
        if mode == 'interval':
            for w in (self.hour_spin, self.minute_spin):
                if w.hasFocus():
                    w.clearFocus()
        else:
            for w in (self.interval_days_spin, self.interval_hours_spin):
                if w.hasFocus():
                    w.clearFocus()
        self._time_part.setVisible(mode != 'interval')
        self._ctx_stack.setCurrentIndex(
            {'daily': 0, 'weekly': 1, 'monthly': 2, 'interval': 3}.get(mode, 0)
        )

    def _tick(self) -> None:
        pass  # обновление идёт из MainWindow через update_labels

    # ------------------------------------------------------------------ #
    #  Public helpers (вызываются из MainWindow)                          #
    # ------------------------------------------------------------------ #

    def set_active(self, active: bool) -> None:
        self.activate_btn.setChecked(active)
        self.activate_btn.setText(
            'Деактивировать расписание' if active else 'Активировать расписание'
        )

    def set_validation(self, ok: bool, errors: list[str]) -> None:
        if ok:
            self.validation_label.setText(
                '<span style="color:#2e7d32;">✓ Все условия выполнены</span>'
            )
        elif errors:
            items = ''.join(f'<li>{e}</li>' for e in errors)
            self.validation_label.setText(
                f'<span style="color:#c62828;"><ul style="margin:0;padding-left:16px;">'
                f'{items}</ul></span>'
            )
        else:
            self.validation_label.setText('')

    def update_labels(
        self,
        next_dt: datetime | None,
        last_dt: datetime | None,
    ) -> None:
        fmt = '%d.%m.%Y %H:%M'
        self.next_run_label.setText(
            f'Следующий запуск: <b>{next_dt.strftime(fmt)}</b>'
            if next_dt else 'Следующий запуск: —'
        )
        self.last_run_label.setText(
            f'Последний запуск: {last_dt.strftime(fmt)}'
            if last_dt else 'Последний запуск: —'
        )

