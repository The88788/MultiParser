# parsers/ozon/utils.py by 88788
from __future__ import annotations

import re

OZON_PRODUCT_URL_RE = re.compile(r'/product/[^/]*?(\d+)(?:/|\?|$)')


def build_ozon_product_url(product_id: str) -> str:
    return f'https://www.ozon.ru/product/{product_id}'


def extract_ozon_product_id_from_url(url: str) -> str:
    match = OZON_PRODUCT_URL_RE.search(url or '')
    return match.group(1) if match else ''
