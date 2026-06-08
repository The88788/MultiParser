# core/utils.py by 88788
from __future__ import annotations

import json
import random
import re
from datetime import datetime
from pathlib import Path
from typing import Any

PRODUCT_URL_RE = re.compile(r'/product/[^/]*?(\d+)(?:/|\?|$)')
INCIDENT_RE = re.compile(r'Инцидент:\s*([^\n\r<]+)')
ILLEGAL_XLSX_RE = re.compile(r'[\x00-\x08\x0B-\x0C\x0E-\x1F]')


def sanitize_excel_value(value: Any) -> Any:
    if value is None:
        return ''
    if isinstance(value, str):
        return ILLEGAL_XLSX_RE.sub('', value)
    return value


def sanitize_rows_for_excel(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cleaned_rows: list[dict[str, Any]] = []
    for row in rows:
        cleaned_row: dict[str, Any] = {}
        for key, value in row.items():
            cleaned_row[key] = sanitize_excel_value(value)
        cleaned_rows.append(cleaned_row)
    return cleaned_rows


def load_config(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8'))


def save_config(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def ensure_runtime_dirs(base_dir: Path) -> None:
    for name in ('output', 'logs', 'proxies', 'profiles'):
        (base_dir / name).mkdir(parents=True, exist_ok=True)
    (base_dir / 'logs' / 'debug').mkdir(parents=True, exist_ok=True)


def now_str() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def time_str() -> str:
    return datetime.now().strftime('%H:%M:%S')


def stamp_for_filename() -> str:
    return datetime.now().strftime('%Y-%m-%d_%H-%M')


def random_pause_seconds(min_value: float, max_value: float) -> float:
    if max_value < min_value:
        min_value, max_value = max_value, min_value
    return random.uniform(min_value, max_value)


def extract_product_id_from_url(url: str) -> str:
    match = PRODUCT_URL_RE.search(url or '')
    return match.group(1) if match else ''


def build_product_url(product_id: str) -> str:
    return f'https://www.ozon.ru/product/{product_id}'


def normalize_space(value: str) -> str:
    return re.sub(r'\s+', ' ', value or '').strip()


def normalize_price(value: str) -> str:
    value = normalize_space(value)
    match = re.search(r'([\d\s\u00A0]+)\s*[₽₸$€]?', value)
    if not match:
        return ''
    digits = re.sub(r'\D', '', match.group(1))
    return digits


def extract_incident_id(text: str) -> str:
    match = INCIDENT_RE.search(text or '')
    return normalize_space(match.group(1)) if match else ''


def dedupe_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        cleaned = normalize_space(item)
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        result.append(cleaned)
    return result