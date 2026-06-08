# core/extractors.py by the88788.com
from __future__ import annotations

import json
import re
from typing import Any

from parsers.ozon.models import VariantInfo
from core.utils import dedupe_keep_order, extract_incident_id, extract_product_id_from_url, normalize_price, normalize_space


def detect_access_denied(text: str) -> tuple[bool, str]:
    normalized = normalize_space(text)
    if not normalized:
        return False, ''
    patterns = ['Доступ ограничен', 'Инцидент:', 'попробуйте сделать это', 'Отключить VPN']
    if any(pattern.lower() in normalized.lower() for pattern in patterns):
        return True, extract_incident_id(text)
    return False, ''


def detect_404(text: str, url: str) -> bool:
    normalized_text = normalize_space(text).lower()
    normalized_url = (url or '').lower()

    if 'страница не найдена' in normalized_text:
        return True
    if 'товар не найден' in normalized_text:
        return True
    if '/error/' in normalized_url and '404' in normalized_url:
        return True

    return False

def detect_sold_out(text: str) -> bool:
    normalized = normalize_space(text)
    if not normalized:
        return False
    return 'Этот товар закончился' in normalized

def parse_prices_from_text(price_text: str) -> tuple[str, str, str]:
    price_text = normalize_space(price_text)
    with_bank = ''
    without_bank = ''
    old_price = ''

    # 634 ₽ с Ozon Банком
    bank_match = re.search(
        r'(\d[\d\s\u00A0]*)\s*₽\s*[cс]\s*Ozon\s*Банком',
        price_text,
        flags=re.IGNORECASE
    )
    if bank_match:
        with_bank = normalize_price(bank_match.group(1))

    # 693 ₽ 4000 ₽ без Ozon Банка
    without_match = re.search(
        r'(\d[\d\s\u00A0]*)\s*₽(?:\s+(\d[\d\s\u00A0]*)\s*₽)?\s*без\s*Ozon\s*Банка',
        price_text,
        flags=re.IGNORECASE
    )
    if without_match:
        without_bank = normalize_price(without_match.group(1))
        if without_match.group(2):
            old_price = normalize_price(without_match.group(2))

    candidates = [normalize_price(x) for x in re.findall(r'(\d[\d\s\u00A0]*)\s*₽', price_text)]
    candidates = [x for x in candidates if x]

    if not with_bank and len(candidates) >= 1:
        with_bank = candidates[0]

    if not without_bank:
        if with_bank and len(candidates) >= 2 and candidates[0] == with_bank:
            without_bank = candidates[1]
        elif len(candidates) >= 1:
            without_bank = candidates[0]

    if not old_price:
        for candidate in candidates:
            if candidate not in {with_bank, without_bank}:
                old_price = candidate
                break

    return with_bank, without_bank, old_price


def parse_state_webaspects(raw_data_state: str) -> dict[str, Any]:
    if not raw_data_state:
        return {}
    try:
        return json.loads(raw_data_state)
    except json.JSONDecodeError:
        return {}


def extract_size_variants(state_data: dict[str, Any]) -> tuple[list[VariantInfo], VariantInfo | None]:
    aspects = state_data.get('aspects') or []
    variants: list[VariantInfo] = []
    active_variant: VariantInfo | None = None
    for aspect in aspects:
        if aspect.get('aspectKey') != 'size':
            continue
        if aspect.get('type') != 'sizes':
            continue
        for item in aspect.get('variants') or []:
            sku = str(item.get('sku') or '').strip()
            link = str(item.get('link') or '').strip()
            data = item.get('data') or {}
            text_value = ''
            if isinstance(data, dict):
                text_value = str(data.get('searchableText') or '').strip()
                if not text_value:
                    text_rs = data.get('textRs') or []
                    if text_rs and isinstance(text_rs, list):
                        first = text_rs[0] or {}
                        if isinstance(first, dict):
                            text_value = str(first.get('content') or '').strip()
            active = bool(item.get('active'))
            variant = VariantInfo(
                sku=sku,
                link=link,
                text=normalize_space(text_value),
                active=active,
            )
            variants.append(variant)
            if active:
                active_variant = variant
        break
    return variants, active_variant


def extract_color_variants_from_aspects(state_data: dict[str, Any]) -> list[VariantInfo]:
    """Извлекает цветовые варианты из структурированного state-webAspects JSON."""
    aspects = state_data.get('aspects') or []
    variants: list[VariantInfo] = []
    seen: set[str] = set()
    for aspect in aspects:
        if aspect.get('aspectKey', '').lower() != 'color':
            continue
        for item in aspect.get('variants') or []:
            sku = str(item.get('sku') or '').strip()
            if not sku or sku in seen:
                continue
            seen.add(sku)
            data = item.get('data') or {}
            text_value = str(data.get('searchableText') or '').strip()
            if not text_value:
                text_rs = data.get('textRs') or []
                if text_rs and isinstance(text_rs, list):
                    first = text_rs[0] or {}
                    if isinstance(first, dict):
                        text_value = str(first.get('content') or '').strip()
            variants.append(VariantInfo(
                sku=sku,
                link=str(item.get('link') or '').strip(),
                text=normalize_space(text_value) or sku,
                active=bool(item.get('active')),
            ))
        break  # берём только первый Color-аспект
    return variants


def extract_color_variants_from_links(urls: list[str], current_product_id: str) -> list[VariantInfo]:
    items: list[VariantInfo] = []
    seen: set[str] = set()
    for href in urls:
        product_id = extract_product_id_from_url(href)
        if not product_id or product_id == current_product_id or product_id in seen:
            continue
        seen.add(product_id)
        items.append(VariantInfo(sku=product_id, link=href, text=product_id, active=False))
    return items


def join_variant_texts(items: list[VariantInfo]) -> str:
    return ', '.join(dedupe_keep_order([item.text or item.sku for item in items]))


def count_unique_texts(items: list[VariantInfo]) -> int:
    return len(dedupe_keep_order([item.text or item.sku for item in items]))