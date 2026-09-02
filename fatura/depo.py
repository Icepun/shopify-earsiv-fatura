"""Kesilen faturaların yerel kaydı (SQLite).

Shopify etiketi tek başına yeterli olurdu; yerel kayıt ETTN'leri, hata
mesajlarını ve imza durumunu da tuttuğu için sorun çıktığında geri
dönülebilir bir iz bırakır.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from . import config

SEMA = """
CREATE TABLE IF NOT EXISTS faturalar (
    siparis_id   TEXT PRIMARY KEY,
    siparis_no   TEXT NOT NULL,
    ettn         TEXT,
    belge_no     TEXT,
    durum        TEXT NOT NULL,           -- taslak | imzalandi | hata
    tutar        TEXT,
    hata         TEXT,
    olusturma    TEXT NOT NULL,
    guncelleme   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS faturalar_durum ON faturalar(durum);

-- Listeye hiç düşmesin istenen siparişler (deneme siparişleri vb.).
-- Faturalanmışlardan ayrı tutuluyor: gizlemek fatura kesmek demek değil,
-- ve tek tıkla geri alınabilmesi gerekiyor.
CREATE TABLE IF NOT EXISTS gizlenenler (
    siparis_id   TEXT PRIMARY KEY,
    siparis_no   TEXT,
    olusturma    TEXT NOT NULL
);
"""


def _simdi() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def baglanti():
    baglan = sqlite3.connect(config.VERITABANI)
    baglan.row_factory = sqlite3.Row
    try:
        yield baglan
        baglan.commit()
    finally:
        baglan.close()


def hazirla() -> None:
    with baglanti() as baglan:
        baglan.executescript(SEMA)
        # Eski veritabanlarında bu sütun yok; sessizce ekliyoruz.
        sutunlar = {s[1] for s in baglan.execute("PRAGMA table_info(faturalar)")}
        if "belge_no" not in sutunlar:
            baglan.execute("ALTER TABLE faturalar ADD COLUMN belge_no TEXT")


def kaydet(
    siparis_id: str,
    siparis_no: str,
    durum: str,
    ettn: str = "",
    tutar: str = "",
    hata: str = "",
    belge_no: str = "",
) -> None:
    with baglanti() as baglan:
        baglan.execute(
            """
            INSERT INTO faturalar
                (siparis_id, siparis_no, ettn, belge_no, durum, tutar, hata,
                 olusturma, guncelleme)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(siparis_id) DO UPDATE SET
                ettn       = excluded.ettn,
                belge_no   = excluded.belge_no,
                durum      = excluded.durum,
                tutar      = excluded.tutar,
                hata       = excluded.hata,
                guncelleme = excluded.guncelleme
            """,
            (siparis_id, siparis_no, ettn, belge_no, durum, tutar, hata,
             _simdi(), _simdi()),
        )


def durum_getir(siparis_id: str) -> sqlite3.Row | None:
    with baglanti() as baglan:
        return baglan.execute(
            "SELECT * FROM faturalar WHERE siparis_id = ?", (siparis_id,)
        ).fetchone()


def bekleyen_taslaklar() -> list[sqlite3.Row]:
    """Oluşturulmuş ama henüz imzalanmamış faturalar."""
    with baglanti() as baglan:
        return baglan.execute(
            "SELECT * FROM faturalar WHERE durum = 'taslak' ORDER BY olusturma"
        ).fetchall()


def islenmis_idler() -> set[str]:
    """Taslağı oluşturulmuş veya imzalanmış sipariş id'leri."""
    with baglanti() as baglan:
        satirlar = baglan.execute(
            "SELECT siparis_id FROM faturalar WHERE durum IN ('taslak', 'imzalandi')"
        ).fetchall()
    return {satir["siparis_id"] for satir in satirlar}


def sil(siparis_id: str) -> None:
    """Fatura kaydını siler — yanlış kesilen bir fatura geri alınırken.

    Sipariş yeniden "faturalanmamış" duruma döner ve yeni bir belge
    numarası + yeni ETTN ile yeniden üretilebilir.
    """
    with baglanti() as baglan:
        baglan.execute("DELETE FROM faturalar WHERE siparis_id = ?", (siparis_id,))


def gizle(siparis_id: str, siparis_no: str = "") -> None:
    with baglanti() as baglan:
        baglan.execute(
            "INSERT INTO gizlenenler (siparis_id, siparis_no, olusturma) "
            "VALUES (?, ?, ?) ON CONFLICT(siparis_id) DO NOTHING",
            (siparis_id, siparis_no, _simdi()),
        )


def gizlemeyi_kaldir(siparis_id: str) -> None:
    with baglanti() as baglan:
        baglan.execute("DELETE FROM gizlenenler WHERE siparis_id = ?", (siparis_id,))


def gizli_idler() -> set[str]:
    with baglanti() as baglan:
        satirlar = baglan.execute("SELECT siparis_id FROM gizlenenler").fetchall()
    return {satir["siparis_id"] for satir in satirlar}


def gizlenenler() -> list[dict]:
    with baglanti() as baglan:
        satirlar = baglan.execute(
            "SELECT * FROM gizlenenler ORDER BY olusturma DESC"
        ).fetchall()
    return [dict(satir) for satir in satirlar]


def gecmis(limit: int = 200) -> list[dict]:
    with baglanti() as baglan:
        satirlar = baglan.execute(
            "SELECT * FROM faturalar ORDER BY guncelleme DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(satir) for satir in satirlar]
