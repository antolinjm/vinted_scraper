# vinted-panel

Panel longitudinal de precios en Vinted (TFM → posible doctorado): snapshots diarios
del catálogo para estudiar rebajas, tiempo en mercado y salida del catálogo.

## Estado

- Fase 0 (probe) hecha el 2026-10-25. Esquema real en `docs/schema.md`.
- Modelo de datos propuesto: `docs/data_model.md`. Decisiones: `docs/methodology.md`.
- Siguiente: Fase 1 → `sharding.py`, `collector.py`, `storage.py`, `events.py`.

## Hechos clave de la API (ver docs/schema.md)

- Listado: `GET https://api.vinted.es/svc-catalogue/items` con `attribute_ids[catalog|brand|status|size]`,
  `price_from`, `price_to`, `order`, `page` (1..10), `per_page` (≤ 96).
- Cabeceras obligatorias: `platform: web`, `locale`, `Origin`. Cookies de `GET /` (warm-up).
- `total_entries` capado a 960 (exacto solo si < 960). Facetas: conteos no fiables.
- Marca/talla/estado solo como texto en `item_box` → `normalize.parse_item_box`.
- Sin fecha de publicación ni timestamp de foto. Sin `catalog_id` por item.

## Comandos

```bash
pip install -e .[dev]
pytest
python scripts/probe.py --tree --facets          # probe + árbol + facetas
python scripts/probe.py --tolerance 150 --delay 4
```

En entornos con proxy de inspección TLS: `export VINTED_CA_BUNDLE=/ruta/ca-bundle.crt`.

## Reglas

- Python 3.11+, `curl_cffi`, `pandas`/`pyarrow`, `pyyaml`. Funciones pequeñas y testeables.
- Configuración en `config/scope.yaml`; nada hardcodeado.
- Toda decisión metodológica (umbrales, ventanas, definiciones) va a `docs/methodology.md`.
- Ritmo 3–6 s/petición con jitter. Ante bloqueo persistente parar (`BlockedError`); no rotar proxies.
- RGPD: `seller_hash = sha256(VINTED_PANEL_SALT + user_id)`; nunca guardar `login` en el panel.
  `data/` fuera de git; borrar JSON crudos tras validar.
