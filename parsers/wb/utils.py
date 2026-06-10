# parsers/wb/utils.py by 88788
from __future__ import annotations

import re

WB_PRODUCT_URL_RE = re.compile(r'/catalog/(\d+)(?:/|\?|$)')


def build_wb_product_url(product_id: str) -> str:
    return f'https://www.wildberries.ru/catalog/{product_id}/detail.aspx'


def extract_wb_product_id_from_url(url: str) -> str:
    match = WB_PRODUCT_URL_RE.search(url or '')
    return match.group(1) if match else ''
