from pathlib import Path
import sys

from PySide6.QtWidgets import QApplication

from core.utils import ensure_runtime_dirs, load_config
from gui.ozon.gui_main import MainWindow, build_app_icon

# Без этого Windows ассоциирует иконку с python.exe, а не с приложением
if sys.platform == 'win32':
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('ozon.parser.88788')
    except Exception:
        pass


def _set_taskbar_icon_win32(hwnd: int, ico_path: str) -> None:
    """Принудительно устанавливает нативный HICON на HWND через WM_SETICON.
    Qt не всегда делает это сам, из-за чего панель задач показывает дефолтную иконку."""
    try:
        import ctypes
        WM_SETICON = 0x0080
        IMAGE_ICON = 1
        LR_LOADFROMFILE = 0x00000010
        user32 = ctypes.windll.user32
        # ICON_SMALL (0) — заголовок окна, ICON_BIG (1) — панель задач и Alt+Tab
        for size, kind in ((16, 0), (32, 1)):
            hicon = user32.LoadImageW(None, ico_path, IMAGE_ICON, size, size, LR_LOADFROMFILE)
            if hicon:
                user32.SendMessageW(hwnd, WM_SETICON, kind, hicon)
    except Exception:
        pass


def main() -> int:
    if getattr(sys, "frozen", False):
        base_dir = Path(sys.executable).resolve().parent
        resources_dir = Path(getattr(sys, '_MEIPASS', str(base_dir)))
    else:
        base_dir = Path(__file__).resolve().parent
        resources_dir = base_dir

    ensure_runtime_dirs(base_dir)

    config_path = base_dir / "config_ozon.json"
    if not config_path.exists():
        raise FileNotFoundError(f"Не найден config_ozon.json: {config_path}")

    config = load_config(config_path)

    app = QApplication(sys.argv)

    app_icon = build_app_icon(resources_dir)
    if not app_icon.availableSizes():
        print(f'[WARNING] Иконка не загружена — проверь папку {resources_dir / "assets"}', file=sys.stderr)
    else:
        app.setWindowIcon(app_icon)

    window = MainWindow(base_dir=base_dir, config=config, resources_dir=resources_dir)
    window.show()

    if sys.platform == 'win32':
        ico_path = resources_dir / 'assets' / 'ozon.ico'
        if ico_path.exists():
            from PySide6.QtCore import QTimer
            hwnd = int(window.winId())
            ico_str = str(ico_path)
            QTimer.singleShot(300, lambda: _set_taskbar_icon_win32(hwnd, ico_str))

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())