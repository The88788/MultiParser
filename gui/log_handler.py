# gui/log_handler.py 88788
from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class LogEmitter(QObject):
    log_signal = Signal(str, str)
    stats_signal = Signal(dict)
    finished_signal = Signal(dict)
    error_signal = Signal(str)