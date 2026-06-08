from __future__ import annotations

import traceback
from pathlib import Path

from PySide6.QtCore import QThread

from parsers.ozon.parser_core import ParserCore
from parsers.ozon.excel_exporter import export_snapshot as _export_fn
from core.proxy_checker import ProxyChecker
from core.utils import ensure_runtime_dirs
from gui.log_handler import LogEmitter


class ParserWorker(QThread):
    def __init__(self, *, base_dir: Path, config: dict, input_ids: list[str],
                 emitter: LogEmitter, valid_proxy_lines: list[str] | None = None):
        super().__init__()
        self.base_dir = base_dir
        self.config = config
        self.input_ids = input_ids
        self.emitter = emitter
        self.valid_proxy_lines: list[str] = list(valid_proxy_lines or [])
        self._stop_requested = False
        self.runner = None

    def stop(self) -> None:
        self._stop_requested = True
        if self.runner is not None:
            try:
                self.runner.request_stop()
            except Exception:
                pass

    def _should_stop(self) -> bool:
        return self._stop_requested

    def _log(self, level: str, message: str) -> None:
        self.emitter.log_signal.emit(level, message)

    def _stats(self, stats) -> None:
        payload = {
            'total_input_ids': stats.total_input_ids,
            'unique_seed_ids': stats.unique_seed_ids,
            'processed': stats.processed,
            'errors': stats.errors,
            'size_variants': stats.size_variants,
            'color_variants': stats.color_variants,
            'rows': stats.rows,
            'access_denied': stats.access_denied,
            'captcha_solved': stats.captcha_solved,
        }
        self.emitter.stats_signal.emit(payload)

    def run(self) -> None:
        import time as _t
        _start = _t.time()
        try:
            ensure_runtime_dirs(self.base_dir)
            ParserCore.rotate_logs(self.base_dir)
            if self.config.get('parser', {}).get('multi_parsing_enabled', False):
                from core.multi_runner import MultiThreadRunner
                valid_lines = self.valid_proxy_lines
                proxy_list = []
                temp_parser = ParserCore(
                    base_dir=self.base_dir,
                    config=self.config,
                    stop_requested=lambda: False,
                    log=lambda *a: None,
                    stats_callback=None,
                )
                for line in valid_lines:
                    try:
                        proxy = temp_parser._parse_single_proxy_line(line)
                        proxy_list.append(proxy)
                    except Exception:
                        pass
                threads = self.config.get('parser', {}).get('threads_count', 1)
                self.runner = MultiThreadRunner(
                    base_dir=self.base_dir,
                    config=self.config,
                    log=self._log,
                    stats_callback=self._stats,
                    stop_requested=self._should_stop,
                    parser_core_class=ParserCore,
                    export_fn=_export_fn,
                )
                output = self.runner.run(self.input_ids, proxy_list, threads)
            else:
                parser = ParserCore(
                    base_dir=self.base_dir,
                    profile_name='default',
                    config=self.config,
                    stop_requested=self._should_stop,
                    log=self._log,
                    stats_callback=self._stats,
                )
                output = parser.run(self.input_ids)
            self.emitter.finished_signal.emit({
                'output_file': output.output_file,
                'rows': len(output.data_rows),
                'errors': len(output.error_rows),
                'elapsed': _t.time() - _start,
            })
        except Exception as exc:
            tb = traceback.format_exc()
            self.emitter.error_signal.emit(f'{type(exc).__name__}: {exc}\n\n{tb}')


class ProxyTestWorker(QThread):
    def __init__(self, *, base_dir: Path, config: dict, emitter: LogEmitter):
        super().__init__()
        self.base_dir = base_dir
        self.config = config
        self.emitter = emitter
        self._stop_requested = False

        self.valid_proxy_lines: list[str] = []
        self.invalid_proxy_lines: list[str] = []
        self.checked_proxy_file_path: str = ''

    def stop(self) -> None:
        self._stop_requested = True

    def _should_stop(self) -> bool:
        return self._stop_requested

    def _log(self, level: str, message: str) -> None:
        self.emitter.log_signal.emit(level, message)

    def run(self) -> None:
        checker = ProxyChecker(
            base_dir=self.base_dir,
            config=self.config,
            log=self._log,
            stop_requested=self._should_stop,
        )
        checker.run()
        self.valid_proxy_lines = checker.valid_proxy_lines
        self.invalid_proxy_lines = checker.invalid_proxy_lines
        self.checked_proxy_file_path = checker.checked_proxy_file_path
