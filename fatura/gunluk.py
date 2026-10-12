"""Uygulama günlüğü: `uygulama.log`.

Uygulama penceresiz çalıştığı için beklenmeyen hatalar hiçbir yere
düşmüyordu; "bazen bir şey oldu" denildiğinde bakılacak iz yoktu. Hatalar
ayrıntısıyla, yapılan işlemler birer satırla buraya yazılıyor.

Müşteri adı, adresi, telefonu günlüğe yazılmaz; sipariş ve belge numarası
yeterli.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from . import config

kayit = logging.getLogger("fatura")
kayit.setLevel(logging.INFO)
kayit.propagate = False

_isleyici: RotatingFileHandler | None = None


def kur() -> None:
    """Günlük dosyasını veri klasöründe açar. Yeniden çağrılabilir."""
    global _isleyici
    if _isleyici is not None:
        return
    try:
        _isleyici = RotatingFileHandler(
            config.veri_klasoru() / "uygulama.log",
            maxBytes=1_000_000, backupCount=2, encoding="utf-8",
        )
    except OSError:
        # Günlük yazılamıyorsa uygulama yine de çalışmalı.
        return
    _isleyici.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    kayit.addHandler(_isleyici)
