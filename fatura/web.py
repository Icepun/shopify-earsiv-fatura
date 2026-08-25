"""Yerel onay paneli: siparişleri getir, gözden geçir, toplu fatura kes."""

from __future__ import annotations

import os
import sys
import uuid
import zipfile
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, depo, shopify_api, ubl
from . import guncelleme as guncelleme_modulu
from .donustur import Fatura, siparisi_faturaya_cevir
from .guncelleme import guncelleme_kontrol
from .shopify_api import Shopify, ShopifyHatasi

uygulama = FastAPI(title="Shopify → e-Arşiv Fatura")
# Paketlenmiş .exe içinde static/ geçici klasöre açılır; yolu config verir.
KOK = config.kaynak_klasoru()

# Panel oturumu: son çekilen siparişler ve hesaplanan faturalar bellekte.
_durum: dict = {"siparisler": {}, "faturalar": {}}


# ─── yardımcılar ─────────────────────────────────────────────────────


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


class IsaretIstegi(BaseModel):
    siparis_idler: list[str]


# ─── uçlar ───────────────────────────────────────────────────────────


@uygulama.on_event("startup")
def _baslangic() -> None:
    depo.hazirla()


@uygulama.get("/", response_class=HTMLResponse)
def panel() -> FileResponse:
    return FileResponse(KOK / "static" / "index.html")


@uygulama.get("/api/ayarlar")
def ayarlar() -> dict:
    ham = config.ayarlar()
    # Gizli alanların değeri arayüze hiç gönderilmiyor; yalnızca dolu olup
    # olmadıkları bildiriliyor ki ekran "kayıtlı" yazabilsin.
    duzenlenebilir = {
        ad: ("" if ad in config.GIZLI_ALANLAR else deger)
        for ad, deger in ham.items()
    }
    return {
        "magaza": config.SHOPIFY_STORE,
        "test_modu": config.GIB_TEST_MODU,
        "kdv_orani": config.KDV_ORANI,
        "kargoyu_dagit": config.KARGOYU_DAGIT,
        "baslangic_tarihi": config.BASLANGIC_TARIHI,
        "eksik_ayarlar": config.eksik_ayarlar(),
        "surum": config.SURUM,
        "duzenlenebilir": duzenlenebilir,
        "dolu_gizliler": {ad: bool(ham.get(ad)) for ad in config.GIZLI_ALANLAR},
    }


class AyarIstegi(BaseModel):
    ayarlar: dict


@uygulama.post("/api/ayarlar")
def ayarlari_kaydet(istek: AyarIstegi) -> dict:
    config.kaydet(istek.ayarlar)

    # Ayar değişince Shopify tokeni geçersiz olabilir, önbelleği bırakıyoruz.
    shopify_api._token_deposu.temizle()
    _durum.update({"siparisler": {}, "faturalar": {}})
    depo.hazirla()
    return ayarlar()


@uygulama.post("/api/baglanti-testi")
def baglanti_testi() -> dict:
    """Ayarlar ekranındaki "Bağlantıyı Sına" düğmesi.

    kontrol.bat'ın yaptığını uygulama içinde yapar; kullanıcının konsola
    düşmesi gerekmesin diye.
    """
    sonuc: dict = {}

    try:
        istemci = Shopify()
        siparisler = istemci.faturalanmamis_siparisler(limit=1)
        sonuc["shopify"] = {
            "durum": "iyi",
            "mesaj": f"{istemci.magaza} bağlantısı çalışıyor "
                     f"({istemci.kimlik_yontemi} ile).",
            "siparis_var": bool(siparisler),
        }
    except ShopifyHatasi as hata:
        sonuc["shopify"] = {"durum": "hata", "mesaj": str(hata)}

    return sonuc


class OrnekIstegi(BaseModel):
    xml: str


@uygulama.post("/api/ornekten-doldur")
def ornekten_doldur(istek: OrnekIstegi) -> dict:
    """Portaldan indirilmiş bir faturadan satıcı bilgilerini doldurur.

    Kullanıcının TCKN, vergi dairesi, adres gibi alanları elle yazmasına gerek
    kalmıyor; e-Faturam'da kestiği herhangi bir faturayı veriyor.
    """
    try:
        satici, seri = ubl.saticiyi_oku(istek.xml)
    except ValueError as hata:
        raise HTTPException(400, str(hata))
    if not satici.tckn:
        raise HTTPException(400, "Faturada satıcı TCKN/VKN'si bulunamadı.")

    yeni = {
        "satici_tckn": satici.tckn, "satici_ad": satici.ad,
        "satici_soyad": satici.soyad, "satici_unvan": satici.unvan,
        "satici_vergi_dairesi": satici.vergi_dairesi,
        "satici_mahalle": satici.mahalle, "satici_bina_no": satici.bina_no,
        "satici_kapi_no": satici.kapi_no, "satici_ilce": satici.ilce,
        "satici_il": satici.il, "satici_posta_kodu": satici.posta_kodu,
        "satici_telefon": satici.telefon, "satici_eposta": satici.eposta,
    }
    config.kaydet(yeni)
    return {"tamam": True, "ayarlar": yeni, "ornek_seri": seri}


@uygulama.get("/api/siparisler")
def siparisler(
    tetikleyici: str = "fulfilled",
    limit: int = 200,
    baslangic: str = "",
    bitis: str = "",
    hepsi: bool = False,
) -> dict:
    """Siparişleri getirir ve her birinin fatura durumunu işaretler.

    hepsi=True ise faturalanmış siparişler de listelenir; onlar seçilemez,
    yalnızca durumu görünsün diye gösterilir.
    """
    try:
        istemci = Shopify()
        ham = istemci.faturalanmamis_siparisler(
            tetikleyici=tetikleyici, limit=limit,
            baslangic=baslangic, bitis=bitis,
            yalnizca_faturasiz=not hepsi,
        )
    except ShopifyHatasi as hata:
        raise HTTPException(400, str(hata))

    kayitlar = {k["siparis_id"]: k for k in depo.gecmis(limit=2000)}
    _durum["siparisler"] = {}
    _durum["faturalar"] = {}

    sonuc = []
    for siparis in ham:
        fatura = siparisi_faturaya_cevir(siparis)
        _durum["siparisler"][siparis["id"]] = siparis
        _durum["faturalar"][siparis["id"]] = fatura

        kayit = kayitlar.get(siparis["id"])
        etiketli = config.ETIKET in (siparis.get("tags") or [])
        kayit_durumu = (kayit or {}).get("durum")
        if etiketli or kayit_durumu == "imzalandi":
            durum = "faturalandi"
        elif kayit_durumu == "taslak":
            durum = "xml_uretildi"
        else:
            durum = "bekliyor"

        satir = _fatura_sozlugu(fatura)
        satir["durum"] = durum
        satir["belge_no"] = (kayit or {}).get("belge_no") or ""
        satir["ettn"] = (kayit or {}).get("ettn") or ""
        sonuc.append(satir)

    return {
        "adet": len(sonuc),
        "faturalar": sonuc,
        "bekleyen": sum(1 for x in sonuc if x["durum"] == "bekliyor"),
        "sinir_doldu": len(ham) >= limit,
        "sinir": limit,
    }


@uygulama.post("/api/onizleme")
def onizleme(istek: TaslakIstegi) -> dict:
    """Seçilenleri düzeltmelerle birlikte gözden geçirmeye hazırlar.

    XML üretmez; kullanıcı kontrol ettikten sonra /api/xml-uret çağrılır.
    """
    sonuc = []
    for siparis_id in istek.siparis_idler:
        fatura = _durum["faturalar"].get(siparis_id)
        if fatura is None:
            raise HTTPException(400, "Sipariş bellekte yok, listeyi yenileyin.")
        _duzeltmeleri_uygula(fatura, istek.duzeltmeler.get(siparis_id, {}))
        satir = _fatura_sozlugu(fatura)
        satir["eksikler"] = [
            ad for ad, deger in (
                ("ilçe", fatura.alici.ilce),
                ("şehir", fatura.alici.sehir),
                ("adres", fatura.alici.adres),
                ("ad soyad", (fatura.alici.ad + fatura.alici.soyad)),
            ) if not (deger or "").strip()
        ]
        sonuc.append(satir)
    return {"adet": len(sonuc), "faturalar": sonuc}


def _satici_ayarlardan() -> ubl.Satici:
    a = config.ayarlar()
    return ubl.Satici(
        tckn=a.get("satici_tckn", ""), ad=a.get("satici_ad", ""),
        soyad=a.get("satici_soyad", ""), unvan=a.get("satici_unvan", ""),
        vergi_dairesi=a.get("satici_vergi_dairesi", ""),
        mahalle=a.get("satici_mahalle", ""), bina_no=a.get("satici_bina_no", ""),
        kapi_no=a.get("satici_kapi_no", ""), ilce=a.get("satici_ilce", ""),
        il=a.get("satici_il", ""), posta_kodu=a.get("satici_posta_kodu", ""),
        telefon=a.get("satici_telefon", ""), eposta=a.get("satici_eposta", ""),
    )


@uygulama.post("/api/xml-uret")
def xml_uret(istek: TaslakIstegi) -> dict:
    """Seçilen siparişler için UBL-TR XML üretir ve klasöre yazar."""
    ayar = config.ayarlar()
    eksik = [a for a in ("satici_tckn", "satici_ad", "satici_vergi_dairesi")
             if not ayar.get(a)]
    if eksik:
        raise HTTPException(
            400, "Ayarlar'da satıcı bilgileri eksik: TCKN, ad ve vergi dairesi."
        )

    satici = _satici_ayarlardan()
    seri = ayar.get("fatura_seri", "MGL")
    sira = int(ayar.get("fatura_sira", 0))
    yil = datetime.now().year

    klasor = (config.veri_klasoru() / "faturalar"
              / datetime.now().strftime("%Y-%m-%d_%H%M"))
    klasor.mkdir(parents=True, exist_ok=True)

    uretilen = []
    for siparis_id in istek.siparis_idler:
        fatura = _durum["faturalar"].get(siparis_id)
        if fatura is None:
            continue
        _duzeltmeleri_uygula(fatura, istek.duzeltmeler.get(siparis_id, {}))

        sira += 1
        belge_no = f"{seri}{yil}{sira:09d}"
        ettn = str(uuid.uuid4())
        xml = ubl.ubl_fatura(fatura, satici, belge_no=belge_no, ettn=ettn)
        ad = ubl.dosya_adi(satici.tckn, belge_no, ettn)
        (klasor / ad).write_text(xml, encoding="utf-8")

        # Üretim anında kaydediyoruz: portal her ETTN'yi bir kez kabul ediyor,
        # iz kalmazsa aynı siparişe ikinci fatura üretilebilir.
        depo.kaydet(
            siparis_id=siparis_id, siparis_no=fatura.siparis_no,
            durum="taslak", ettn=ettn, tutar=f"{fatura.toplam:.2f}",
            belge_no=belge_no,
        )
        uretilen.append({
            "siparis_id": siparis_id, "siparis_no": fatura.siparis_no,
            "belge_no": belge_no, "ettn": ettn, "dosya": ad,
            "toplam": f"{fatura.toplam:.2f}",
        })

    if not uretilen:
        raise HTTPException(400, "Üretilecek fatura yok, listeyi yenileyin.")

    zip_adi = f"faturalar_{len(uretilen)}_adet.zip"
    with zipfile.ZipFile(klasor / zip_adi, "w", zipfile.ZIP_DEFLATED) as z:
        for kayit in uretilen:
            z.write(klasor / kayit["dosya"], arcname=kayit["dosya"])

    config.kaydet({"fatura_sira": sira})
    return {
        "adet": len(uretilen),
        "klasor": str(klasor),
        "zip": zip_adi,
        "faturalar": uretilen,
    }


class KlasorIstegi(BaseModel):
    klasor: str


@uygulama.post("/api/klasoru-ac")
def klasoru_ac(istek: KlasorIstegi) -> dict:
    """Üretilen XML'lerin klasörünü Dosya Gezgini'nde açar."""
    kok = (config.veri_klasoru() / "faturalar").resolve()
    yol = Path(istek.klasor)
    try:
        # Yalnızca kendi ürettiğimiz klasörler açılabilsin.
        yol.resolve().relative_to(kok)
    except ValueError:
        raise HTTPException(400, "Klasör açılamadı.")
    if sys.platform == "win32" and yol.is_dir():
        os.startfile(str(yol))
        return {"tamam": True}
    return {"tamam": False}


@uygulama.post("/api/isaretle")
def isaretle(istek: IsaretIstegi) -> dict:
    """Portala yüklenip onaylananları Shopify'da 'faturalandi' işaretler."""
    try:
        shopify = Shopify()
    except ShopifyHatasi as hata:
        raise HTTPException(400, str(hata))

    kayitlar = {k["siparis_id"]: k for k in depo.gecmis(limit=2000)}
    basarili, hatalar = 0, []
    for siparis_id in istek.siparis_idler:
        kayit = kayitlar.get(siparis_id) or {}
        fatura = _durum["faturalar"].get(siparis_id)
        siparis_no = kayit.get("siparis_no") or (
            fatura.siparis_no if fatura else siparis_id)
        try:
            shopify.faturalandi_isaretle(siparis_id, kayit.get("ettn") or "")
            depo.kaydet(
                siparis_id=siparis_id, siparis_no=siparis_no,
                durum="imzalandi", ettn=kayit.get("ettn") or "",
                tutar=kayit.get("tutar") or "",
                belge_no=kayit.get("belge_no") or "",
            )
            basarili += 1
        except ShopifyHatasi as hata:
            hatalar.append(f"{siparis_no}: {hata}")

    return {"isaretlenen": basarili, "hatalar": hatalar}


@uygulama.get("/api/bekleyenler")
def bekleyenler() -> dict:
    """Taslağı oluşmuş ama henüz imzalanmamış faturalar.

    Panel taslak oluşturduktan sonra satırları listeden düşürüyor; bu uç
    olmadan kullanıcı faturaların nereye gittiğini göremiyordu.
    """
    satirlar = [dict(satir) for satir in depo.bekleyen_taslaklar()]
    return {
        "adet": len(satirlar),
        "ettnsiz": sum(1 for satir in satirlar if not satir.get("ettn")),
        "taslaklar": satirlar,
    }


@uygulama.get("/api/gecmis")
def gecmis() -> dict:
    return {"kayitlar": depo.gecmis()}


# ─── güncelleme ──────────────────────────────────────────────────────


class IndirmeIstegi(BaseModel):
    url: str


@uygulama.get("/api/guncelleme")
def guncelleme() -> dict:
    return guncelleme_kontrol()


@uygulama.post("/api/guncelleme/indir")
def guncelleme_indir(istek: IndirmeIstegi) -> dict:
    if not istek.url.startswith("https://github.com/"):
        raise HTTPException(400, "Beklenmeyen indirme adresi.")
    return guncelleme_modulu.indirmeyi_baslat(istek.url)


@uygulama.get("/api/guncelleme/durum")
def guncelleme_durum() -> dict:
    return guncelleme_modulu.durum()


@uygulama.post("/api/guncelleme/kur")
def guncelleme_kur() -> dict:
    return guncelleme_modulu.kuruluma_gec()


uygulama.mount("/static", StaticFiles(directory=KOK / "static"), name="static")
