"""Ortam değişkenlerinden okunan ayarlar."""

import os
from pathlib import Path

from dotenv import load_dotenv

KOK = Path(__file__).resolve().parent.parent
load_dotenv(KOK / ".env")


def _bool(anahtar: str, varsayilan: bool) -> bool:
    ham = os.getenv(anahtar)
    if ham is None or ham.strip() == "":
        return varsayilan
    return ham.strip().lower() in {"1", "true", "evet", "yes", "on"}


SHOPIFY_STORE = os.getenv("SHOPIFY_STORE", "").strip()
SHOPIFY_TOKEN = os.getenv("SHOPIFY_TOKEN", "").strip()
SHOPIFY_API_SURUMU = "2025-07"

GIB_KULLANICI_KODU = os.getenv("GIB_KULLANICI_KODU", "").strip()
GIB_SIFRE = os.getenv("GIB_SIFRE", "").strip()
GIB_TEST_MODU = _bool("GIB_TEST_MODU", True)

KDV_ORANI = int(os.getenv("KDV_ORANI", "20"))
KARGOYU_DAGIT = _bool("KARGOYU_DAGIT", True)
FATURA_NOTU = os.getenv("FATURA_NOTU", "").strip()

# Test ve gerçek kayıtlar ayrı dosyalarda tutulur; test denemeleri
# gerçek siparişleri "faturalandı" saymasın diye.
VERITABANI = KOK / ("fatura-test.db" if GIB_TEST_MODU else "fatura.db")
FATURA_KLASORU = KOK / "faturalar"

# Faturası kesilen siparişe Shopify'da eklenen etiket.
ETIKET = "faturalandi"

# Nihai tüketici (şahıs) faturalarında kullanılan TCKN yer tutucusu.
NIHAI_TUKETICI_TCKN = "11111111111"


def eksik_ayarlar() -> list[str]:
    """Araç çalışmadan önce doldurulması gereken ayarların listesi."""
    eksik = []
    if not SHOPIFY_STORE:
        eksik.append("SHOPIFY_STORE")
    if not SHOPIFY_TOKEN:
        eksik.append("SHOPIFY_TOKEN")
    if not GIB_KULLANICI_KODU:
        eksik.append("GIB_KULLANICI_KODU")
    if not GIB_SIFRE:
        eksik.append("GIB_SIFRE")
    return eksik
