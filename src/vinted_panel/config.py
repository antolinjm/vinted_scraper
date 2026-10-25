"""Carga de config/scope.yaml."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .client import HttpConfig, Market

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCOPE = ROOT / "config" / "scope.yaml"


def load_scope(path: Path | str = DEFAULT_SCOPE) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def market_from_scope(scope: dict[str, Any], code: str) -> Market:
    m = scope["markets"][code]
    return Market(code=code, web=m["web"], api=m["api"], locale=m["locale"], currency=m.get("currency", "EUR"))


def http_from_scope(scope: dict[str, Any]) -> HttpConfig:
    return HttpConfig.from_dict(scope.get("http", {}))
