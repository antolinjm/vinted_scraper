"""Cliente HTTP para la API interna de Vinted.

Responsabilidades:
- Sesión `curl_cffi` que imita la huella TLS/HTTP2 de Chrome (Cloudflare).
- Warm-up en la home para obtener las cookies anónimas (`access_token_web`, ...).
- Ritmo conservador con jitter entre peticiones.
- Reintentos con backoff exponencial ante 401/403/429/5xx; si persiste, se para.
- Log de cada petición (status, latencia, items devueltos).

Endpoints confirmados (oct-2026, ver docs/schema.md):
- Listado:  GET {api}/svc-catalogue/items
- Facetas:  GET {api}/svc-filters/filters/facets?filter_code=...
"""

from __future__ import annotations

import logging
import os
import random
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from curl_cffi import requests

log = logging.getLogger(__name__)

# Estados HTTP que justifican reintentar (con backoff). 400/404 son errores
# de la petición: reintentar no sirve, se propagan inmediatamente.
RETRYABLE = {401, 403, 429, 500, 502, 503, 504}

# Tope duro de la API: 10 páginas x 96. Pedir la página 11 devuelve 400.
MAX_PER_PAGE = 96
MAX_PAGES = 10


class VintedError(RuntimeError):
    """Error no recuperable de la API (petición inválida, ruta inexistente)."""


class BlockedError(RuntimeError):
    """Se agotaron los reintentos: Vinted está bloqueando o limitando. Parar."""


@dataclass
class HttpConfig:
    min_delay_s: float = 3.0
    max_delay_s: float = 6.0
    backoff_base_s: float = 30.0
    max_retries: int = 5
    warmup_retries: int = 5
    warmup_retry_s: float = 8.0
    timeout_s: float = 30.0

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "HttpConfig":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class Market:
    code: str
    web: str
    api: str
    locale: str
    currency: str = "EUR"


@dataclass
class RequestStats:
    """Contadores de la ejecución; sirven para medir la tolerancia del sitio."""

    requests: int = 0
    by_status: dict[int, int] = field(default_factory=dict)
    retries: int = 0
    warmups: int = 0

    def record(self, status: int) -> None:
        self.requests += 1
        self.by_status[status] = self.by_status.get(status, 0) + 1


def _ca_bundle() -> str | bool:
    """CA para verificar TLS. En entornos con proxy de inspección TLS hay que
    apuntar a su bundle; en local basta el almacén por defecto (True)."""
    for var in ("VINTED_CA_BUNDLE", "REQUESTS_CA_BUNDLE", "SSL_CERT_FILE", "CURL_CA_BUNDLE"):
        path = os.environ.get(var)
        if path and os.path.exists(path):
            return path
    return True


def _is_cf_challenge(resp: requests.Response) -> bool:
    """Cloudflare marca sus challenges con la cabecera `cf-mitigated`."""
    return resp.headers.get("cf-mitigated") == "challenge"


class VintedClient:
    """Cliente con rate limit y backoff. Una instancia por mercado."""

    def __init__(
        self,
        market: Market,
        http: HttpConfig | None = None,
        session_factory: Callable[[], Any] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.market = market
        self.http = http or HttpConfig()
        # Inyectables para tests (sesión falsa y sleep instantáneo).
        self._session_factory = session_factory or self._new_session
        self._sleep = sleep
        self._session = None
        self._last_request_at = 0.0
        self.stats = RequestStats()

    # ------------------------------------------------------------------ sesión

    @staticmethod
    def _new_session():
        return requests.Session(impersonate="chrome", verify=_ca_bundle())

    def _api_headers(self) -> dict[str, str]:
        """Cabeceras que envía la web en sus XHR. Sin `platform`/`locale`/`Origin`
        la API responde 403 aunque las cookies sean válidas."""
        return {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": self.market.locale,
            "Origin": self.market.web,
            "Referer": self.market.web + "/",
            "platform": "web",
            "locale": self.market.locale,
            "x-next-app": "marketplace-web",
        }

    def warm_up(self) -> None:
        """Crea una sesión nueva y visita la home para obtener cookies anónimas.

        Cloudflare devuelve a veces un challenge (403) en la primera visita;
        se reintenta con una sesión limpia tras una espera corta.
        """
        for attempt in range(1, self.http.warmup_retries + 1):
            self._session = self._session_factory()
            self.stats.warmups += 1
            self._throttle()
            resp = self._session.get(
                self.market.web + "/",
                headers={"Accept-Language": self.market.locale},
                timeout=self.http.timeout_s,
            )
            self.stats.record(resp.status_code)
            if resp.status_code == 200 and self._session.cookies.get("access_token_web"):
                log.info("warm-up ok (intento %d)", attempt)
                return
            log.warning(
                "warm-up fallido: status=%s challenge=%s (intento %d)",
                resp.status_code, _is_cf_challenge(resp), attempt,
            )
            self._sleep(self.http.warmup_retry_s * attempt)
        raise BlockedError("No se pudo obtener sesión anónima tras el warm-up")

    # ------------------------------------------------------------ rate limit

    def _throttle(self) -> None:
        """Espera hasta cumplir el intervalo mínimo (con jitter) desde la última petición."""
        wait = random.uniform(self.http.min_delay_s, self.http.max_delay_s)
        elapsed = time.monotonic() - self._last_request_at
        if self._last_request_at and elapsed < wait:
            self._sleep(wait - elapsed)
        self._last_request_at = time.monotonic()

    # -------------------------------------------------------------- peticiones

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """GET a la API con reintentos. Devuelve el JSON o lanza VintedError/BlockedError."""
        resp = self._request(self.market.api + path, params, self._api_headers())
        data = resp.json()
        if isinstance(data, dict) and "items" in data:
            log.info("  items=%d pagination=%s", len(data["items"]), data.get("pagination"))
        return data

    def get_html(self, path: str, params: dict[str, Any] | None = None) -> str:
        """GET a una página de la web (p.ej. /catalog para el árbol de categorías)."""
        headers = {"Accept-Language": self.market.locale}
        return self._request(self.market.web + path, params, headers).text

    def _request(self, url: str, params: dict[str, Any] | None, headers: dict[str, str]):
        """GET con rate limit y reintentos. Devuelve la respuesta 200."""
        if self._session is None:
            self.warm_up()
        path = url.split("://", 1)[-1].split("/", 1)[-1]
        params = {k: v for k, v in (params or {}).items() if v is not None}

        for attempt in range(self.http.max_retries + 1):
            self._throttle()
            t0 = time.monotonic()
            resp = self._session.get(url, params=params, headers=headers, timeout=self.http.timeout_s)
            latency = time.monotonic() - t0
            self.stats.record(resp.status_code)

            if resp.status_code == 200:
                log.info("GET /%s status=200 latency=%.2fs params=%s", path, latency, params)
                return resp

            log.warning(
                "GET /%s status=%s latency=%.2fs challenge=%s body=%r",
                path, resp.status_code, latency, _is_cf_challenge(resp), resp.text[:120],
            )
            if resp.status_code not in RETRYABLE:
                raise VintedError(f"{resp.status_code} en /{path}: {resp.text[:200]}")
            if attempt == self.http.max_retries:
                break

            self.stats.retries += 1
            if resp.status_code == 401:
                # Token anónimo caducado: renovar sin esperar el backoff largo.
                self.warm_up()
                continue
            delay = self.http.backoff_base_s * (2**attempt)
            log.warning("backoff %.0fs (reintento %d/%d)", delay, attempt + 1, self.http.max_retries)
            self._sleep(delay)
            if resp.status_code == 403:
                # 403 suele indicar cookie/clearance inválida: sesión nueva.
                self.warm_up()

        raise BlockedError(f"Reintentos agotados en /{path} (último status {resp.status_code})")

    # ---------------------------------------------------------------- catálogo

    def catalog_items(
        self,
        catalog_ids: list[int] | int | None = None,
        page: int = 1,
        per_page: int = MAX_PER_PAGE,
        order: str = "newest_first",
        price_from: float | None = None,
        price_to: float | None = None,
        brand_ids: list[int] | None = None,
        status_ids: list[int] | None = None,
        size_ids: list[int] | None = None,
        search_text: str | None = None,
    ) -> dict[str, Any]:
        """Una página del listado. Respuesta: {items, pagination, search_tracking_params}."""
        if not 1 <= page <= MAX_PAGES:
            raise ValueError(f"page debe estar en [1, {MAX_PAGES}] (tope de la API)")
        params = build_catalog_params(
            catalog_ids=catalog_ids, page=page, per_page=per_page, order=order,
            price_from=price_from, price_to=price_to, brand_ids=brand_ids,
            status_ids=status_ids, size_ids=size_ids, search_text=search_text,
            currency=self.market.currency,
        )
        return self.get_json("/svc-catalogue/items", params)

    def facets(self, filter_code: str, catalog_ids: list[int] | int | None = None) -> dict[str, Any]:
        """Opciones de un filtro (status, brand, size, color, material) con id y título.

        Ojo: los `items_count` que devuelve NO son fiables para dimensionar
        shards (ver docs/schema.md); úsese solo como diccionario id -> título.
        """
        params = build_catalog_params(catalog_ids=catalog_ids)
        params["filter_code"] = filter_code
        return self.get_json("/svc-filters/filters/facets", params)


def _csv(v: list[int] | int | None) -> str | None:
    if v is None:
        return None
    if isinstance(v, (list, tuple, set)):
        return ",".join(str(x) for x in v) or None
    return str(v)


def build_catalog_params(
    catalog_ids: list[int] | int | None = None,
    page: int | None = None,
    per_page: int | None = None,
    order: str | None = None,
    price_from: float | None = None,
    price_to: float | None = None,
    brand_ids: list[int] | None = None,
    status_ids: list[int] | None = None,
    size_ids: list[int] | None = None,
    search_text: str | None = None,
    currency: str | None = None,
) -> dict[str, Any]:
    """Traduce filtros al formato de la API nueva: `attribute_ids[<tipo>]=id1,id2`."""
    params: dict[str, Any] = {
        "page": page,
        "per_page": per_page,
        "order": order,
        "search_text": search_text,
        "price_from": price_from,
        "price_to": price_to,
        "currency": currency if (price_from is not None or price_to is not None) else None,
        "attribute_ids[catalog]": _csv(catalog_ids),
        "attribute_ids[brand]": _csv(brand_ids),
        "attribute_ids[status]": _csv(status_ids),
        "attribute_ids[size]": _csv(size_ids),
    }
    return {k: v for k, v in params.items() if v is not None}
