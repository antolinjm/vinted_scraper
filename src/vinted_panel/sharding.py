"""División recursiva de consultas para saltar el tope de 960 resultados (Fase 1).

Criterio de shard completo (validado en el probe): `pagination.total_entries`
es exacto solo si < 960; si vale 960 significa ">= 960" y hay que partir.
Los `items_count` de las facetas NO sirven para dimensionar (inconsistentes).

Algoritmo previsto:
1. page=1 de (catalog_id hoja [+ marca]) en [price_from, price_to].
2. total_entries < 960 -> paginar hasta total_pages.
3. total_entries == 960 -> partir el rango de precio en dos y recursar.
4. Ancho < min_price_width y aún 960 -> partir por status_ids (5 valores).
5. Deduplicar por item_id; registrar cobertura (completo/incompleto) por shard.
"""
