"""Normalización de un item crudo de /svc-catalogue/items.

La API ya no devuelve `brand_title`, `size_title` ni `status` estructurados:
solo los muestra como texto en `item_box`:
    first_line  = "Nike"                     -> marca (puede faltar)
    second_line = "42 · Muy bueno"           -> talla · estado
                = "Muy bueno"                -> categorías sin talla
"""

from __future__ import annotations

from typing import Any

SEP = " · "

# Vocabulario de estados (es-ES), tomado de /svc-filters/filters/facets?filter_code=status.
# Ids estables entre mercados; los títulos dependen del idioma.
STATUS_ES = {
    "Nuevo con etiquetas": 6,
    "Nuevo sin etiquetas": 1,
    "Muy bueno": 2,
    "Bueno": 3,
    "Satisfactorio": 4,
}


def parse_item_box(item_box: dict[str, Any] | None, status_vocab: dict[str, int] = STATUS_ES) -> dict[str, Any]:
    """Devuelve brand_title, size_title, status_title, status_id a partir del item_box."""
    box = item_box or {}
    brand = (box.get("first_line") or "").strip() or None
    parts = [p.strip() for p in (box.get("second_line") or "").split(SEP) if p.strip()]

    status = size = None
    # El estado es siempre el último fragmento si pertenece al vocabulario.
    if parts and parts[-1] in status_vocab:
        status = parts.pop()
    if parts:
        size = SEP.join(parts)
    return {
        "brand_title": brand,
        "size_title": size,
        "status_title": status,
        "status_id": status_vocab.get(status) if status else None,
    }


def _amount(obj: dict[str, Any] | None) -> float | None:
    return float(obj["amount"]) if obj and obj.get("amount") is not None else None


def normalize_item(raw: dict[str, Any]) -> dict[str, Any]:
    """Aplana un item crudo a los campos que usa el panel (sin datos personales:
    `user` se trata aparte en pseudonymize)."""
    photo = raw.get("photo") or {}
    return {
        "item_id": raw["id"],
        "title": raw.get("title"),
        "url": raw.get("url"),
        "price_amount": _amount(raw.get("price")),
        "currency": (raw.get("price") or {}).get("currency_code"),
        "service_fee": _amount(raw.get("service_fee")),
        "total_item_price": _amount(raw.get("total_item_price")),
        "favourite_count": raw.get("favourite_count"),
        "view_count": raw.get("view_count"),
        "is_promoted": bool(raw.get("promoted")),
        "content_source": raw.get("content_source"),
        "is_business_seller": (raw.get("user") or {}).get("business"),
        "photo_id": (photo.get("high_resolution") or {}).get("id"),
        "photo_url": photo.get("url"),
        "n_photos": len(raw.get("photos") or []),
        **parse_item_box(raw.get("item_box")),
    }
