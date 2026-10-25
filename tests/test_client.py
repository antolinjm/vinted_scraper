"""Tests del cliente con una sesión falsa (sin red)."""

import pytest

from vinted_panel.client import (
    BlockedError,
    HttpConfig,
    Market,
    VintedClient,
    VintedError,
    build_catalog_params,
)

MARKET = Market(code="es", web="https://www.vinted.es", api="https://api.vinted.es", locale="es-ES")


class FakeResp:
    def __init__(self, status, payload=None, headers=None, text=""):
        self.status_code = status
        self._payload = payload
        self.headers = headers or {}
        self.text = text

    def json(self):
        return self._payload


class FakeCookies(dict):
    pass


class FakeSession:
    """Devuelve respuestas de una cola compartida; registra las URLs pedidas."""

    def __init__(self, script, calls):
        self.script = script
        self.calls = calls
        self.cookies = FakeCookies(access_token_web="tok")

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, params))
        return self.script.pop(0)


def make_client(script, **http):
    calls, sleeps = [], []
    cfg = HttpConfig(min_delay_s=0, max_delay_s=0, backoff_base_s=30, max_retries=3, warmup_retry_s=8, **http)
    client = VintedClient(MARKET, cfg, session_factory=lambda: FakeSession(script, calls), sleep=sleeps.append)
    return client, calls, sleeps


HOME_OK = FakeResp(200)
PAGE = {"items": [{"id": 1}], "pagination": {"total_entries": 1, "total_pages": 1}}


def test_happy_path_warms_up_then_fetches():
    client, calls, _ = make_client([HOME_OK, FakeResp(200, PAGE)])
    assert client.catalog_items(catalog_ids=1242) == PAGE
    assert calls[0][0] == "https://www.vinted.es/"
    assert calls[1][0] == "https://api.vinted.es/svc-catalogue/items"
    assert calls[1][1]["attribute_ids[catalog]"] == "1242"


def test_warmup_retries_on_cloudflare_challenge():
    challenge = FakeResp(403, headers={"cf-mitigated": "challenge"})
    client, _, sleeps = make_client([challenge, HOME_OK, FakeResp(200, PAGE)])
    client.catalog_items(catalog_ids=1)
    assert client.stats.warmups == 2
    assert sleeps == [8]


def test_429_uses_exponential_backoff():
    client, _, sleeps = make_client([HOME_OK, FakeResp(429), FakeResp(429), FakeResp(200, PAGE)])
    client.catalog_items(catalog_ids=1)
    assert sleeps == [30, 60]


def test_401_renews_session_without_long_backoff():
    client, calls, sleeps = make_client([HOME_OK, FakeResp(401), HOME_OK, FakeResp(200, PAGE)])
    client.catalog_items(catalog_ids=1)
    assert sleeps == []
    assert [u for u, _ in calls].count("https://www.vinted.es/") == 2


def test_persistent_block_raises_and_stops():
    client, _, sleeps = make_client([HOME_OK] + [FakeResp(429)] * 4)
    with pytest.raises(BlockedError):
        client.catalog_items(catalog_ids=1)
    assert sleeps == [30, 60, 120]


def test_400_is_not_retried():
    client, calls, _ = make_client([HOME_OK, FakeResp(400, text="Invalid request")])
    with pytest.raises(VintedError):
        client.catalog_items(catalog_ids=1)
    assert len(calls) == 2


def test_page_above_api_cap_rejected_locally():
    client, calls, _ = make_client([])
    with pytest.raises(ValueError):
        client.catalog_items(catalog_ids=1, page=11)
    assert calls == []


def test_build_params_uses_attribute_ids_and_drops_nones():
    p = build_catalog_params(catalog_ids=[1, 2], status_ids=[6], price_from=10, price_to=12, currency="EUR", page=1)
    assert p == {
        "page": 1,
        "price_from": 10,
        "price_to": 12,
        "currency": "EUR",
        "attribute_ids[catalog]": "1,2",
        "attribute_ids[status]": "6",
    }
