"""Fase 0 – Probe.

Usos:
    # 1 página de la categoría del scope, JSON crudo a data/raw/
    python scripts/probe.py

    # Otra categoría / varias páginas
    python scripts/probe.py --catalog-id 2630 --pages 3

    # Además, descargar el árbol de categorías y las facetas de estado
    python scripts/probe.py --tree --facets

    # Medir tolerancia: N peticiones seguidas al ritmo configurado
    python scripts/probe.py --tolerance 150 --delay 4

Los JSON crudos contienen datos personales (user.id, user.login): data/ está
en .gitignore y deben borrarse tras validar el pipeline.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vinted_panel.catalog import extract_catalog_tree, flatten_tree, leaf_ids_under  # noqa: E402
from vinted_panel.client import MAX_PAGES, BlockedError, VintedClient  # noqa: E402
from vinted_panel.config import ROOT, http_from_scope, load_scope, market_from_scope  # noqa: E402
from vinted_panel.normalize import normalize_item  # noqa: E402

RAW = ROOT / "data" / "raw"


def save_json(obj, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  -> {path.relative_to(ROOT)}")


def ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def probe_pages(client: VintedClient, catalog_id: int, pages: int, order: str, run: str) -> None:
    """Descarga `pages` páginas y guarda cada respuesta con su contexto de petición."""
    for page in range(1, pages + 1):
        data = client.catalog_items(catalog_ids=catalog_id, page=page, order=order)
        envelope = {
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "market": client.market.code,
            "endpoint": "/svc-catalogue/items",
            "params": {"catalog_id": catalog_id, "page": page, "per_page": 96, "order": order},
            "response": data,
        }
        save_json(envelope, RAW / client.market.code / f"probe_{run}_cat{catalog_id}_p{page}.json")
        pag = data.get("pagination", {})
        print(f"  página {page}: {len(data['items'])} items, pagination={pag}")
        if page >= pag.get("total_pages", 0):
            break

    # Resumen legible del primer item, ya normalizado (sin user).
    first = data["items"][0]
    print("\nClaves raíz:", sorted(data))
    print("Claves de item:", sorted(first))
    print("Item normalizado:", json.dumps(normalize_item(first), ensure_ascii=False, indent=1))


def probe_tree(client: VintedClient) -> None:
    html = client.get_html("/catalog")
    tree = extract_catalog_tree(html)
    flat = list(flatten_tree(tree))
    save_json(tree, RAW / f"catalog_tree_{client.market.code}.json")
    save_json(flat, RAW / f"catalog_flat_{client.market.code}.json")
    print(f"  árbol: {len(flat)} nodos, {sum(r['is_leaf'] for r in flat)} hojas")


def probe_facets(client: VintedClient, catalog_id: int) -> None:
    for code in ("status", "brand", "size", "color", "material"):
        data = client.facets(code, catalog_ids=catalog_id)
        save_json(data, RAW / client.market.code / f"facets_{code}_cat{catalog_id}.json")


def probe_tolerance(client: VintedClient, n: int, root_catalog: int, order: str) -> None:
    """N peticiones seguidas recorriendo páginas 1..10 de las hojas de una categoría.

    No reintenta agresivamente: un BlockedError corta la prueba y se informa
    de cuántas peticiones se llevaban.
    """
    flat_path = RAW / f"catalog_flat_{client.market.code}.json"
    leaves = [root_catalog]
    if flat_path.exists():
        leaves = leaf_ids_under(json.loads(flat_path.read_text()), root_catalog) or leaves
    t0 = time.monotonic()
    done = 0
    try:
        while done < n:
            for cat in leaves:
                for page in range(1, MAX_PAGES + 1):
                    if done >= n:
                        break
                    data = client.catalog_items(catalog_ids=cat, page=page, order=order)
                    done += 1
                    if page >= data["pagination"]["total_pages"]:
                        break
                if done >= n:
                    break
    except BlockedError as e:
        print(f"  BLOQUEADO tras {done} peticiones OK: {e}")
    elapsed = time.monotonic() - t0
    s = client.stats
    print(
        f"\nTolerancia: {done} peticiones OK en {elapsed:.0f}s "
        f"({done / max(elapsed, 1) * 60:.1f}/min). Status: {s.by_status}, "
        f"reintentos: {s.retries}, warm-ups: {s.warmups}"
    )


def main() -> None:
    scope = load_scope()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--market", default=scope["probe"]["market"])
    ap.add_argument("--catalog-id", type=int, default=scope["probe"]["catalog_id"])
    ap.add_argument("--order", default=scope["probe"]["order"])
    ap.add_argument("--pages", type=int, default=1)
    ap.add_argument("--tree", action="store_true", help="descargar árbol de categorías")
    ap.add_argument("--facets", action="store_true", help="descargar facetas de la categoría")
    ap.add_argument("--tolerance", type=int, default=0, help="N peticiones para medir tolerancia")
    ap.add_argument("--delay", type=float, default=None, help="fija min=max delay (s)")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    http = http_from_scope(scope)
    if args.delay is not None:
        http.min_delay_s = http.max_delay_s = args.delay
    client = VintedClient(market_from_scope(scope, args.market), http)
    run = ts()

    if args.tree:
        probe_tree(client)
    probe_pages(client, args.catalog_id, args.pages, args.order, run)
    if args.facets:
        probe_facets(client, args.catalog_id)
    if args.tolerance:
        probe_tolerance(client, args.tolerance, args.catalog_id, args.order)
    print(f"\nEstadísticas: {client.stats}")


if __name__ == "__main__":
    main()
