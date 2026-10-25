"""Pseudonimización de vendedores: seller_hash = sha256(salt + user_id).

La sal se lee de la variable de entorno VINTED_PANEL_SALT y nunca va al repo.
No se guarda `user.login` (dato personal identificable).
"""

from __future__ import annotations

import hashlib
import os


def seller_hash(user_id: int | str, salt: str | None = None) -> str:
    salt = salt if salt is not None else os.environ.get("VINTED_PANEL_SALT")
    if not salt:
        raise RuntimeError("Define VINTED_PANEL_SALT para pseudonimizar vendedores")
    return hashlib.sha256(f"{salt}{user_id}".encode()).hexdigest()
