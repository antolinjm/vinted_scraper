from vinted_panel.normalize import normalize_item, parse_item_box


def test_brand_size_status():
    out = parse_item_box({"first_line": "Nike", "second_line": "42,5 · Muy bueno"})
    assert out == {"brand_title": "Nike", "size_title": "42,5", "status_title": "Muy bueno", "status_id": 2}


def test_no_size_category():
    out = parse_item_box({"first_line": "Zara", "second_line": "Nuevo con etiquetas"})
    assert out["size_title"] is None and out["status_id"] == 6


def test_missing_brand_and_unknown_status_kept_as_size():
    out = parse_item_box({"first_line": "", "second_line": "M"})
    assert out == {"brand_title": None, "size_title": "M", "status_title": None, "status_id": None}


def test_normalize_item_drops_personal_fields():
    raw = {
        "id": 10,
        "title": "Zapatillas",
        "price": {"amount": "80.00", "currency_code": "EUR"},
        "service_fee": {"amount": "4.70", "currency_code": "EUR"},
        "total_item_price": {"amount": "84.70", "currency_code": "EUR"},
        "promoted": True,
        "user": {"id": 99, "login": "someone", "business": False},
        "photo": {"high_resolution": {"id": "abc"}, "url": "u"},
        "photos": [{}, {}],
        "item_box": {"first_line": "Nike", "second_line": "43 · Bueno"},
    }
    out = normalize_item(raw)
    assert out["price_amount"] == 80.0 and out["total_item_price"] == 84.7
    assert out["is_promoted"] is True and out["n_photos"] == 2 and out["status_id"] == 3
    assert "login" not in str(out) and 99 not in out.values()
