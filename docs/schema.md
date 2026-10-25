# Esquema real de la API de Vinted

Validado con el probe del **25-oct-2026** en `vinted.es` (`scripts/probe.py`).
Las capturas crudas están en `data/raw/` (fuera de git, contienen datos personales).

> Vinted cambia su web con frecuencia. Si algo falla, volver a capturar el tráfico
> de la web (Chromium + Playwright, ver "Cómo se descubrió" al final).

## 1. Cambios frente a lo que se suponía

| Supuesto inicial | Realidad |
|---|---|
| `GET www.vinted.es/api/v2/catalog/items` | **404**. Listado en `GET api.vinted.es/svc-catalogue/items` |
| Filtros `catalog_ids`, `brand_ids`, `status_ids`, `size_ids` | `attribute_ids[catalog]`, `attribute_ids[brand]`, `attribute_ids[status]`, `attribute_ids[size]`, `attribute_ids[color]`, `attribute_ids[material]` (ids separados por comas) |
| Basta con la cookie anónima | Además hacen falta las cabeceras `platform: web`, `locale`, `Origin`. Sin ellas → 403 `{"code":"FORBIDDEN"}` |
| `brand_title`, `size_title`, `status` por item | **No existen**. Solo como texto en `item_box` |
| `photo.high_resolution.timestamp` como proxy de publicación | **No existe**. `high_resolution` solo trae `id` y `orientation` |
| `total_entries` = tamaño real | Capado: vale 960 cuando hay ≥ 960. Exacto solo si < 960 |
| `catalog_id` por item | No viene. Hay que heredarlo del shard (consultar por categoría hoja) |
| Árbol de categorías: endpoint por descubrir | Embebido en el HTML de `/catalog` (clave `catalogTree`) |
| Endpoint de detalle utilizable a veces | JSON `/api/v2/items/{id}` → 404; `/details` → 403. Pero la **página HTML** `/items/{id}` da 200 (ver §9) |
| `vinted.es` = anuncios de España | El catálogo muestra un **pool paneuropeo** (títulos en FR/IT/NL…). Ver methodology.md |

## 2. Sesión y cabeceras

1. `GET https://www.vinted.es/` con `curl_cffi` (`impersonate="chrome"`).
   Devuelve las cookies `access_token_web` (JWT anónimo, `scope: public`, caduca a las 24 h),
   `refresh_token_web`, `anon_id`, `v_udt`, `__cf_bm` (dominio `.vinted.es`, por lo que viajan a `api.vinted.es`).
   - Cloudflare responde a veces **403 con `cf-mitigated: challenge`** en esta primera visita.
     Una sesión nueva tras ~8 s lo resuelve (observado ~1 de cada 3 warm-ups).
2. Peticiones a `https://api.vinted.es/...` con:

```
Accept: application/json, text/plain, */*
Accept-Language: es-ES
Origin: https://www.vinted.es
Referer: https://www.vinted.es/
platform: web
locale: es-ES
x-next-app: marketplace-web
```

`x-csrf-token` y `x-anon-id` (los envía la web) **no** son necesarios para lectura.

## 3. Listado: `GET /svc-catalogue/items`

### Parámetros

| parámetro | ejemplo | notas |
|---|---|---|
| `page` | 1..10 | `page=11` → **400** `INVALID_REQUEST` |
| `per_page` | 96 | máximo |
| `order` | `newest_first`, `price_low_to_high`, `price_high_to_low`, `relevance` | |
| `price_from`, `price_to` | 10, 12 | inclusivos; verificado que se aplican |
| `currency` | EUR | |
| `search_text` | | |
| `attribute_ids[catalog]` | 1242 | incluye descendientes si no es hoja |
| `attribute_ids[brand]` | 53 | |
| `attribute_ids[status]` | 6 | ver vocabulario §5 |
| `attribute_ids[size]` | 776 | ids dependen del tipo de talla |
| `time` | epoch | la web lo envía para "congelar" la búsqueda; no elimina los solapes (ver §6) |

### Respuesta raíz

```json
{
  "items": [ ... ],
  "pagination": {"current_page": 1, "per_page": 96, "time": 1792931540,
                 "total_entries": 960, "total_pages": 10},
  "search_tracking_params": {"search_session_id": "...", "search_correlation_id": "...",
                             "global_catalog_browse_session_id": "..."}
}
```

### Item

| campo | tipo | ejemplo | uso en el panel |
|---|---|---|---|
| `id` | int | 10524756859 | clave. Creciente en el tiempo (proxy grueso de antigüedad) |
| `title` | str | "Sneakers Givenchy …" | |
| `url` | str | `/items/10524756859-sneakers-…` | relativa al dominio |
| `price` | `{amount: "80.00", currency_code: "EUR"}` | | **precio** (amount es string) |
| `service_fee` | idem | "4.70" | = 0,70 € + 5 % × precio en toda la muestra → derivable |
| `total_item_price` | idem | "84.70" | price + service_fee |
| `favourite_count` | int | 0 | señal de demanda |
| `view_count` | int | 0 | **siempre 0**, también en anuncios de varios días → anulado por Vinted. Descartar |
| `promoted` | bool | false | anuncio pagado ("Destacado") |
| `content_source` | str | `catalog` / `catalog_promoted_items` | los promocionados inyectados **sí respetan los filtros** del shard (3/3 verificados) |
| `item_box.first_line` | str | "Nike" | **marca** (texto) |
| `item_box.second_line` | str | "43 · Bueno" | **talla · estado** (texto); sin talla en categorías que no la tienen |
| `item_box.accessibility_label` | str | "…, Marca: Nike, Estado: Bueno, Tamaño: 43, 80.00 €, 84.70 €" | alternativa de parseo |
| `photo` | obj | | foto principal: `url` (f800), `full_size_url`, `thumbnails[]`, `width`, `height`, `dominant_color`, `high_resolution.id` |
| `photos` | list | | en el listado solo trae la principal |
| `user` | `{id, login, business}` | | **datos personales**: `id` → `seller_hash`; `login` se descarta; `business` se conserva (profesional vs particular) |
| `is_favourite` | bool | false | relativo al usuario logado → descartar |
| `show_1st_time_seller_discount` | bool | false | conservar (posible covariable de precio) |
| `search_tracking_params.score` | float | 0.0105 | score de ranking; solo con `relevance` |

## 4. Facetas y filtros

- `GET /svc-filters/filters?attribute_ids[catalog]=…` → códigos de filtro disponibles: `size, brand, status, color, price, material`.
- `GET /svc-filters/filters/facets?filter_code=<código>&attribute_ids[catalog]=…` → opciones `{id, title, items_count}`.
- `GET /svc-filters/faceted_categories?attribute_ids[catalog]=…` → subcategorías con `item_count`.

**Los `items_count` NO son fiables**: misma categoría 1231 da 70.435 sin filtro de precio
y 1.360.888 con `price_from=20&price_to=40`. Usarlos solo como diccionario id → título,
nunca para dimensionar shards.

## 5. Vocabulario de estado (`status`)

| id | es-ES |
|---|---|
| 6 | Nuevo con etiquetas |
| 1 | Nuevo sin etiquetas |
| 2 | Muy bueno |
| 3 | Bueno |
| 4 | Satisfactorio |

El parseo de `item_box.second_line` cubrió el 100 % de la muestra (94/94 con estado reconocido).

## 6. Comportamiento de la paginación

- `total_entries < 960` → exacto (p.ej. 341 → 4 páginas). `= 960` → "960 o más".
- Una página puede traer < 96 items aunque haya más páginas (visto: 94). **No usar `len(items) < 96` como fin**; usar `total_pages`.
- Con `newest_first` hay solapes entre páginas consecutivas (~5 % en 5 páginas recorridas en ~15 s),
  causados por anuncios nuevos que desplazan la lista. Deduplicar por `id`.
  El riesgo simétrico (huecos por anuncios que desaparecen) existe pero es menor; se mitiga con shards pequeños.
- `newest_first` no ordena estrictamente por `id` (48 inversiones en 96) → el orden es por fecha de publicación/subida, no de creación del borrador.

## 7. Árbol de categorías

En el HTML de `GET https://www.vinted.es/catalog`, dentro del payload RSC, la clave
`catalogTree` contiene la jerarquía anidada `{id, title, url, catalogs: [...]}`.
2.902 nodos, 2.482 hojas, 9 raíces (Mujer, Hombre, Moda de diseño, Niños, Hogar,
Electrónica, Libros y multimedia, Hobbies y coleccionismo, Deportes).
Se extrae con `vinted_panel.catalog.extract_catalog_tree` → `data/raw/catalog_tree_es.json`.

## 8. Tolerancia (probe 25-oct-2026)

- 150 peticiones seguidas a 1 req/4 s (10 min, 15/min): **150 × 200, 0 reintentos**.
- Unas ~170 peticiones adicionales durante el día a 3,5–6 s: sin 429.
- Cloudflare: challenges (403 + `cf-mitigated: challenge`) esporádicos en el warm-up y uno en la API;
  el cliente los resuelve con espera + sesión nueva.
- Orden de magnitud de capacidad: a 4,5 s medios ≈ 800 peticiones/h ≈ 75.000 items/h brutos.

## 9. Página HTML del item (enriquecimiento opcional)

`GET https://www.vinted.es/items/{id}` → 200 (≈1,7 MB). En el RSC aparecen, entre otros:
`catalog_id`, `brand_id`, `can_buy`, `instant_buy`, `is_reserved`, `is_hidden`,
`feedback_count`/`feedback_reputation` del vendedor. No se encontró fecha de subida.
Útil para: validar `catalog_id`/`brand_id` del parseo, y validar en muestra pequeña si un
item desaparecido está vendido/reservado (pendiente: ver cómo se muestra un item vendido).
Coste alto (1 petición por item): solo muestras.

## 10. Cómo se descubrió

1. `curl_cffi` contra el endpoint antiguo → 404.
2. Chromium (Playwright) cargando `/catalog?catalog[]=1231`, clic en "página 2", registro de XHR:
   aparece `api.vinted.es/svc-catalogue/items` y `svc-filters/*`.
3. Bundle JS de Next.js: función que construye los parámetros (`attribute_ids`, `price_from`, …).
4. Reproducción solo con `curl_cffi` + cabeceras de §2 → 200.
