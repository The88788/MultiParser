# core/queue_manager.py by the88788.com
from __future__ import annotations

from collections import deque

from parsers.ozon.models import QueueEntry, RelationRow


class QueueManager:
    def __init__(self) -> None:
        self._queue: deque[QueueEntry] = deque()
        self.queued_ids: set[str] = set()
        self.visited_ids: set[str] = set()
        self._relation_keys: set[tuple[str, str, str, str]] = set()
        self._input_ids: set[str] = set()

    def reserve_input_ids(self, ids: set[str]) -> None:
        """Регистрирует входные IDs чтобы не добавлять их как варианты из других чанков."""
        self._input_ids = ids

    def add_seed(self, product_id: str) -> QueueEntry | None:
        product_id = (product_id or '').strip()
        if not product_id:
            return None
        if product_id in self.queued_ids or product_id in self.visited_ids:
            return None
        entry = QueueEntry(
            root_input_id=product_id,
            current_product_id=product_id,
            source_type='input',
            parent_product_id='',
            url_old='',
        )
        self._queue.append(entry)
        self.queued_ids.add(product_id)
        return entry

    def add_variant(
        self,
        *,
        root_input_id: str,
        current_product_id: str,
        source_type: str,
        parent_product_id: str,
        url_old: str,
    ) -> QueueEntry | None:
        current_product_id = (current_product_id or '').strip()
        if not current_product_id:
            return None
        if current_product_id in self._input_ids:
            return None  # будет обработан как input когда придёт его чанк
        if current_product_id in self.queued_ids or current_product_id in self.visited_ids:
            return None
        entry = QueueEntry(
            root_input_id=root_input_id,
            current_product_id=current_product_id,
            source_type=source_type,
            parent_product_id=parent_product_id,
            url_old=url_old,
        )
        self._queue.append(entry)
        self.queued_ids.add(current_product_id)
        return entry

    def add_relation(
        self,
        *,
        root_input_id: str,
        parent_product_id: str,
        current_product_id: str,
        source_type: str,
    ) -> RelationRow | None:
        key = (root_input_id, parent_product_id, current_product_id, source_type)
        if key in self._relation_keys:
            return None
        self._relation_keys.add(key)
        return RelationRow(
            root_input_id=root_input_id,
            parent_product_id=parent_product_id,
            current_product_id=current_product_id,
            source_type=source_type,
        )

    def pop(self) -> QueueEntry | None:
        if not self._queue:
            return None
        return self._queue.popleft()

    def mark_visited(self, product_id: str) -> None:
        product_id = (product_id or '').strip()
        if product_id:
            self.visited_ids.add(product_id)
            self.queued_ids.discard(product_id)

    def push_front(self, entry: QueueEntry) -> None:
        """Вставляет элемент в начало очереди, чтобы он был обработан следующим."""
        self._queue.appendleft(entry)
        pid = entry.current_product_id
        if pid:
            self.queued_ids.add(pid)
            self.visited_ids.discard(pid)

    def mark_unvisited(self, product_id: str) -> None:
        """Убирает ID из списка посещённых, делая возможной повторную обработку."""
        product_id = (product_id or '').strip()
        if product_id:
            self.visited_ids.discard(product_id)

    def __len__(self) -> int:
        return len(self._queue)