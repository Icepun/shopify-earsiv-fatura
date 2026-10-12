"""Kesilen faturaların yerel kaydı (SQLite).

Shopify etiketi tek başına yeterli olurdu; yerel kayıt ETTN'leri, belge
numaralarını ve yükleme durumunu da tuttuğu için sorun çıktığında geri
dönülebilir bir iz bırakır.

Üç tablo var:
    faturalar  siparişin şu anki durumu (sipariş başına tek satır)
    belgeler   üretilen her XML'in kalıcı izi (silinmez, iptal olur)
    sayac      seri + yıl başına son verilen sıra
"""

from __future__ import annotations

import os
import shutil
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Callable

from . import config
from .gunluk import kayit

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

-- Üretilen her XML'in kalıcı izi. Yeniden üretme ve geri alma satır silmez,
-- durumu 'iptal' yapar: verilmiş bir numara bir daha verilmez ve bir
-- siparişe hangi numaraların çıktığı sonradan görülebilir.
CREATE TABLE IF NOT EXISTS belgeler (
    belge_no       TEXT PRIMARY KEY,
    siparis_id     TEXT NOT NULL,
    siparis_no     TEXT NOT NULL,
    ettn           TEXT,
    tutar          TEXT,
    fatura_tarihi  TEXT,                  -- YYYY-AA-GG
    dosya          TEXT,
    durum          TEXT NOT NULL,         -- uretildi | yuklendi | iptal
    olusturma      TEXT NOT NULL,
    guncelleme     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS belgeler_siparis ON belgeler(siparis_id);

-- Seri + yıl başına son verilen sıra (MGL2026 -> 182). Yıl değişince yeni
-- anahtar açılır ve sıra 1'den başlar.
CREATE TABLE IF NOT EXISTS sayac (
    anahtar      TEXT PRIMARY KEY,
    son          INTEGER NOT NULL
);
"""

FATURA_YAZ = """
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
"""

# Belge numarası: seri (3) + yıl (4) + sıra (9) = 16 hane.
SIRA_HANESI = 9
BELGE_NO_BOYU = 16


def _simdi() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _anahtar(seri: str, yil: int) -> str:
    return f"{seri}{yil}"


@contextmanager
def baglanti():
    baglan = sqlite3.connect(config.VERITABANI, timeout=15)
    baglan.row_factory = sqlite3.Row
    try:
        yield baglan
        baglan.commit()
    finally:
        baglan.close()


def eski_veritabanini_tasi() -> None:
    """`fatura-test.db`'yi `fatura.db` adına taşır (tek seferlik).

    Gerçek kayıtlar eskiden adı "test" olan dosyada birikiyordu (bkz.
    config._globalleri_tazele); "test dosyası" diye silinirse bütün belge
    geçmişi ve sayaç giderdi.

    Taşımadan önce ikisi de `yedek/` klasörüne alınır: taşınan dosyanın bir
    kopyası ve varsa eski `fatura.db` (içindekiler yeni dosyaya karışmaz).
    Bir adım başarısız olursa eski dosya yerinde kalır, uygulama onunla
    çalışmaya devam eder ve sonraki açılışta yeniden denenir.
    """
    asil, eski = config.veritabani_dosyalari()
    if not (config.GIB_TEST_MODU and eski.exists()):
        return
    # Yarım kalmış bir işlemin günlüğü varsa dosya tek başına taşınamaz;
    # SQLite onu ilk açılışta toparlar, taşıma bir sonraki açılışa kalır.
    if any(eski.with_name(eski.name + ek).exists() for ek in ("-journal", "-wal")):
        return
    yedek = eski.parent / "yedek"
    damga = datetime.now().strftime("%Y%m%d-%H%M%S")
    try:
        yedek.mkdir(exist_ok=True)
        shutil.copy2(eski, yedek / f"fatura-test_{damga}.db")
        if asil.exists():
            os.replace(asil, yedek / f"fatura-eski_{damga}.db")
        os.replace(eski, asil)
    except OSError as hata:
        kayit.error("veritabani tasinamadi, eski dosyayla devam: %r", hata)
        return
    kayit.info("veritabani fatura.db adina tasindi (yedek: %s)", yedek)
    config.yeniden_yukle()


def hazirla() -> None:
    with baglanti() as baglan:
        baglan.executescript(SEMA)
        # Eski veritabanlarında bu sütun yok; sessizce ekliyoruz.
        sutunlar = {s[1] for s in baglan.execute("PRAGMA table_info(faturalar)")}
        if "belge_no" not in sutunlar:
            baglan.execute("ALTER TABLE faturalar ADD COLUMN belge_no TEXT")
        _eskiyi_tasi(baglan)


def _eskiyi_tasi(baglan: sqlite3.Connection) -> None:
    """Eski kayıtları belge geçmişine, eski sıra ayarını sayaca taşır.

    Her açılışta çalışır ama yalnızca eksik olanı ekler.
    """
    baglan.execute(
        """
        INSERT OR IGNORE INTO belgeler
            (belge_no, siparis_id, siparis_no, ettn, tutar, durum,
             olusturma, guncelleme)
        SELECT belge_no, siparis_id, siparis_no, ettn, tutar,
               CASE durum WHEN 'imzalandi' THEN 'yuklendi' ELSE 'uretildi' END,
               olusturma, guncelleme
        FROM faturalar
        WHERE belge_no IS NOT NULL AND belge_no != ''
        """
    )

    if baglan.execute("SELECT COUNT(*) FROM sayac").fetchone()[0]:
        return
    # Sayaç ilk kez kuruluyor: kullanılmış numaralardan ve eskiden ayar
    # dosyasında tutulan sıradan devralınıyor.
    onek = BELGE_NO_BOYU - SIRA_HANESI
    for satir in baglan.execute(
        "SELECT substr(belge_no, 1, ?) AS anahtar, "
        "MAX(CAST(substr(belge_no, ?) AS INTEGER)) AS son "
        "FROM belgeler WHERE length(belge_no) = ? GROUP BY anahtar",
        (onek, onek + 1, BELGE_NO_BOYU),
    ).fetchall():
        baglan.execute(
            "INSERT INTO sayac (anahtar, son) VALUES (?, ?)",
            (satir["anahtar"], satir["son"]),
        )
    eski = _eski_sira()
    if eski > 0:
        baglan.execute(
            "INSERT INTO sayac (anahtar, son) VALUES (?, ?) "
            "ON CONFLICT(anahtar) DO UPDATE SET son = MAX(son, excluded.son)",
            (_anahtar(config.fatura_serisi(), datetime.now().year), eski),
        )


def _eski_sira() -> int:
    """Ayar dosyasındaki yedek sıra (bkz. config.ALANLAR > fatura_sira)."""
    try:
        return max(0, int(config.ayarlar().get("fatura_sira", 0) or 0))
    except (TypeError, ValueError):
        return 0


def _kullanilan_en_buyuk(baglan: sqlite3.Connection, anahtar: str) -> int:
    """Bu seri + yılda bugüne kadar verilmiş en büyük sıra (iptaller dahil)."""
    return baglan.execute(
        "SELECT MAX(CAST(substr(belge_no, ?) AS INTEGER)) FROM belgeler "
        "WHERE substr(belge_no, 1, ?) = ? AND length(belge_no) = ?",
        (len(anahtar) + 1, len(anahtar), anahtar, len(anahtar) + SIRA_HANESI),
    ).fetchone()[0] or 0


def _son_sira(baglan: sqlite3.Connection, anahtar: str) -> int:
    satir = baglan.execute(
        "SELECT son FROM sayac WHERE anahtar = ?", (anahtar,)
    ).fetchone()
    if satir is not None:
        son = satir["son"]
    elif baglan.execute("SELECT COUNT(*) FROM sayac").fetchone()[0] == 0:
        son = _eski_sira()
    else:
        son = 0
    # Sayaç ne derse desin, verilmiş bir numaranın altından devam edilmez.
    return max(son, _kullanilan_en_buyuk(baglan, anahtar))


def son_sira(seri: str, yil: int) -> int:
    """Bu seri + yılda son verilen sıra; sonraki fatura bir fazlasını alır."""
    with baglanti() as baglan:
        return _son_sira(baglan, _anahtar(seri, yil))


def sirayi_ayarla(seri: str, yil: int, deger: int) -> int:
    """Sayacı elle değiştirir ve geçerli olan değeri döner.

    Daha önce verilmiş en büyük numaranın altına inmez; inseydi aynı numara
    ikinci kez verilirdi.
    """
    anahtar = _anahtar(seri, yil)
    with baglanti() as baglan:
        son = max(int(deger), _kullanilan_en_buyuk(baglan, anahtar), 0)
        baglan.execute(
            "INSERT INTO sayac (anahtar, son) VALUES (?, ?) "
            "ON CONFLICT(anahtar) DO UPDATE SET son = excluded.son",
            (anahtar, son),
        )
    return son


def belge_uret(
    seri: str,
    yil: int,
    siparis_id: str,
    siparis_no: str,
    ettn: str,
    tutar: str,
    fatura_tarihi: str,
    yaz: Callable[[str], str],
) -> dict:
    """Sıradaki numarayı verir, XML'i yazdırır ve kaydı düşer — tek işlemde.

    `yaz(belge_no)` dosyayı yazıp adını döner. Hata verirse işlem geri
    sarılır: numara harcanmaz, yarım kayıt kalmaz. Veritabanı işlem boyunca
    kilitli tutulduğu için iki üretim aynı numarayı alamaz.

    Siparişin önceki belgesi varsa 'iptal' olur (yeniden üretim).
    """
    anahtar = _anahtar(seri, yil)
    simdi = _simdi()
    baglan = sqlite3.connect(config.VERITABANI, timeout=15, isolation_level=None)
    baglan.row_factory = sqlite3.Row
    try:
        baglan.execute("BEGIN IMMEDIATE")
        try:
            sira = _son_sira(baglan, anahtar) + 1
            belge_no = f"{anahtar}{sira:0{SIRA_HANESI}d}"
            dosya = yaz(belge_no)
            baglan.execute(
                "UPDATE belgeler SET durum = 'iptal', guncelleme = ? "
                "WHERE siparis_id = ? AND durum != 'iptal'",
                (simdi, siparis_id),
            )
            baglan.execute(
                "INSERT INTO belgeler (belge_no, siparis_id, siparis_no, ettn, "
                "tutar, fatura_tarihi, dosya, durum, olusturma, guncelleme) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'uretildi', ?, ?)",
                (belge_no, siparis_id, siparis_no, ettn, tutar, fatura_tarihi,
                 dosya, simdi, simdi),
            )
            baglan.execute(
                "INSERT INTO sayac (anahtar, son) VALUES (?, ?) "
                "ON CONFLICT(anahtar) DO UPDATE SET son = excluded.son",
                (anahtar, sira),
            )
            baglan.execute(
                FATURA_YAZ,
                (siparis_id, siparis_no, ettn, belge_no, "taslak", tutar, "",
                 simdi, simdi),
            )
            baglan.execute("COMMIT")
        except BaseException:
            baglan.execute("ROLLBACK")
            raise
    finally:
        baglan.close()
    return {"belge_no": belge_no, "sira": sira, "dosya": dosya}


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
            FATURA_YAZ,
            (siparis_id, siparis_no, ettn, belge_no, durum, tutar, hata,
             _simdi(), _simdi()),
        )


def yuklendi_isaretle(siparis_id: str) -> None:
    """Siparişin geçerli belgesini 'portala yüklendi' durumuna çeker."""
    with baglanti() as baglan:
        baglan.execute(
            "UPDATE belgeler SET durum = 'yuklendi', guncelleme = ? "
            "WHERE siparis_id = ? AND durum = 'uretildi'",
            (_simdi(), siparis_id),
        )


def bekleyen_taslaklar() -> list[sqlite3.Row]:
    """XML'i üretilmiş ama henüz 'faturalandı' diye işaretlenmemiş siparişler."""
    with baglanti() as baglan:
        return baglan.execute(
            "SELECT f.*, b.fatura_tarihi, b.dosya FROM faturalar f "
            "LEFT JOIN belgeler b ON b.belge_no = f.belge_no "
            "WHERE f.durum = 'taslak' ORDER BY f.belge_no, f.olusturma"
        ).fetchall()


def geri_al(siparis_id: str) -> None:
    """Siparişi yeniden "faturalanmamış" yapar.

    Belge geçmişte 'iptal' olarak kalır; sipariş yeni bir belge numarası ve
    yeni ETTN ile yeniden üretilebilir.
    """
    with baglanti() as baglan:
        baglan.execute(
            "UPDATE belgeler SET durum = 'iptal', guncelleme = ? "
            "WHERE siparis_id = ? AND durum != 'iptal'",
            (_simdi(), siparis_id),
        )
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


def kayitlari_getir(siparis_idler: list[str]) -> dict[str, dict]:
    """Verilen siparişlerin kayıtları (siparis_id -> satır); kaydı olmayan yer almaz."""
    bulunan: dict[str, dict] = {}
    with baglanti() as baglan:
        for bas in range(0, len(siparis_idler), 500):
            parca = siparis_idler[bas:bas + 500]
            for satir in baglan.execute(
                "SELECT * FROM faturalar WHERE siparis_id IN (%s)"
                % ",".join("?" * len(parca)),
                parca,
            ):
                bulunan[satir["siparis_id"]] = dict(satir)
    return bulunan


def gecmis(limit: int = 200) -> list[dict]:
    with baglanti() as baglan:
        satirlar = baglan.execute(
            "SELECT * FROM faturalar ORDER BY guncelleme DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(satir) for satir in satirlar]
