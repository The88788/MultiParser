from __future__ import annotations

import sys
import winreg
from pathlib import Path

_REG_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'


def _exe_path() -> str:
    if getattr(sys, 'frozen', False):
        return sys.executable
    return str(Path(sys.argv[0]).resolve())


def is_enabled(app_name: str) -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REG_KEY) as key:
            winreg.QueryValueEx(key, app_name)
            return True
    except FileNotFoundError:
        return False


def enable(app_name: str) -> None:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REG_KEY, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, f'"{_exe_path()}"')


def disable(app_name: str) -> None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REG_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, app_name)
    except FileNotFoundError:
        pass
