APP_QSS = """
QWidget {
    font-size: 12px;
    color: #1f2933;
    background: #f7fbff;
}

QToolTip {
    background: #ffffff;
    color: #1f2933;
    border: 1px solid #c7d3dd;
    border-radius: 6px;
    padding: 4px 8px;
    font-size: 12px;
    font-weight: normal;
}

QPlainTextEdit,
QTextEdit {
    border: 1px solid #c7d3dd;
    border-radius: 8px;
    padding: 8px;
    background: #ffffff;
    selection-background-color: #cfe8ff;
    selection-color: #1f2933;
}

QLineEdit {
    min-height: 22px;
    max-height: 24px;
    border: 1px solid #c7d3dd;
    border-radius: 8px;
    background: #ffffff;
    color: #1f2933;
    padding: 0 10px;
    selection-background-color: #cfe8ff;
    selection-color: #1f2933;
}

QLineEdit:focus,
QPlainTextEdit:focus,
QTextEdit:focus {
    border: 1px solid #8db4d4;
}

QPushButton {
    min-height: 28px;
    border-radius: 8px;
    border: 1px solid #8db4d4;
    background: #e8f3fb;
    color: #1f2933;
    padding: 0 14px;
}

QPushButton:hover {
    background: #d7ebfa;
}

QPushButton:pressed {
    background: #c8e2f6;
}

QPushButton:disabled {
    background: #eef4f8;
    color: #8a97a6;
    border: 1px solid #d3dee7;
}

QGroupBox {
    font-weight: bold;
    border: 1px solid #d8e2ea;
    border-radius: 10px;
    margin-top: 2px;
    padding-top: 2px;
    background: #f7fbff;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px 0 6px;
    background: #f7fbff;
}

QStatusBar {
    background: #f4f8fb;
    border-top: 1px solid #d8e2ea;
}

QTabWidget::pane {
    border: 1px solid #c7d3dd;
    border-radius: 8px;
    background: #ffffff;
    top: -1px;
}

QTabBar::tab {
    background: #e8f3fb;
    border: 1px solid #8db4d4;
    border-bottom: none;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    padding: 7px 14px;
    margin-right: 4px;
    min-height: 20px;
}

QTabBar::tab:selected {
    background: #ffffff;
}

QTabBar::tab:hover {
    background: #d7ebfa;
}

QLabel {
    background: transparent;
}

QScrollBar:vertical {
    background: #eef4f8;
    width: 12px;
    border-radius: 6px;
    margin: 2px;
}

QScrollBar::handle:vertical {
    background: #b7cad9;
    border-radius: 6px;
    min-height: 30px;
}

QScrollBar::handle:vertical:hover {
    background: #9eb7ca;
}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {
    background: none;
    border: none;
}

QScrollBar:horizontal {
    background: #eef4f8;
    height: 12px;
    border-radius: 6px;
    margin: 2px;
}

QScrollBar::handle:horizontal {
    background: #b7cad9;
    border-radius: 6px;
    min-width: 30px;
}

QScrollBar::handle:horizontal:hover {
    background: #9eb7ca;
}

QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal,
QScrollBar::add-page:horizontal,
QScrollBar::sub-page:horizontal {
    background: none;
    border: none;
}

QPushButton[compactIconButton="true"] {
    min-height: 28px;
    max-height: 28px;
    min-width: 28px;
    max-width: 28px;
    padding: 0;
    border-radius: 8px;
}

QMenu {
    background: #ffffff;
    color: #1f2933;
    border: 1px solid #c7d3dd;
    border-radius: 8px;
    padding: 6px;
}

QMenu::item {
    background: transparent;
    padding: 6px 12px;
    border-radius: 6px;
    margin: 2px 0;
}

QMenu::item:selected {
    background: #d7ebfa;
    color: #1f2933;
}

QMenu::item:disabled {
    color: #8a97a6;
    background: transparent;
}

QMenu::separator {
    height: 1px;
    background: #d8e2ea;
    margin: 6px 4px;
}

QSpinBox,
QDoubleSpinBox {
    min-height: 24px;
    max-height: 26px;
    border: 1px solid #c7d3dd;
    border-radius: 8px;
    background: #ffffff;
    color: #1f2933;
    padding: 0 6px 0 10px;
}

QSpinBox:focus,
QDoubleSpinBox:focus {
    border: 1px solid #8db4d4;
}

QSpinBox::up-button,
QDoubleSpinBox::up-button {
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 24px;
    border-left: 1px solid #d8e2ea;
    border-bottom: 1px solid #d8e2ea;
    border-top-right-radius: 8px;
    background: #f4f8fb;
}

QSpinBox::down-button,
QDoubleSpinBox::down-button {
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    width: 24px;
    border-left: 1px solid #d8e2ea;
    border-bottom-right-radius: 8px;
    background: #f4f8fb;
}

QSpinBox::up-button:hover,
QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover,
QDoubleSpinBox::down-button:hover {
    background: #e8f3fb;
}

QSpinBox::up-button:pressed,
QDoubleSpinBox::up-button:pressed,
QSpinBox::down-button:pressed,
QDoubleSpinBox::down-button:pressed {
    background: #d7ebfa;
}

QSpinBox::up-arrow,
QDoubleSpinBox::up-arrow {
    image: url(assets/spin_up.svg);
    width: 10px;
    height: 10px;
}

QSpinBox::down-arrow,
QDoubleSpinBox::down-arrow {
    image: url(assets/spin_down.svg);
    width: 10px;
    height: 10px;
}

QCheckBox {
    spacing: 6px;
    background: transparent;
    color: #1f2933;
}

QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #8db4d4;
    border-radius: 5px;
    background: #ffffff;
}

QCheckBox::indicator:hover {
    border: 1px solid #6fa7d1;
    background: #f4f8fb;
}

QCheckBox::indicator:checked {
    border: 1px solid #2b90d9;
    background: #2b90d9;
    image: url(assets/check_mark.svg);
}

QCheckBox::indicator:checked:hover {
    border: 1px solid #247fc1;
    background: #247fc1;
}

QCheckBox::indicator:disabled {
    border: 1px solid #d3dee7;
    background: #eef4f8;
}

QCheckBox::indicator:checked:disabled {
    border: 1px solid #9fc3df;
    background: #9fc3df;
    image: url(assets/check_mark.svg);
}

QRadioButton {
    spacing: 6px;
    background: transparent;
    color: #1f2933;
}

QRadioButton::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #8db4d4;
    border-radius: 5px;
    background: #ffffff;
}

QRadioButton::indicator:hover {
    border: 1px solid #6fa7d1;
    background: #f4f8fb;
}

QRadioButton::indicator:checked {
    border: 1px solid #2b90d9;
    background: #2b90d9;
    image: url(assets/check_mark.svg);
}

QRadioButton::indicator:checked:hover {
    border: 1px solid #247fc1;
    background: #247fc1;
}

QRadioButton::indicator:disabled {
    border: 1px solid #d3dee7;
    background: #eef4f8;
}

QRadioButton::indicator:checked:disabled {
    border: 1px solid #9fc3df;
    background: #9fc3df;
    image: url(assets/check_mark.svg);
}
QComboBox {
    min-height: 24px;
    max-height: 26px;
    border: 1px solid #c7d3dd;
    border-radius: 8px;
    background: #ffffff;
    color: #1f2933;
    padding: 0 30px 0 6px;
}

QComboBox:focus {
    border: 1px solid #8db4d4;
}

QComboBox::drop-down {
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 24px;
    border-left: 1px solid #d8e2ea;
    border-top-right-radius: 8px;
    border-bottom-right-radius: 8px;
    background: #f4f8fb;
}

QComboBox::drop-down:hover {
    background: #e8f3fb;
}

QComboBox::drop-down:pressed {
    background: #d7ebfa;
}

QComboBox::down-arrow {
    image: url(assets/combo_down.svg);
    width: 10px;
    height: 10px;
}

QComboBox QAbstractItemView {
    border: 1px solid #c7d3dd;
    border-radius: 8px;
    background: #ffffff;
    color: #1f2933;
    selection-background-color: #d7ebfa;
    selection-color: #1f2933;
    outline: 0;
    padding: 4px;
}
"""