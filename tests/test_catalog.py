import json

from vinted_panel.catalog import extract_catalog_tree, flatten_tree, leaf_ids_under

TREE = [
    {"id": 5, "title": "Hombre", "url": "/catalog/5", "catalogs": [
        {"id": 1231, "title": "Calzado", "url": "/catalog/1231", "catalogs": [
            {"id": 1242, "title": "Zapatillas", "url": "/catalog/1242", "catalogs": []},
            {"id": 1233, "title": "Botas", "url": "/catalog/1233", "catalogs": []},
        ]},
    ]},
]


def test_extract_from_escaped_rsc_payload():
    # Así aparece en el HTML: JSON serializado dentro de un string JS.
    payload = json.dumps({"catalogTree": TREE, "other": 1}).replace('"', '\\"')
    html = f'<script>self.__next_f.push([1,"{payload}"])</script>'
    assert extract_catalog_tree(html) == TREE


def test_flatten_and_leaves():
    flat = list(flatten_tree(TREE))
    assert len(flat) == 4
    zap = next(r for r in flat if r["catalog_id"] == 1242)
    assert zap["path"] == "Hombre > Calzado > Zapatillas" and zap["depth"] == 2 and zap["parent_id"] == 1231
    assert leaf_ids_under(flat, 5) == [1233, 1242]
    assert leaf_ids_under(flat, 1242) == [1242]
