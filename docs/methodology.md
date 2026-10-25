# Decisiones metodológicas

Registro vivo de decisiones que afectan a la validez del dataset. Cada entrada:
fecha, decisión, motivo, implicaciones para el análisis. Irá a la memoria del TFM.

## Base legal y ética

- Los términos de Vinted prohíben el acceso automatizado. La base para la recogida es la
  excepción de minería de textos y datos con fines de investigación científica
  (art. 3 Directiva (UE) 2019/790; transposición española en el TRLPI). **Pendiente**:
  validación con la dirección del TFM y, si procede, con el comité de ética.
- RGPD: `user.id` se pseudonimiza en captura (`seller_hash = sha256(sal + user_id)`,
  sal en `VINTED_PANEL_SALT`, fuera del repo). `user.login` no se guarda en el panel.
  Los JSON crudos de `data/raw/` sí lo contienen: se borran tras validar el pipeline y nunca van a git.
- Ritmo: 1 petición cada 3–6 s con jitter, sin rotación de proxies ni evasión agresiva.
  Ante bloqueo persistente el cliente se detiene (`BlockedError`) en lugar de forzar.

## Decisiones

### 2026-10-25 · Endpoint y fuente de datos
- **Decisión**: usar `api.vinted.es/svc-catalogue/items` (el endpoint que usa la web). El endpoint
  de detalle se descarta (404/403).
- **Implicación**: solo se observan los campos del listado. No hay descripción, fecha de
  publicación, nº de fotos completo ni país del vendedor.

### 2026-10-25 · Fecha de publicación
- **Hallazgo**: no hay timestamp de foto ni de publicación en el listado.
- **Decisión**: (a) `first_seen_at` como fecha de entrada observada; para items captados con
  `newest_first` en ventanas cortas, `first_seen_at` ≈ publicación. (b) Calibrar una función
  monótona `item_id → fecha` con los items captados al publicarse (el id es creciente), y usarla
  como proxy para el stock preexistente al inicio del panel (left-censoring).
- **Implicación**: los items vivos al arrancar el panel tienen antigüedad estimada, no observada;
  en análisis de supervivencia tratarlos como truncados por la izquierda o excluirlos.

### 2026-10-25 · Definición de mercado
- **Hallazgo**: el catálogo de vinted.es incluye anuncios de vendedores de otros países de la UE
  (títulos en francés, italiano, neerlandés…).
- **Decisión**: `market` = dominio desde el que se observa (oferta visible para un comprador en
  ese país), no país del vendedor. El precio observado es el mismo en todos los dominios
  (pendiente de verificar con el mismo item en .es y .fr).
- **Implicación**: una comparativa entre países no puede basarse en "anuncios de .es vs .fr" sin
  antes medir el solapamiento de ids entre dominios. Si el pool es común, la dimensión país
  pasa a ser el idioma del título (proxy de origen) o se abandona.

### 2026-10-25 · Atributos de producto
- **Hallazgo**: marca, talla y estado solo vienen como texto (`item_box`).
- **Decisión**: parsear `item_box` con el vocabulario cerrado de estados (cobertura 100 % en la
  muestra). Guardar también el texto bruto para re-parsear si cambia el formato.
- **Validación pendiente**: comparar el estado parseado con el filtro `attribute_ids[status]` en
  una muestra (el filtro da la verdad terreno).

### 2026-10-25 · Cobertura y sharding
- **Hallazgo**: `total_entries` está capado a 960 y es exacto solo por debajo; las facetas dan
  conteos inconsistentes.
- **Decisión**: un shard es *completo* si `total_entries < 960` y se recorren todas sus
  `total_pages`. Si vale 960, se parte (precio → estado). Las 10 categorías hoja de
  Hombre > Calzado devuelven 960 → todas requieren sharding.
- **Implicación**: `disappeared` solo se evalúa sobre items cuyo shard fue completo en la ejecución.

### 2026-10-25 · Solapes de paginación
- **Hallazgo**: ~5 % de ids repetidos entre páginas con `newest_first` (anuncios nuevos empujan la lista).
- **Decisión**: deduplicar por `item_id` dentro del snapshot; registrar la tasa de duplicados por
  shard como indicador de calidad. Mantener los shards pequeños para minimizar el tiempo de recorrido.

### 2026-10-25 · Anuncios promocionados
- **Hallazgo**: la API inyecta items con `content_source = catalog_promoted_items`.
- **Verificado**: los promocionados respetan los filtros del shard (3/3 en un shard estrecho).
- **Decisión**: guardar `is_promoted` y `content_source`; cuentan para la cobertura con normalidad.

### 2026-10-25 · view_count
- **Hallazgo**: `view_count` = 0 en el 100 % de items, también en anuncios de varios días.
- **Decisión**: se excluye del panel. Las señales de demanda quedan en `favourite_count`.
  La pregunta de investigación sobre visitas se reformula solo con favoritos.

## Tolerancia del sitio (probe, 2026-10-25)

150 peticiones seguidas a 1 req/4 s: 150 × 200, sin 429 ni reintentos. Challenges de
Cloudflare esporádicos, resueltos con sesión nueva. Se mantiene 3–6 s con jitter: holgura
suficiente sin acercarse al límite. Capacidad ≈ 800 peticiones/h.
