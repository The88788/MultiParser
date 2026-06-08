# core/proxy_manager.py by The 88788
from __future__ import annotations

from pathlib import Path
from typing import Optional


class ProxyManager:
    def __init__(self, proxy_config: dict):
        self.proxy_config = proxy_config or {}
        self._loaded_list: list[str] = []
        self._current_index = 0
        proxy_file = (self.proxy_config.get('proxy_file') or '').strip()
        if proxy_file:
            self._loaded_list = self._load_from_file(proxy_file)

    def get_launch_proxy(self) -> Optional[dict]:
        if not self.proxy_config.get('enabled', False):
            return None
        mode = self.proxy_config.get('mode', 'single')
        if mode == 'single':
            proxy = (self.proxy_config.get('single_proxy') or '').strip()
            return {'server': proxy} if proxy else None
        if mode == 'file' and self._loaded_list:
            # Ротация: берем текущий и сдвигаем указатель
            proxy = self._loaded_list[self._current_index % len(self._loaded_list)]
            self._current_index += 1
            return {'server': proxy}
        return None

    def next_proxy(self) -> Optional[dict]:
        """Сдвигает указатель на следующий прокси и возвращает его (для переключения при ошибке)."""
        if not self.proxy_config.get('enabled', False):
            return None
        mode = self.proxy_config.get('mode', 'single')
        if mode == 'single':
            # Один прокси – возвращаем его же (смена невозможна)
            proxy = (self.proxy_config.get('single_proxy') or '').strip()
            return {'server': proxy} if proxy else None
        if mode == 'file' and self._loaded_list:
            self._current_index += 1
            # После двух полных кругов останавливаем ротацию, чтобы не зациклиться
            if self._current_index >= len(self._loaded_list) * 2:
                return None
            proxy = self._loaded_list[self._current_index % len(self._loaded_list)]
            return {'server': proxy}
        return None

    @staticmethod
    def _load_from_file(proxy_file: str) -> list[str]:
        path = Path(proxy_file)
        if not path.exists():
            return []
        return [line.strip() for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]