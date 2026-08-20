"""Yerel onay paneli: siparişleri getir, gözden geçir, toplu fatura kes."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, depo
from .donustur import Fatura, siparisi_faturaya_cevir
from .gib import GibHatasi, GibPortal
from .payload import gib_payloadu
from .shopify_api import Shopify, ShopifyHatasi

uygulama = FastAPI(title="Shopify → e-Arşiv Fatura")
KOK = Path(__file__).resolve().parent.parent

# Panel oturumu: GİB bağlantısı ve son çekilen siparişler bellekte tutulur.
_durum: dict = {"gib": None, "siparisler": {}, "faturalar": {}, "oid": None, "telefon": None}


# ─── yardımcılar ─────────────────────────────────────────────────────


def _gib() -> GibPortal:
    portal = _durum.get("gib")
    if portal is None or not portal.token:
        eksik = [a for a in ("GIB_KULLANICI_KODU", "GIB_SIFRE") if not getattr(config, a)]
        if eksik:
            raise HTTPException(400, f".env dosyasında {', '.join(eksik)} boş.")
        portal = GibPortal(
            config.GIB_KULLANICI_KODU, config.GIB_SIFRE, config.GIB_TEST_MODU
        )
        try:
            portal.giris()
        except GibHatasi as hata:
            raise HTTPException(400, str(hata))
        _durum["gib"] = portal
    return portal


def _fatura_sozlugu(fatura: Fatura) -> dict:
    return {
        "siparis_id": fatura.siparis_id,
        "siparis_no": fatura.siparis_no,
        "tarih": fatura.tarih,
        "alici": {
            "ad": fatura.alici.ad,
            "soyad": fatura.alici.soyad,
            "unvan": fatura.alici.unvan,
            "vkn_tckn": fatura.alici.vkn_tckn,
            "vergi_dairesi": fatura.alici.vergi_dairesi,
            "adres": fatura.alici.adres,
            "ilce": fatura.alici.ilce,
            "sehir": fatura.alici.sehir,
            "telefon": fatura.alici.telefon,
            "eposta": fatura.alici.eposta,
        },
        "kalemler": [
            {
                "ad": k.ad,
                "miktar": float(k.miktar),
                "birim_fiyat": f"{k.birim_fiyat:.2f}",
                "matrah": f"{k.matrah:.2f}",
                "kdv": f"{k.kdv:.2f}",
                "dahil": f"{k.dahil:.2f}",
            }
            for k in fatura.kalemler
        ],
        "matrah": f"{fatura.matrah:.2f}",
        "kdv": f"{fatura.kdv:.2f}",
        "toplam": f"{fatura.toplam:.2f}",
        "tahsil_edilen": f"{fatura.tahsil_edilen:.2f}",
        "sapma": f"{fatura.sapma:.2f}",
        "uyarilar": fatura.uyarilar,
    }


def _duzeltmeleri_uygula(fatura: Fatura, duzeltmeler: dict) -> None:
    for alan in (
        "ad", "soyad", "unvan", "vkn_tckn", "vergi_dairesi",
        "adres", "ilce", "sehir", "telefon", "eposta",
    ):
        if alan in duzeltmeler and duzeltmeler[alan] is not None:
            setattr(fatura.alici, alan, str(duzeltmeler[alan]).strip())


# ─── istek gövdeleri ─────────────────────────────────────────────────


class TaslakIstegi(BaseModel):
    siparis_idler: list[str]
    duzeltmeler: dict[str, dict] = {}


class ImzaIstegi(BaseModel):
    kod: str


# ─── uçlar ───────────────────────────────────────────────────────────


@uygulama.on_event("startup")
def _baslangic() -> None:
    depo.hazirla()


@uygulama.get("/", response_class=HTMLResponse)
def panel() -> FileResponse:
    return FileResponse(KOK / "static" / "index.html")


@uygulama.get("/api/ayarlar")
def ayarlar() -> dict:
    return {
        "magaza": config.SHOPIFY_STORE,
        "test_modu": config.GIB_TEST_MODU,
        "kdv_orani": config.KDV_ORANI,
        "kargoyu_dagit": config.KARGOYU_DAGIT,
        "eksik_ayarlar": config.eksik_ayarlar(),
    }


@uygulama.get("/api/siparisler")
def siparisler(tetikleyici: str = "fulfilled", limit: int = 100) -> dict:
    try:
        istemci = Shopify()
        ham = istemci.faturalanmamis_siparisler(tetikleyici=tetikleyici, limit=limit)
    except ShopifyHatasi as hata:
        raise HTTPException(400, str(hata))

    islenmis = depo.islenmis_idler()
    _durum["siparisler"] = {}
    _durum["faturalar"] = {}

    sonuc = []
    for siparis in ham:
        if siparis["id"] in islenmis:
            continue
        fatura = siparisi_faturaya_cevir(siparis)
        _durum["siparisler"][siparis["id"]] = siparis
        _durum["faturalar"][siparis["id"]] = fatura
        sonuc.append(_fatura_sozlugu(fatura))

    return {"adet": len(sonuc), "faturalar": sonuc}


def _tarih_araligi() -> tuple[str, str]:
    """Taslak sorgusu için geniş bir aralık (faturalar geçmiş tarihli olabilir)."""
    bugun = datetime.now()
    return (
        (bugun - timedelta(days=60)).strftime("%d/%m/%Y"),
        bugun.strftime("%d/%m/%Y"),
    )


@uygulama.post("/api/taslaklar")
def taslak_olustur(istek: TaslakIstegi) -> dict:
    portal = _gib()
    baslangic, bitis = _tarih_araligi()

    # ETTN'i GİB atadığı ve yanıtta dönmediği için, oluşturmadan önceki
    # taslak kümesini alıp sonrasındaki farktan eşleştiriyoruz.
    try:
        onceki_ettnler = portal.taslak_ettnleri(baslangic, bitis)
    except GibHatasi:
        onceki_ettnler = set()

    sonuclar = []
    olusturulanlar = []  # (siparis_id, fatura) — oluşturma sırasıyla

    for siparis_id in istek.siparis_idler:
        fatura = _durum["faturalar"].get(siparis_id)
        if fatura is None:
            sonuclar.append(
                {"siparis_id": siparis_id, "durum": "hata",
                 "hata": "Sipariş bellekte yok, listeyi yenileyin."}
            )
            continue

        _duzeltmeleri_uygula(fatura, istek.duzeltmeler.get(siparis_id, {}))

        try:
            portal.fatura_olustur(gib_payloadu(fatura))
            olusturulanlar.append((siparis_id, fatura))
            sonuclar.append(
                {"siparis_id": siparis_id, "siparis_no": fatura.siparis_no,
                 "durum": "taslak", "ettn": ""}
            )
        except GibHatasi as hata:
            depo.kaydet(
                siparis_id=siparis_id, siparis_no=fatura.siparis_no,
                durum="hata", tutar=f"{fatura.toplam:.2f}", hata=str(hata),
            )
            sonuclar.append(
                {"siparis_id": siparis_id, "siparis_no": fatura.siparis_no,
                 "durum": "hata", "hata": str(hata)}
            )

    # Yeni taslakları belge numarasına göre sırala; oluşturma sırasıyla eşleşir.
    yeni_taslaklar = []
    if olusturulanlar:
        try:
            hepsi = portal.taslaklari_getir(baslangic, bitis)
            yeni_taslaklar = sorted(
                (t for t in hepsi if t.get("ettn") not in onceki_ettnler),
                key=lambda t: t.get("belgeNumarasi", ""),
            )
        except GibHatasi:
            yeni_taslaklar = []

    eslesti = len(yeni_taslaklar) == len(olusturulanlar)
    for sira, (siparis_id, fatura) in enumerate(olusturulanlar):
        ettn = yeni_taslaklar[sira].get("ettn", "") if eslesti else ""
        depo.kaydet(
            siparis_id=siparis_id, siparis_no=fatura.siparis_no,
            durum="taslak", ettn=ettn, tutar=f"{fatura.toplam:.2f}",
        )
        for sonuc in sonuclar:
            if sonuc["siparis_id"] == siparis_id:
                sonuc["ettn"] = ettn

    basarili = len(olusturulanlar)
    cevap = {"basarili": basarili, "toplam": len(sonuclar), "sonuclar": sonuclar}
    if olusturulanlar and not eslesti:
        cevap["uyari"] = (
            f"{basarili} taslak oluştu ama portalda {len(yeni_taslaklar)} yeni kayıt "
            "göründü; ETTN eşleştirmesi yapılamadı. İmzalama yine de çalışır, "
            "sipariş-fatura eşleşmesini portaldan doğrulayın."
        )
    return cevap


@uygulama.post("/api/sms-iste")
def sms_iste() -> dict:
    portal = _gib()
    try:
        oid, telefon = portal.sms_kodu_iste()
    except GibHatasi as hata:
        raise HTTPException(400, str(hata))

    _durum["oid"] = oid
    _durum["telefon"] = telefon
    gizli = f"{telefon[:3]}***{telefon[-2:]}" if len(telefon) >= 5 else telefon
    return {"telefon": gizli, "bekleyen": len(depo.bekleyen_taslaklar())}


@uygulama.post("/api/imzala")
def imzala(istek: ImzaIstegi) -> dict:
    portal = _gib()
    oid = _durum.get("oid")
    if not oid:
        raise HTTPException(400, "Önce SMS kodu isteyin.")

    bekleyenler = depo.bekleyen_taslaklar()
    if not bekleyenler:
        raise HTTPException(400, "İmzalanacak taslak yok.")

    hedef_ettnler = {satir["ettn"] for satir in bekleyenler if satir["ettn"]}
    ettnsiz = [satir["siparis_no"] for satir in bekleyenler if not satir["ettn"]]
    if not hedef_ettnler:
        raise HTTPException(
            400,
            "Bekleyen taslakların ETTN'i eşleştirilemedi. "
            "Bu faturaları GİB portalından elle onaylayın.",
        )

    baslangic, bitis = _tarih_araligi()
    taslaklar = portal.taslaklari_getir(baslangic, bitis)
    imzalanacaklar = [t for t in taslaklar if t.get("ettn") in hedef_ettnler]

    if not imzalanacaklar:
        raise HTTPException(
            400,
            "Taslaklar GİB portalında bulunamadı. "
            "Portalda tarih aralığını kontrol edin.",
        )

    try:
        mesaj = portal.sms_ile_imzala(istek.kod, oid, imzalanacaklar)
    except GibHatasi as hata:
        raise HTTPException(400, str(hata))

    _durum["oid"] = None

    # İmzalananları Shopify'da etiketle.
    imzalanan_ettnler = {t.get("ettn") for t in imzalanacaklar}
    etiketlenen, etiket_hatalari = 0, []
    try:
        shopify = Shopify()
    except ShopifyHatasi as hata:
        shopify = None
        etiket_hatalari.append(str(hata))

    for satir in bekleyenler:
        if satir["ettn"] not in imzalanan_ettnler:
            continue
        depo.kaydet(
            siparis_id=satir["siparis_id"], siparis_no=satir["siparis_no"],
            durum="imzalandi", ettn=satir["ettn"], tutar=satir["tutar"] or "",
        )
        if shopify is None:
            continue
        try:
            shopify.faturalandi_isaretle(satir["siparis_id"], satir["ettn"])
            etiketlenen += 1
        except ShopifyHatasi as hata:
            etiket_hatalari.append(f"{satir['siparis_no']}: {hata}")

    if ettnsiz:
        etiket_hatalari.append(
            "ETTN'i eşleşmediği için atlananlar (portaldan elle onaylayın): "
            + ", ".join(ettnsiz)
        )

    return {
        "mesaj": mesaj,
        "imzalanan": len(imzalanacaklar),
        "etiketlenen": etiketlenen,
        "etiket_hatalari": etiket_hatalari,
    }


@uygulama.get("/api/gecmis")
def gecmis() -> dict:
    return {"kayitlar": depo.gecmis()}


uygulama.mount("/static", StaticFiles(directory=KOK / "static"), name="static")
