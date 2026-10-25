# Modelo de datos v2 (ajustado al esquema real)

Propuesta tras el probe del 25-oct-2026. Sustituye a la sección 4 del plan inicial.
Formato: Parquet. Particiones: `market` (+ `snapshot_date` en las tablas de hechos).

## Resumen de cambios

| Cambio | Motivo |
|---|---|
| `photo_ts` → `first_seen_at` + `pub_ts_est` + `is_fresh_listing` | No existe timestamp de foto. Se observa la entrada y se estima la publicación desde el `item_id` |
| `brand_title`, `size_title`, `status` → parseados de `item_box` + texto bruto | La API ya no los da estructurados |
| Nuevo `status_id` | Vocabulario cerrado de 5 estados (ids estables entre idiomas) |
| `brand_id` nullable | Solo se conoce si el shard filtró por marca; si no, solo texto |
| `catalog_id` heredado del shard hoja | La API no lo devuelve. Consultar siempre por hoja lo hace exacto |
| Nuevo `is_business_seller`, `photo_id`, `show_1st_time_seller_discount` | Covariables gratis; `photo_id` permite detectar re-publicaciones |
| `total_item_price` eliminado | = `price + service_fee`. Se mantiene `service_fee` (la tarifa de Vinted puede cambiar: variable de política) |
| `view_count` eliminado | Siempre 0, confirmado también en anuncios antiguos |
| Nuevos `page`, `position`, `content_source` | Visibilidad en el ranking y control de promocionados inyectados |
| `query_shard` (texto) → `shard_id` (FK) + tabla `shards` | La cobertura es la base de `disappeared`; necesita tabla propia |
| Nuevas tablas `runs`, `catalogs`, `id_calibration` | Trazabilidad, dimensión de categorías versionada y estimación de fechas |
| Nuevo evento `relisted` | Borrar y volver a subir un anuncio no es una venta: sin esto `disappeared` sobreestima ventas |

## Tablas

### `items` (dimensión, una fila por `market, item_id`; se actualiza `last_seen_at`)

| campo | tipo | origen |
|---|---|---|
| item_id | int64 | `id` |
| market | str | dominio observado |
| catalog_id | int32 | shard hoja |
| title | str | `title` (primer valor visto) |
| brand_title | str? | `item_box.first_line` |
| brand_id | int32? | shard (si filtró por marca) |
| size_title | str? | `item_box.second_line` (parte izquierda) |
| status_id / status_title | int8? / str? | `item_box.second_line` (último fragmento) |
| item_box_first_line, item_box_second_line | str | texto bruto para re-parsear |
| seller_hash | str | `sha256(sal + user.id)` |
| is_business_seller | bool | `user.business` |
| photo_id | str | `photo.high_resolution.id` |
| photo_url | str | `photo.url` |
| url | str | `url` |
| first_seen_at / last_seen_at | timestamp | panel |
| is_fresh_listing | bool | visto por primera vez en las primeras páginas de `newest_first` con `first_seen_at - snapshot anterior` < 24 h |
| pub_ts_est | timestamp | calibración `item_id → fecha` (ver `id_calibration`) |
| attrs_hash | str | hash de título+marca+talla+estado: detecta ediciones |

### `snapshots` (hechos, una fila por item y ejecución)

| campo | tipo | notas |
|---|---|---|
| snapshot_id | str | id de ejecución (FK `runs`) |
| fetched_at | timestamp | momento de la página, no de la ejecución |
| market, item_id | | clave |
| shard_id | str | FK `shards` |
| price_amount | decimal(10,2) | |
| currency | str | |
| service_fee | decimal(10,2) | |
| favourite_count | int32 | señal de demanda |
| is_promoted | bool | `promoted` |
| content_source | str | `catalog` / `catalog_promoted_items` |
| page, position | int8, int8 | posición en el ranking |
| show_1st_time_seller_discount | bool | |
| attrs_hash | str | para detectar cambios de atributos |

### `shards` (cobertura, una fila por shard y ejecución)

| campo | notas |
|---|---|
| snapshot_id, shard_id | `shard_id` = hash de los filtros |
| catalog_id, price_from, price_to, status_id, brand_id | filtros |
| order | |
| total_entries | < 960 → exacto |
| pages_fetched, items_returned, unique_items | |
| dup_rate | 1 − unique/returned: indicador de calidad |
| is_complete | `total_entries < 960` y se recorrieron todas las páginas |
| started_at, finished_at | |

### `runs` (una fila por ejecución)

`snapshot_id, market, started_at, finished_at, n_requests, status_counts (json), blocked (bool), code_version (git sha), scope_hash`.

### `catalogs` (dimensión versionada)

`catalog_id, parent_id, title, path, depth, is_leaf, valid_from, valid_to`. El árbol cambia; versionarlo evita reasignar categorías retroactivamente.

### `id_calibration`

`item_id, first_seen_at` de los items `is_fresh_listing`. Se ajusta una función monótona
(isotónica) `item_id → fecha` para estimar `pub_ts_est` del stock preexistente.

## Eventos (derivados de `snapshots` + `shards`)

| evento | regla |
|---|---|
| `listed_fresh` | primera aparición con `is_fresh_listing` |
| `listed_stock` | primera aparición sin serlo (stock previo al panel o categoría recién añadida): left-censored |
| `price_drop` / `price_increase` | cambio de `price_amount` entre snapshots consecutivos del item: precio anterior, nuevo, Δ%, días desde `first_seen_at` / `pub_ts_est` |
| `attrs_changed` | cambia `attrs_hash` (título, estado…) |
| `promoted_on` / `promoted_off` | cambio de `is_promoted` |
| `disappeared` | ausente en N snapshots consecutivos **y** todos los shards de su `catalog_id` completos en esos snapshots (ver nota) |
| `reappeared` | vuelve tras `disappeared`: falso positivo, se usa para calibrar N |
| `relisted` | tras `disappeared`, aparece un `item_id` nuevo con mismo `seller_hash` y mismo `photo_id` (o título+marca+talla) en ≤ 14 días: re-publicación, no venta |

**Nota sobre cobertura**: los shards se parten por precio, así que una rebaja mueve el item a otro
shard. Por eso la condición de `disappeared` se evalúa a nivel de categoría hoja (todos sus shards
completos), no del shard donde se vio por última vez.

**N inicial**: 2 snapshots diarios consecutivos. Calibrar con la tasa de `reappeared`.

## Variable dependiente para el TFM

`sold_proxy = disappeared ∧ ¬relisted ∧ ¬reappeared`. Sigue mezclando ventas con retiradas
definitivas; documentarlo como limitación y, si es posible, validar en una muestra pequeña
contra la página pública del item (muestra "Vendido") con muy bajo volumen.
