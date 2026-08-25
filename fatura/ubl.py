"""Fatura -> UBL-TR 1.2 e-Arşiv XML'i (Hepsiburada e-Faturam toplu yükleme).

Biçim, kullanıcının kendi hesabından indirdiği gerçek bir faturadan
çıkarıldı (`INT2026000000361`). Oradan öğrenilenler:

- `ProfileID = EARSIVFATURA`, `CustomizationID = TR1.2`, `UBLVersionID = 2.1`
- Miktar birimi **NIU** (GİB portalındaki C62 değil)
- Tutarı yazıyla notu `#...#` arasında ve "Türk Lirası / Kuruş" diye yazılıyor
- `CityName` = il, `CitySubdivisionName` = ilçe
- Nihai tüketici için alıcı TCKN'si `11111111111`

**Eleman sırası UBL şemasında bağlayıcıdır** — aşağıdaki sıra örnek dosyadan
birebir alındı, oynatma.

Yüklediğimiz dosya **imzasızdır**: imzayı portalın entegratörü (Uyumsoft)
atıyor. `UBLExtensions`, `Signature` ve XSLT eki bu yüzden üretilmiyor.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal
from xml.sax.saxutils import escape

from .donustur import Fatura

CBC = "cbc"
CAC = "cac"

BIRLER = ["", "Bir", "İki", "Üç", "Dört", "Beş", "Altı", "Yedi", "Sekiz", "Dokuz"]
ONLAR = ["", "On", "Yirmi", "Otuz", "Kırk", "Elli", "Altmış", "Yetmiş", "Seksen", "Doksan"]
BASAMAK = [(10**9, "Milyar"), (10**6, "Milyon"), (10**3, "Bin"), (1, "")]


@dataclass
class Satici:
    """Faturayı kesen (mükellef) bilgileri — ayarlardan gelir."""
    tckn: str
    ad: str
    soyad: str
    unvan: str = ""
    vergi_dairesi: str = ""
    mahalle: str = ""
    bina_no: str = ""
    kapi_no: str = ""
    ilce: str = ""
    il: str = ""
    posta_kodu: str = ""
    telefon: str = ""
    eposta: str = ""
    website: str = ""


def _uc_hane(n: int) -> list[str]:
    yuz, kalan = divmod(n, 100)
    on, bir = divmod(kalan, 10)
    p = []
    if yuz:
        p.append(("" if yuz == 1 else BIRLER[yuz] + " ") + "Yüz")
    if on:
        p.append(ONLAR[on])
    if bir:
        p.append(BIRLER[bir])
    return p


def _sayi_yaziyla(n: int) -> str:
    if n == 0:
        return "Sıfır"
    parcalar: list[str] = []
    for carpan, ad in BASAMAK:
        grup, n = divmod(n, carpan)
        if not grup:
            continue
        if grup == 1 and ad == "Bin":
            parcalar.append("Bin")
        else:
            parcalar.extend(_uc_hane(grup))
            if ad:
                parcalar.append(ad)
    return " ".join(p for p in parcalar if p)


def tutar_yaziyla(tutar: Decimal) -> str:
    """379.99 -> 'Yalnız #Üç Yüz Yetmiş Dokuz Türk Lirası Doksan Dokuz Kuruş#'

    Biçim örnek faturadan alındı: kelimeler boşluklu, iki yanında # var.
    """
    lira = int(tutar)
    kurus = int((tutar - Decimal(lira)) * 100)
    metin = f"{_sayi_yaziyla(lira)} Türk Lirası"
    if kurus:
        metin += f" {_sayi_yaziyla(kurus)} Kuruş"
    return f"Yalnız #{metin}#"


# ─── XML yardımcıları ────────────────────────────────────────────────


def _e(on_ek: str, ad: str, deger="", **nitelik) -> str:
    n = "".join(f' {a}="{escape(str(d), {chr(34): "&quot;"})}"' for a, d in nitelik.items())
    if deger == "" and not nitelik:
        return f"<{on_ek}:{ad}/>"
    return f"<{on_ek}:{ad}{n}>{escape(str(deger))}</{on_ek}:{ad}>"


def _para(deger: Decimal) -> str:
    return f"{deger:.2f}"


def _adres(on_ek_kapsayici: str, oda: str, sokak: str, bina_adi: str,
           bina_no: str, ilce: str, il: str, posta: str, bolge: str = "") -> str:
    return (
        f"<{CAC}:{on_ek_kapsayici}>"
        + _e(CBC, "Room", oda)
        + _e(CBC, "StreetName", sokak)
        + _e(CBC, "BuildingName", bina_adi)
        + _e(CBC, "BuildingNumber", bina_no)
        + _e(CBC, "CitySubdivisionName", ilce)
        + _e(CBC, "CityName", il)
        + _e(CBC, "PostalZone", posta)
        + _e(CBC, "Region", bolge)
        + f"<{CAC}:Country>" + _e(CBC, "Name", "TÜRKİYE") + f"</{CAC}:Country>"
        + f"</{CAC}:{on_ek_kapsayici}>"
    )


def _vergi_alt_toplami(matrah: Decimal, kdv: Decimal, oran: int) -> str:
    return (
        f"<{CAC}:TaxSubtotal>"
        + _e(CBC, "TaxableAmount", _para(matrah), currencyID="TRY")
        + _e(CBC, "TaxAmount", _para(kdv), currencyID="TRY")
        + _e(CBC, "Percent", f"{oran:.2f}")
        + f"<{CAC}:TaxCategory><{CAC}:TaxScheme>"
        + _e(CBC, "Name", "KDV")
        + _e(CBC, "TaxTypeCode", "0015")
        + f"</{CAC}:TaxScheme></{CAC}:TaxCategory>"
        + f"</{CAC}:TaxSubtotal>"
    )


# ─── asıl üretim ─────────────────────────────────────────────────────


def ubl_fatura(
    fatura: Fatura,
    satici: Satici,
    belge_no: str,
    ettn: str | None = None,
    siparis_tarihi: str = "",
) -> str:
    """Tek bir faturanın UBL-TR XML'ini üretir.

    belge_no: 'MGL2026000000001' gibi — seri + yıl + 9 hane sıra.
    ettn: verilmezse üretilir. Dosya adında da kullanılır.
    """
    ettn = ettn or str(uuid.uuid4())
    alici = fatura.alici
    gun, ay, yil = fatura.tarih.split("/")
    tarih_iso = f"{yil}-{ay}-{gun}"

    bas = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"'
        ' xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"'
        ' xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"'
        ' xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
        ' xsi:schemaLocation="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2'
        ' UBL-Invoice-2.1.xsd">'
    )

    basliklar = (
        _e(CBC, "UBLVersionID", "2.1")
        + _e(CBC, "CustomizationID", "TR1.2")
        + _e(CBC, "ProfileID", "EARSIVFATURA")
        + _e(CBC, "ID", belge_no)
        + _e(CBC, "CopyIndicator", "false")
        + _e(CBC, "UUID", ettn)
        + _e(CBC, "IssueDate", tarih_iso)
        + _e(CBC, "IssueTime", fatura.saat or "00:00:00")
        + _e(CBC, "InvoiceTypeCode", "SATIS")
        + _e(CBC, "Note", tutar_yaziyla(fatura.toplam))
        + _e(CBC, "DocumentCurrencyCode", "TRY")
        + _e(CBC, "LineCountNumeric", str(len(fatura.kalemler)))
    )

    siparis = ""
    if fatura.siparis_no:
        siparis = (
            f"<{CAC}:OrderReference>"
            + _e(CBC, "ID", fatura.siparis_no.lstrip("#"))
            + _e(CBC, "IssueDate", siparis_tarihi or tarih_iso)
            + f"</{CAC}:OrderReference>"
        )

    satici_blogu = (
        f"<{CAC}:AccountingSupplierParty><{CAC}:Party>"
        + _e(CBC, "WebsiteURI", satici.website)
        + f"<{CAC}:PartyIdentification>"
        + _e(CBC, "ID", satici.tckn, schemeID="TCKN" if len(satici.tckn) == 11 else "VKN")
        + f"</{CAC}:PartyIdentification>"
        + (f"<{CAC}:PartyName>" + _e(CBC, "Name", satici.unvan) + f"</{CAC}:PartyName>"
           if satici.unvan else "")
        + _adres("PostalAddress", satici.kapi_no, satici.mahalle, "", satici.bina_no,
                 satici.ilce, satici.il, satici.posta_kodu)
        + f"<{CAC}:PartyTaxScheme><{CAC}:TaxScheme>"
        + _e(CBC, "Name", satici.vergi_dairesi)
        + f"</{CAC}:TaxScheme></{CAC}:PartyTaxScheme>"
        + f"<{CAC}:Contact>"
        + _e(CBC, "Telephone", satici.telefon)
        + _e(CBC, "ElectronicMail", satici.eposta)
        + f"</{CAC}:Contact>"
        + (f"<{CAC}:Person>" + _e(CBC, "FirstName", satici.ad)
           + _e(CBC, "FamilyName", satici.soyad) + f"</{CAC}:Person>"
           if not satici.unvan else "")
        + f"</{CAC}:Party></{CAC}:AccountingSupplierParty>"
    )

    kurumsal = bool(alici.unvan)
    alici_blogu = (
        f"<{CAC}:AccountingCustomerParty><{CAC}:Party>"
        + f"<{CAC}:PartyIdentification>"
        + _e(CBC, "ID", alici.vkn_tckn,
             schemeID="VKN" if kurumsal and len(alici.vkn_tckn) == 10 else "TCKN")
        + f"</{CAC}:PartyIdentification>"
        + (f"<{CAC}:PartyName>" + _e(CBC, "Name", alici.unvan) + f"</{CAC}:PartyName>"
           if kurumsal else "")
        + _adres("PostalAddress", "", alici.adres, "", "", alici.ilce,
                 alici.sehir, alici.posta_kodu)
        + (f"<{CAC}:PartyTaxScheme><{CAC}:TaxScheme>"
           + _e(CBC, "Name", alici.vergi_dairesi)
           + f"</{CAC}:TaxScheme></{CAC}:PartyTaxScheme>" if alici.vergi_dairesi else "")
        + f"<{CAC}:Contact>"
        + _e(CBC, "Telephone", alici.telefon)
        + _e(CBC, "ElectronicMail", alici.eposta)
        + f"</{CAC}:Contact>"
        + (f"<{CAC}:Person>" + _e(CBC, "FirstName", alici.ad)
           + _e(CBC, "FamilyName", alici.soyad) + f"</{CAC}:Person>"
           if not kurumsal else "")
        + f"</{CAC}:Party></{CAC}:AccountingCustomerParty>"
    )

    oran = fatura.kalemler[0].kdv_orani if fatura.kalemler else 20
    vergi_toplami = (
        f"<{CAC}:TaxTotal>"
        + _e(CBC, "TaxAmount", _para(fatura.kdv), currencyID="TRY")
        + _vergi_alt_toplami(fatura.matrah, fatura.kdv, oran)
        + f"</{CAC}:TaxTotal>"
    )

    genel_toplam = (
        f"<{CAC}:LegalMonetaryTotal>"
        + _e(CBC, "LineExtensionAmount", _para(fatura.matrah), currencyID="TRY")
        + _e(CBC, "TaxExclusiveAmount", _para(fatura.matrah), currencyID="TRY")
        + _e(CBC, "TaxInclusiveAmount", _para(fatura.toplam), currencyID="TRY")
        + _e(CBC, "AllowanceTotalAmount", "0.00", currencyID="TRY")
        + _e(CBC, "PayableAmount", _para(fatura.toplam), currencyID="TRY")
        + f"</{CAC}:LegalMonetaryTotal>"
    )

    satirlar = []
    for sira, k in enumerate(fatura.kalemler, start=1):
        satirlar.append(
            f"<{CAC}:InvoiceLine>"
            + _e(CBC, "ID", str(sira))
            + _e(CBC, "InvoicedQuantity", f"{k.miktar}", unitCode="NIU")
            + _e(CBC, "LineExtensionAmount", _para(k.matrah), currencyID="TRY")
            + f"<{CAC}:TaxTotal>"
            + _e(CBC, "TaxAmount", _para(k.kdv), currencyID="TRY")
            + _vergi_alt_toplami(k.matrah, k.kdv, k.kdv_orani)
            + f"</{CAC}:TaxTotal>"
            + f"<{CAC}:Item>" + _e(CBC, "Name", k.ad) + f"</{CAC}:Item>"
            + f"<{CAC}:Price>"
            + _e(CBC, "PriceAmount", _para(k.birim_fiyat), currencyID="TRY")
            + f"</{CAC}:Price>"
            + f"</{CAC}:InvoiceLine>"
        )

    return (
        bas + basliklar + siparis + satici_blogu + alici_blogu
        + vergi_toplami + genel_toplam + "".join(satirlar) + "</Invoice>"
    )


def saticiyi_oku(xml_metni: str) -> tuple[Satici, str]:
    """Portaldan indirilmiş bir faturadan satıcı bilgilerini çıkarır.

    Kullanıcının bu bilgileri elle yazmasına gerek kalmasın diye: e-Faturam'da
    kestiği herhangi bir faturayı XML olarak indirip veriyor, ad/adres/vergi
    dairesi oradan okunuyor. Fatura numarasının serisi de (ör. 'INT') döner,
    böylece çakışmayan bir seri seçilebilir.
    """
    import re as _re
    from xml.etree import ElementTree as _ET

    # İmza bloğu ve XSLT eki devasa olabiliyor; ayrıştırmadan önce atıyoruz.
    govde = _re.sub(r"<ext:UBLExtensions>.*?</ext:UBLExtensions>", "", xml_metni, flags=_re.S)
    govde = _re.sub(
        r"<cac:AdditionalDocumentReference>.*?</cac:AdditionalDocumentReference>",
        "", govde, flags=_re.S,
    )
    try:
        kok = _ET.fromstring(govde)
    except _ET.ParseError as hata:
        raise ValueError(f"XML okunamadı: {hata}")

    ad_sadelestir = lambda etiket: _re.sub(r"\{[^}]+\}", "", etiket)  # noqa: E731

    def bul(kapsayici, *yol: str) -> str:
        el = kapsayici
        for parca in yol:
            el = next((c for c in el if ad_sadelestir(c.tag) == parca), None)
            if el is None:
                return ""
        return (el.text or "").strip()

    taraf = next(
        (c for c in kok if ad_sadelestir(c.tag) == "AccountingSupplierParty"), None
    )
    if taraf is None:
        raise ValueError("Faturada satıcı bilgisi bulunamadı.")
    taraf = next((c for c in taraf if ad_sadelestir(c.tag) == "Party"), taraf)

    satici = Satici(
        tckn=bul(taraf, "PartyIdentification", "ID"),
        ad=bul(taraf, "Person", "FirstName"),
        soyad=bul(taraf, "Person", "FamilyName"),
        unvan=bul(taraf, "PartyName", "Name"),
        vergi_dairesi=bul(taraf, "PartyTaxScheme", "TaxScheme", "Name"),
        mahalle=bul(taraf, "PostalAddress", "StreetName"),
        bina_no=bul(taraf, "PostalAddress", "BuildingNumber"),
        kapi_no=bul(taraf, "PostalAddress", "Room"),
        ilce=bul(taraf, "PostalAddress", "CitySubdivisionName"),
        il=bul(taraf, "PostalAddress", "CityName"),
        posta_kodu=bul(taraf, "PostalAddress", "PostalZone"),
        telefon=bul(taraf, "Contact", "Telephone"),
        eposta=bul(taraf, "Contact", "ElectronicMail"),
        website=bul(taraf, "WebsiteURI"),
    )

    # Belge numarasının harf öneki = seri (INT2026000000361 -> INT)
    belge_no = next(
        ((c.text or "").strip() for c in kok if ad_sadelestir(c.tag) == "ID"), ""
    )
    seri = "".join(ch for ch in belge_no[:3] if ch.isalpha())
    return satici, seri


def dosya_adi(satici_tckn: str, belge_no: str, ettn: str) -> str:
    """Portalın kendi indirdiği dosyalardaki adlandırma düzeni."""
    return f"{satici_tckn}-{belge_no}-{ettn}.xml"
