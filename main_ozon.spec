# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all, collect_submodules
import importlib.util
from pathlib import Path


def _browser_datas(pkg_name: str) -> list:
    """collect_all не подхватывает .local-browsers — добавляем вручную."""
    spec = importlib.util.find_spec(pkg_name)
    if not spec:
        return []
    pkg_dir = Path(spec.submodule_search_locations[0])
    browsers_dir = pkg_dir / 'driver' / 'package' / '.local-browsers'
    if not browsers_dir.exists():
        print(f'WARNING: {pkg_name} browsers not found. Run: {pkg_name} install chromium')
        return []
    return [(str(browsers_dir), f'{pkg_name}/driver/package/.local-browsers')]


# Собираем все данные playwright/patchright — они тянут JS-бридж и данные браузера
pw_datas, pw_binaries, pw_hidden = collect_all('playwright')
pr_datas, pr_binaries, pr_hidden = collect_all('patchright')
cf_datas, cf_binaries, cf_hidden = collect_all('camoufox')
bf_datas, bf_binaries, bf_hidden = collect_all('browserforge')

# Браузерные бинарники (.local-browsers) не входят в Python-пакет — добавляем явно
browser_datas = _browser_datas('playwright') + _browser_datas('patchright')

a = Analysis(
    ['main_ozon.py'],
    pathex=[],
    binaries=pw_binaries + pr_binaries + cf_binaries + bf_binaries,
    datas=[
        ('assets', 'assets'),
        ('config_ozon.default.json', '.'),
    ] + pw_datas + pr_datas + cf_datas + bf_datas + browser_datas,
    hiddenimports=(
        pw_hidden + pr_hidden + cf_hidden + bf_hidden
        + collect_submodules('anticaptchaofficial')
        + collect_submodules('twocaptcha')
        + collect_submodules('capsolver')
        + collect_submodules('curl_cffi')
        + [
            'winreg',
            'openpyxl',
            'pandas',
            'lxml',
            'lxml.etree',
            'requests',
            'httpx',
            'PySide6.QtCore',
            'PySide6.QtGui',
            'PySide6.QtWidgets',
            'PySide6.QtSvg',
        ]
    ),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='OZON Parser',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon='assets/ozon.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='OZON Parser',
    contents_directory='.',
)
