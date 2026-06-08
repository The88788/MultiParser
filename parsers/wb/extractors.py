# core/extractors.py by 88788 — WB
from __future__ import annotations

import re
import urllib.request
from typing import Any

from parsers.wb.models import VariantInfo
from core.utils import dedupe_keep_order, extract_incident_id, extract_product_id_from_url, normalize_price, normalize_space


# ---------- Детекторы состояния страницы ----------

def detect_access_denied_wb(text: str) -> tuple[bool, str]:
    normalized = normalize_space(text)
    if not normalized:
        return False, ''
    patterns = ['Доступ ограничен', 'Инцидент:', 'Отключите VPN', 'заблокирован']
    if any(p.lower() in normalized.lower() for p in patterns):
        return True, extract_incident_id(text)
    return False, ''


def detect_404_wb(text: str, url: str) -> bool:
    normalized = normalize_space(text).lower()
    if 'страница не найдена' in normalized:
        return True
    if 'товар не найден' in normalized:
        return True
    return False


def detect_sold_out_wb(text: str) -> bool:
    return 'Нет в наличии' in normalize_space(text)


# ---------- Парсинг цен ----------

def parse_prices_wb(text: str) -> tuple[str, str, int]:
    """Возвращает (price_current, price_original, discount_pct)."""
    text = normalize_space(text)
    prices = [normalize_price(x) for x in re.findall(r'(\d[\d\s ]*)\s*₽', text)]
    prices = [p for p in prices if p]

    current = prices[0] if prices else ''
    original = prices[1] if len(prices) >= 2 else ''

    discount_match = re.search(r'[-−](\d+)\s*%', text)
    discount_pct = int(discount_match.group(1)) if discount_match else 0

    return current, original, discount_pct


# ---------- WB CDN ----------

def fetch_wb_cdn(nm_id: int) -> dict:
    """Загружает card.json + sellers.json с basket-NN.wbbasket.ru. Возвращает {'card': {...}, 'sellers': {...}}."""
    vol = nm_id // 100000
    part = nm_id // 1000

    card_data: dict[str, Any] = {}
    sellers_data: dict[str, Any] = {}
    basket_num: int | None = None

    for nn in range(1, 26):
        url = (
            f'https://basket-{nn:02d}.wbbasket.ru/vol{vol}/part{part}'
            f'/{nm_id}/info/ru/card.json'
        )
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=8) as resp:
                if resp.status == 200:
                    raw = resp.read()
                    import json
                    try:
                        text = raw.decode('utf-8')
                    except UnicodeDecodeError:
                        text = raw.decode('cp1251', errors='replace')
                    card_data = json.loads(text)
                    basket_num = nn
                    break
        except Exception:
            continue

    if basket_num is not None:
        sellers_url = (
            f'https://basket-{basket_num:02d}.wbbasket.ru/vol{vol}/part{part}'
            f'/{nm_id}/info/sellers.json'
        )
        try:
            req = urllib.request.Request(sellers_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=8) as resp:
                if resp.status == 200:
                    import json
                    raw_s = resp.read()
                    try:
                        text_s = raw_s.decode('utf-8')
                    except UnicodeDecodeError:
                        text_s = raw_s.decode('cp1251', errors='replace')
                    sellers_data = json.loads(text_s)
        except Exception:
            pass

    return {'card': card_data, 'sellers': sellers_data}


# ---------- Извлечение из CDN ----------

def extract_brand_from_cdn(cdn_data: dict) -> str:
    try:
        return normalize_space(cdn_data['card']['selling']['brand_name'])
    except (KeyError, TypeError):
        return ''


def extract_product_name_from_cdn(cdn_data: dict) -> str:
    try:
        return normalize_space(cdn_data['card']['imt_name'])
    except (KeyError, TypeError):
        return ''


def extract_seller_from_cdn(cdn_data: dict) -> str:
    try:
        sellers = cdn_data.get('sellers') or {}
        name = sellers.get('supplierName') or sellers.get('trademark') or ''
        return normalize_space(name)
    except Exception:
        return ''


def extract_sizes_from_cdn(cdn_data: dict, current_nm: str) -> list[VariantInfo]:
    variants: list[VariantInfo] = []
    try:
        values = cdn_data['card']['sizes_table']['values']
        for item in (values or []):
            chrt_id = str(item.get('chrt_id') or '').strip()
            tech_size = str(item.get('tech_size') or '').strip()
            if not chrt_id:
                continue
            variants.append(VariantInfo(
                sku=chrt_id,
                link='',
                text=tech_size or chrt_id,
                active=False,
            ))
    except (KeyError, TypeError):
        pass
    return variants


def extract_color_variants_from_cdn(cdn_data: dict, current_nm: str) -> list[VariantInfo]:
    variants: list[VariantInfo] = []
    seen: set[str] = set()
    try:
        card = cdn_data.get('card') or {}
        # Пробуем full_colors сначала, потом colors
        color_list = card.get('full_colors') or card.get('colors') or []
        for item in color_list:
            if isinstance(item, dict):
                nm = str(item.get('nm_id') or item.get('nmId') or '').strip()
            else:
                nm = str(item).strip()
            if not nm or nm == current_nm or nm in seen:
                continue
            seen.add(nm)
            from core.utils import build_product_url
            variants.append(VariantInfo(
                sku=nm,
                link=build_product_url(nm),
                text=nm,
                active=False,
            ))
    except Exception:
        pass
    return variants


# ---------- Извлечение из HTML-ссылок (фоллбэк для цветов) ----------

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


# ---------- Утилиты ----------

def join_variant_texts(items: list[VariantInfo]) -> str:
    return ', '.join(dedupe_keep_order([item.text or item.sku for item in items]))


def count_unique_texts(items: list[VariantInfo]) -> int:
    return len(dedupe_keep_order([item.text or item.sku for item in items]))
