# core/models.py by the88788.com
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class QueueEntry:
    root_input_id: str
    current_product_id: str
    source_type: str
    parent_product_id: str = ''
    url_old: str = ''


@dataclass(slots=True)
class VariantInfo:
    sku: str
    link: str
    text: str
    active: bool = False


@dataclass(slots=True)
class ParseResult:
    root_input_id: str
    current_product_id: str
    source_type: str
    parent_product_id: str = ''
    url_old: str = ''
    new_url: str = ''
    date: str = ''
    brand: str = ''
    seller: str = ''
    product_name: str = ''
    price_wallet: str = ''
    price_current: str = ''
    price_original: str = ''
    discount_pct: int = 0
    sold_out: str = 'Нет'
    count_size: int = 0
    count_color: int = 0
    color_variants: str = ''
    incident_id: str = ''
    proxy_geo: str = ''
    error: str = ''
    parse_status: str = 'ok'
    parse_time: float = 0.0   # время обработки в секундах
    size_variant_map: list[dict[str, str]] = field(default_factory=list, repr=False)
    color_variant_ids: list[str] = field(default_factory=list, repr=False)

    def to_row(self) -> dict[str, Any]:
        row = asdict(self)
        row.pop('size_variant_map', None)
        row.pop('color_variant_ids', None)
        # color_variants — длинный текст, выносим в конец чтобы не мешал
        color_variants = row.pop('color_variants', '')
        row['color_variants'] = color_variants
        return row


@dataclass(slots=True)
class RelationRow:
    root_input_id: str
    parent_product_id: str
    current_product_id: str
    source_type: str

    def to_row(self) -> dict[str, str]:
        return asdict(self)


@dataclass(slots=True)
class ErrorRow:
    date: str
    current_product_id: str
    url: str
    error: str
    parse_status: str
    incident_id: str = ''
    error_detail: str = ''

    def to_row(self) -> dict[str, str]:
        return asdict(self)


@dataclass(slots=True)
class RunStats:
    total_input_ids: int = 0
    unique_seed_ids: int = 0
    processed: int = 0
    errors: int = 0
    size_variants: int = 0
    color_variants: int = 0
    rows: int = 0
    access_denied: int = 0
    captcha_solved: int = 0


@dataclass(slots=True)
class RunOutput:
    data_rows: list[dict[str, Any]] = field(default_factory=list)
    relation_rows: list[dict[str, str]] = field(default_factory=list)
    error_rows: list[dict[str, str]] = field(default_factory=list)
    stats: RunStats = field(default_factory=RunStats)
    output_file: str = ''