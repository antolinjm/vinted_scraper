"""Árbol de categorías.

No hay endpoint JSON público para el árbol: la web lo embebe en el payload
RSC (Next.js) de la página /catalog, bajo la clave `catalogTree`, como lista
anidada de nodos {id, title, url, catalogs: [...]}.
"""

from __future__ import annotations

import json
from typing import Any, Iterator

TREE_KEY = '"catalogTree":'


def extract_catalog_tree(html: str) -> list[dict[str, Any]]:
    """Extrae `catalogTree` del HTML de /catalog.

    El payload RSC va serializado dentro de strings JS, con las comillas
    escapadas (\\"). Se desescapan y se decodifica el primer valor JSON
    que sigue a la clave.
    """
    text = html.replace('\\"', '"')
    start = text.find(TREE_KEY)
    if start < 0:
        raise ValueError("No se encontró catalogTree en el HTML (¿cambió la web?)")
    pos = start + len(TREE_KEY)
    while text[pos].isspace():  # raw_decode no admite espacios iniciales
        pos += 1
    tree, _ = json.JSONDecoder().raw_decode(text, pos)
    return tree


def flatten_tree(
    nodes: list[dict[str, Any]], parent_id: int | None = None, path: tuple[str, ...] = ()
) -> Iterator[dict[str, Any]]:
    """Recorre el árbol en profundidad y emite una fila plana por nodo."""
    for n in nodes:
        p = path + (n["title"],)
        children = n.get("catalogs") or []
        yield {
            "catalog_id": n["id"],
            "parent_id": parent_id,
            "title": n["title"],
            "path": " > ".join(p),
            "depth": len(p) - 1,
            "is_leaf": not children,
            "url": n.get("url"),
        }
        yield from flatten_tree(children, n["id"], p)


def leaf_ids_under(flat: list[dict[str, Any]], root_id: int) -> list[int]:
    """Ids hoja descendientes de `root_id` (o el propio si ya es hoja).

    Útil para asignar `catalog_id` a cada item: la API no lo devuelve, así
    que se hereda del shard. Consultando por hoja, el catalog_id es exacto.
    """
    children: dict[int | None, list[dict[str, Any]]] = {}
    for row in flat:
        children.setdefault(row["parent_id"], []).append(row)
    by_id = {r["catalog_id"]: r for r in flat}
    out, stack = [], [by_id[root_id]]
    while stack:
        node = stack.pop()
        if node["is_leaf"]:
            out.append(node["catalog_id"])
        else:
            stack.extend(children.get(node["catalog_id"], []))
    return sorted(out)
