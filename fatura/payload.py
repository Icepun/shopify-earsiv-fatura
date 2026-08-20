"""Fatura nesnesini GİB e-Arşiv Portal payload'ına çevirir."""

from __future__ import annotations

from decimal import Decimal

from . import config
from .donustur import Fatura

BIRLER = ["", "Bir", "İki", "Üç", "Dört", "Beş", "Altı", "Yedi", "Sekiz", "Dokuz"]
ONLAR = ["", "On", "Yirmi", "Otuz", "Kırk", "Elli", "Altmış", "Yetmiş", "Seksen", "Doksan"]
BASAMAKLAR = [(10**9, "Milyar"), (10**6, "Milyon"), (10**3, "Bin"), (1, "")]


def _uc_hane_yaziyla(sayi: int) -> str:
    yuz, kalan = divmod(sayi, 100)
    on, bir = divmod(kalan, 10)
    parcalar = []
    if yuz:
        parcalar.append(("" if yuz == 1 else BIRLER[yuz]) + "Yüz")
    if on:
        parcalar.append(ONLAR[on])
    if bir:
        parcalar.append(BIRLER[bir])
    return "".join(parcalar)


def _tam_sayi_yaziyla(sayi: int) -> str:
    if sayi == 0:
        return "Sıfır"
    parcalar = []
    for carpan, ad in BASAMAKLAR:
        grup, sayi = divmod(sayi, carpan)
        if not grup:
            continue
        # "BirBin" değil "Bin"
        metin = "" if (grup == 1 and ad == "Bin") else _uc_hane_yaziyla(grup)
        parcalar.append(metin + ad)
    return "".join(parcalar)


def tutar_yaziyla(tutar: Decimal) -> str:
    """514.99 -> 'Yalnız BeşyüzOndört TL, DoksanDokuz Kr.'"""
    lira = int(tutar)
    kurus = int((tutar - Decimal(lira)) * 100)
    metin = f"Yalnız {_tam_sayi_yaziyla(lira)} TL"
    if kurus:
        metin += f", {_tam_sayi_yaziyla(kurus)} Kr."
    return metin


def gib_payloadu(fatura: Fatura, fatura_notu: str | None = None) -> dict:
    """Onaylanmış Fatura nesnesinden GİB'e gönderilecek sözlüğü üretir."""
    alici = fatura.alici
    notlar = [n for n in [(fatura_notu if fatura_notu is not None else config.FATURA_NOTU)] if n]
    notlar.append(tutar_yaziyla(fatura.toplam))

    return {
        # ETTN'i GİB'in kendisi atar. Buraya kendi UUID'mizi yazarsak
        # portal "Ettn ... 36 uzunluk sınırına uymuyor" diyerek reddediyor.
        "faturaUuid": "",
        "belgeNumarasi": "",
        "faturaTarihi": fatura.tarih,
        "saat": fatura.saat,
        "paraBirimi": "TRY",
        "dovzTLkur": "0",
        "faturaTipi": "SATIS",
        "hangiTip": "5000/30000",
        "vknTckn": alici.vkn_tckn or config.NIHAI_TUKETICI_TCKN,
        "aliciUnvan": alici.unvan,
        "aliciAdi": alici.ad,
        "aliciSoyadi": alici.soyad,
        "binaAdi": "",
        "binaNo": "",
        "kapiNo": "",
        "kasabaKoy": "",
        "vergiDairesi": alici.vergi_dairesi,
        "ulke": "Türkiye",
        "bulvarcaddesokak": alici.adres,
        "irsaliyeNumarasi": "",
        "irsaliyeTarihi": "",
        "mahalleSemtIlce": alici.ilce,
        "sehir": alici.sehir or " ",
        "postaKodu": alici.posta_kodu,
        "tel": alici.telefon,
        "fax": "",
        "eposta": alici.eposta,
        "websitesi": "",
        "iadeTable": [],
        "vergiCesidi": " ",
        "malHizmetTable": [kalem.gib_sozlugu() for kalem in fatura.kalemler],
        "tip": "İskonto",
        "matrah": f"{fatura.matrah:.2f}",
        "malhizmetToplamTutari": f"{fatura.matrah:.2f}",
        "toplamIskonto": "0.00",
        "hesaplanankdv": f"{fatura.kdv:.2f}",
        "vergilerToplami": f"{fatura.kdv:.2f}",
        "vergilerDahilToplamTutar": f"{fatura.toplam:.2f}",
        "odenecekTutar": f"{fatura.toplam:.2f}",
        "not": "\n".join(notlar),
        "siparisNumarasi": fatura.siparis_no,
        "siparisTarihi": fatura.tarih,
        "fisNo": "",
        "fisTarihi": "",
        "fisSaati": " ",
        "fisTipi": " ",
        "zRaporNo": "",
        "okcSeriNo": "",
    }
