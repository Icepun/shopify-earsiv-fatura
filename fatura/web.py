"""Yerel onay paneli: siparişleri getir, gözden geçir, toplu fatura kes."""

from __future__ import annotations

import os
import re
import sys
import uuid
import zipfile
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, depo, gunluk, shopify_api, ubl
from . import guncelleme as guncelleme_modulu
from .donustur import Fatura, siparisi_faturaya_cevir
from .guncelleme import guncelleme_kontrol
from .gunluk import kayit
from .shopify_api import ODENMIS, Shopify, ShopifyHatasi

uygulama = FastAPI(title="Shopify → e-Arşiv Fatura")
# Paketlenmiş .exe içinde static/ geçici klasöre açılır; yolu config verir.
KOK = config.kaynak_klasoru()

# Son listelenen siparişlerin numaraları (id -> "#1105"); yalnızca mesajlarda
# okunaklı ad göstermek için. Fatura verisi bellekte tutulmuyor: önizleme ve
# üretim her seferinde Shopify'dan taze çekiyor (bkz. _taze_faturalar).
_numaralar: dict[str, str] = {}


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


def _taze_faturalar(siparis_idler: list[str], duzeltmeler: dict) -> list[Fatura]:
    """Seçili siparişleri Shopify'dan yeniden çekip faturaya çevirir.

    Sunucu eskiden son çekilen listeyi bellekte tutuyordu. Ayar kaydetmek o
    belleği sildiği için "sipariş bellekte yok" hatası çıkıyor, liste bayatsa
    arada iptal ya da iade olmuş sipariş eski haliyle faturalanabiliyordu.

    Artık faturalanamayacak bir sipariş varsa hiçbiri işlenmez; hangileri
    olduğu kullanıcıya söylenir.
    """
    idler = list(dict.fromkeys(siparis_idler))
    try:
        ham = Shopify().siparisleri_getir(idler)
    except ShopifyHatasi as hata:
        raise HTTPException(400, str(hata))

    faturalar: list[Fatura] = []
    sorunlar: list[str] = []
    for siparis_id in idler:
        siparis = ham.get(siparis_id)
        if siparis is None:
            sorunlar.append(f"{_numaralar.get(siparis_id, 'Bir sipariş')} bulunamadı")
            continue
        no = siparis.get("name") or siparis_id
        _numaralar[siparis_id] = no
        if siparis.get("cancelledAt"):
            sorunlar.append(f"{no} iptal edilmiş")
        elif siparis.get("displayFinancialStatus") == "REFUNDED":
            sorunlar.append(f"{no} iade edilmiş")
        elif siparis.get("displayFinancialStatus") not in ODENMIS:
            sorunlar.append(f"{no} için ödeme tamamlanmamış")
        elif config.ETIKET in (siparis.get("tags") or []):
            sorunlar.append(f"{no} zaten faturalanmış")
        else:
            fatura = siparisi_faturaya_cevir(siparis)
            _duzeltmeleri_uygula(fatura, duzeltmeler.get(siparis_id, {}))
            faturalar.append(fatura)
    if sorunlar:
        raise HTTPException(
            400, ", ".join(sorunlar) + ". Siparişleri yeniden getirin."
        )
    return faturalar


# ─── istek gövdeleri ─────────────────────────────────────────────────


class TaslakIstegi(BaseModel):
    siparis_idler: list[str]
    duzeltmeler: dict[str, dict] = {}
    # Fatura tarihi siparişin kendi tarihi yerine bugün olsun mu?
    # Mali müşavir, birikmiş geçmiş siparişlerin bugünün tarihiyle
    # kesilmesini istedi; bundan sonrakiler sipariş tarihiyle gidiyor.
    bugun_tarihli: bool = False
    # Kullanıcının gözden geçirme ekranında gördüğü toplamlar (id -> "449.99").
    # Üretim anında taze veriyle tutmuyorsa sipariş arada değişmiştir.
    beklenen_toplamlar: dict[str, str] = {}


class IsaretIstegi(BaseModel):
    siparis_idler: list[str]


# ─── uçlar ───────────────────────────────────────────────────────────


@uygulama.on_event("startup")
def _baslangic() -> None:
    gunluk.kur()
    kayit.info("acilis: surum %s", config.SURUM)
    depo.eski_veritabanini_tasi()
    depo.hazirla()


@uygulama.exception_handler(Exception)
async def _beklenmeyen_hata(istek: Request, hata: Exception) -> JSONResponse:
    """Yakalanmamış her hatayı günlüğe yazar ve panele okunur bir yanıt verir.

    Bu olmadan panel yalnızca "HTTP 500" gösteriyor, hatanın ne olduğu da
    hiçbir yere düşmüyordu.
    """
    kayit.error("beklenmeyen hata: %s %s", istek.method, istek.url.path, exc_info=hata)
    return JSONResponse(
        status_code=500,
        content={"detail": "Beklenmeyen bir sorun oluştu. Yeniden deneyin."},
    )


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
    # Sıra ayar dosyasından değil sayaçtan okunuyor; ekrandaki değer her
    # zaman en son verilen numara olsun.
    duzenlenebilir["fatura_sira"] = depo.son_sira(
        config.fatura_serisi(), datetime.now().year
    )
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
    yeni = dict(istek.ayarlar)
    # Sıra yalnızca kullanıcı elle değiştirdiyse gelir. Formdaki değer her
    # kayıtta gönderilirken, fatura ürettikten sonra ayar kaydetmek sayacı
    # geri sarıyor ve aynı numaralar ikinci kez veriliyordu.
    istenen_sira = yeni.pop("fatura_sira", None)
    if istenen_sira is not None:
        try:
            istenen_sira = max(0, int(str(istenen_sira).strip()))
        except ValueError:
            raise HTTPException(400, "Sıra bir sayı olmalı.")

    # Belge numarası seri (3) + yıl (4) + sıra (9) = 16 hane olmak zorunda;
    # seri kısa ya da Türkçe harfli olursa portal dosyayı reddeder.
    if str(yeni.get("fatura_seri") or "").strip():
        yeni["fatura_seri"] = str(yeni["fatura_seri"]).strip().upper()
        if not re.fullmatch(r"[A-Z0-9]{3}", yeni["fatura_seri"]):
            raise HTTPException(
                400, "Seri 3 karakter olmalı: yalnızca A-Z harfleri ve rakam."
            )

    config.kaydet(yeni)

    # Ayar değişince Shopify tokeni geçersiz olabilir, önbelleği bırakıyoruz.
    shopify_api._token_deposu.temizle()
    _numaralar.clear()
    depo.hazirla()

    sira_indirilemedi = False
    if istenen_sira is not None:
        gecerli = depo.sirayi_ayarla(
            config.fatura_serisi(), datetime.now().year, istenen_sira
        )
        config.kaydet({"fatura_sira": gecerli})
        sira_indirilemedi = gecerli != istenen_sira
    return {**ayarlar(), "sira_indirilemedi": sira_indirilemedi}


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
    gizliler: bool = False,
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

    kayitlar = depo.kayitlari_getir([siparis["id"] for siparis in ham])
    gizli = depo.gizli_idler()
    _numaralar.clear()

    sonuc = []
    for siparis in ham:
        # Gizlenenler listeye hiç düşmez; yalnızca "gizlenenleri göster"
        # işaretliyken, geri almak için görünürler.
        gizli_mi = siparis["id"] in gizli
        if gizli_mi and not gizliler:
            continue
        fatura = siparisi_faturaya_cevir(siparis)
        _numaralar[siparis["id"]] = fatura.siparis_no

        fatura_kaydi = kayitlar.get(siparis["id"])
        etiketli = config.ETIKET in (siparis.get("tags") or [])
        kayit_durumu = (fatura_kaydi or {}).get("durum")
        if etiketli or kayit_durumu == "imzalandi":
            durum = "faturalandi"
        elif kayit_durumu == "taslak":
            durum = "xml_uretildi"
        else:
            durum = "bekliyor"

        satir = _fatura_sozlugu(fatura)
        satir["durum"] = "gizli" if gizli_mi else durum
        satir["gizli"] = gizli_mi
        satir["belge_no"] = (fatura_kaydi or {}).get("belge_no") or ""
        satir["ettn"] = (fatura_kaydi or {}).get("ettn") or ""
        satir["kismi_iade"] = siparis.get("displayFinancialStatus") == "PARTIALLY_REFUNDED"
        sonuc.append(satir)

    return {
        "adet": len(sonuc),
        "faturalar": sonuc,
        "bekleyen": sum(1 for x in sonuc if x["durum"] == "bekliyor"),
        "gizli_toplam": len(gizli),
        "sinir_doldu": len(ham) >= limit,
        "sinir": limit,
    }


@uygulama.post("/api/onizleme")
def onizleme(istek: TaslakIstegi) -> dict:
    """Seçilenleri düzeltmelerle birlikte gözden geçirmeye hazırlar.

    XML üretmez; kullanıcı kontrol ettikten sonra /api/xml-uret çağrılır.
    """
    sonuc = []
    for fatura in _taze_faturalar(istek.siparis_idler, istek.duzeltmeler):
        satir = _fatura_sozlugu(fatura)
        # İlçe burada aranmıyor: portal adresi yazıldığı gibi kabul ediyor,
        # müşterilerin yarısından fazlası da ilçeyi ayrıca yazmıyor.
        satir["eksikler"] = [
            ad for ad, deger in (
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

    # Hiçbir şey üretmeden önce bütün seçimi sına: parti yarıda kalmasın.
    secilen = _taze_faturalar(istek.siparis_idler, istek.duzeltmeler)
    if not secilen:
        raise HTTPException(400, "Üretilecek fatura yok.")
    kalemsiz = [f.siparis_no for f in secilen
                if not f.kalemler or f.toplam <= 0 or not f.tarih]
    if kalemsiz:
        raise HTTPException(
            400, "Faturalanacak tutarı olmayan sipariş var: " + ", ".join(kalemsiz)
        )
    degisen = [
        f.siparis_no for f in secilen
        if istek.beklenen_toplamlar.get(f.siparis_id) not in (None, f"{f.toplam:.2f}")
    ]
    if degisen:
        raise HTTPException(
            400, "Tutarı değişen sipariş var: " + ", ".join(degisen)
            + ". Siparişleri yeniden getirin."
        )

    # Numaralar eskiden yeniye verilir: belge numarası büyüdükçe fatura
    # tarihi geriye gitmesin.
    secilen.sort(key=lambda f: (f.zaman, f.siparis_no))

    satici = _satici_ayarlardan()
    seri = config.fatura_serisi()
    simdi = datetime.now()

    klasor = (config.veri_klasoru() / "faturalar"
              / simdi.strftime("%Y-%m-%d_%H%M%S"))
    klasor.mkdir(parents=True, exist_ok=True)

    uretilen: list[dict] = []
    hata_mesaji = ""
    for fatura in secilen:
        if istek.bugun_tarihli:
            belge_tarihi = simdi.strftime("%Y-%m-%d")
            belge_saati = simdi.strftime("%H:%M:%S")
        else:
            gun, ay, yil = fatura.tarih.split("/")
            belge_tarihi, belge_saati = f"{yil}-{ay}-{gun}", ""
        ettn = str(uuid.uuid4())
        yazilan: list[Path] = []

        def yaz(belge_no: str) -> str:
            xml = ubl.ubl_fatura(
                fatura, satici, belge_no=belge_no, ettn=ettn,
                belge_tarihi=belge_tarihi, belge_saati=belge_saati,
            )
            ad = ubl.dosya_adi(satici.tckn, belge_no, ettn)
            yazilan.append(klasor / ad)
            (klasor / ad).write_text(xml, encoding="utf-8")
            return ad

        # Numara, dosya ve kayıt tek işlemde: portal her ETTN'yi bir kez
        # kabul ediyor, iz kalmazsa aynı siparişe ikinci fatura üretilebilir.
        # Numaradaki yıl fatura tarihinin yılıdır.
        try:
            belge = depo.belge_uret(
                seri=seri, yil=int(belge_tarihi[:4]),
                siparis_id=fatura.siparis_id, siparis_no=fatura.siparis_no,
                ettn=ettn, tutar=f"{fatura.toplam:.2f}",
                fatura_tarihi=belge_tarihi, yaz=yaz,
            )
        except Exception as hata:  # disk, veritabanı ya da beklenmeyen veri
            for yol in yazilan:
                yol.unlink(missing_ok=True)
            kayit.error("%s uretilemedi", fatura.siparis_no, exc_info=hata)
            hata_mesaji = f"{fatura.siparis_no} üretilemedi: {hata}"
            break

        uretilen.append({
            "siparis_id": fatura.siparis_id, "siparis_no": fatura.siparis_no,
            "belge_no": belge["belge_no"], "ettn": ettn, "dosya": belge["dosya"],
            "toplam": f"{fatura.toplam:.2f}",
            "fatura_tarihi": (simdi.strftime("%d/%m/%Y")
                              if istek.bugun_tarihli else fatura.tarih),
            "siparis_tarihi": fatura.tarih,
        })

    if not uretilen:
        try:
            klasor.rmdir()
        except OSError:
            pass
        raise HTTPException(500, hata_mesaji or "Fatura üretilemedi.")

    zip_adi = f"faturalar_{len(uretilen)}_adet.zip"
    with zipfile.ZipFile(klasor / zip_adi, "w", zipfile.ZIP_DEFLATED) as z:
        for satir in uretilen:
            z.write(klasor / satir["dosya"], arcname=satir["dosya"])

    # Ayar dosyasındaki sıra yedektir (bkz. config.ALANLAR > fatura_sira).
    config.kaydet({"fatura_sira": depo.son_sira(seri, simdi.year)})
    kayit.info(
        "xml uretildi: %d adet, %s - %s%s", len(uretilen),
        uretilen[0]["belge_no"], uretilen[-1]["belge_no"],
        f" | yarida kaldi: {hata_mesaji}" if hata_mesaji else "",
    )
    return {
        "adet": len(uretilen),
        "klasor": str(klasor),
        "zip": zip_adi,
        "faturalar": uretilen,
        # Parti yarıda kaldıysa: buraya kadar üretilenler geçerli, kalanlar
        # üretilmedi ve numara almadı.
        "hata": hata_mesaji,
        "uretilmeyen": len(secilen) - len(uretilen),
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

    kayitlar = depo.kayitlari_getir(istek.siparis_idler)
    basarili, hatalar = 0, []
    for siparis_id in istek.siparis_idler:
        fatura_kaydi = kayitlar.get(siparis_id) or {}
        siparis_no = (fatura_kaydi.get("siparis_no")
                      or _numaralar.get(siparis_id) or siparis_id)
        try:
            shopify.faturalandi_isaretle(siparis_id, fatura_kaydi.get("ettn") or "")
            depo.kaydet(
                siparis_id=siparis_id, siparis_no=siparis_no,
                durum="imzalandi", ettn=fatura_kaydi.get("ettn") or "",
                tutar=fatura_kaydi.get("tutar") or "",
                belge_no=fatura_kaydi.get("belge_no") or "",
            )
            depo.yuklendi_isaretle(siparis_id)
            basarili += 1
        except ShopifyHatasi as hata:
            hatalar.append(f"{siparis_no}: {hata}")

    kayit.info("isaretlendi: %d siparis, %d hata", basarili, len(hatalar))
    return {"isaretlenen": basarili, "hatalar": hatalar}


@uygulama.get("/api/bekleyenler")
def bekleyenler() -> dict:
    """XML'i üretilmiş ama henüz "faturalandı" diye işaretlenmemiş siparişler.

    Panel bunları açılışta ayrı bir kutuda gösteriyor. Kutu olmadan, 3. adımı
    işaretlemeden kapatan kullanıcının tek yolu aynı siparişi yeni numarayla
    yeniden üretmekti.
    """
    satirlar = [dict(satir) for satir in depo.bekleyen_taslaklar()]
    return {
        "adet": len(satirlar),
        "ettnsiz": sum(1 for satir in satirlar if not satir.get("ettn")),
        "taslaklar": satirlar,
    }


@uygulama.post("/api/faturayi-geri-al")
def faturayi_geri_al(istek: IsaretIstegi) -> dict:
    """Yanlış kesilen faturaları geri alır: etiket kaldırılır, belge iptal olur.

    Sipariş yeniden "faturalanmamış" olur ve yeni belge numarası + yeni ETTN
    ile tekrar üretilebilir; eski belge geçmişte 'iptal' olarak kalır.
    Portaldaki eski faturayı silmek kullanıcının işi — bu uç yalnızca bizim
    tarafı temizler.
    """
    try:
        shopify = Shopify()
    except ShopifyHatasi as hata:
        raise HTTPException(400, str(hata))

    kayitlar = depo.kayitlari_getir(istek.siparis_idler)
    geri_alinan, hatalar = 0, []
    for siparis_id in istek.siparis_idler:
        fatura_kaydi = kayitlar.get(siparis_id) or {}
        no = (fatura_kaydi.get("siparis_no")
              or _numaralar.get(siparis_id) or siparis_id)
        try:
            shopify.faturalandi_etiketini_kaldir(siparis_id)
            depo.geri_al(siparis_id)
            geri_alinan += 1
            kayit.info("geri alindi: %s %s", no, fatura_kaydi.get("belge_no") or "")
        except ShopifyHatasi as hata:
            hatalar.append(f"{no}: {hata}")

    return {"geri_alinan": geri_alinan, "hatalar": hatalar}


@uygulama.post("/api/gizle")
def gizle(istek: IsaretIstegi) -> dict:
    """Seçilen siparişleri listeden kalıcı olarak çıkarır (deneme siparişleri).

    Fatura durumuna dokunmaz; tek tıkla geri alınabilir.
    """
    for siparis_id in istek.siparis_idler:
        depo.gizle(siparis_id, _numaralar.get(siparis_id, ""))
    return {"gizlenen": len(istek.siparis_idler), "toplam": len(depo.gizli_idler())}


@uygulama.post("/api/gizlemeyi-kaldir")
def gizlemeyi_kaldir(istek: IsaretIstegi) -> dict:
    for siparis_id in istek.siparis_idler:
        depo.gizlemeyi_kaldir(siparis_id)
    return {"kaldirilan": len(istek.siparis_idler), "toplam": len(depo.gizli_idler())}


@uygulama.get("/api/tani")
def tani() -> dict:
    """Ayarların nereden okunduğunu döner (ayarlar ekranında gösteriliyor)."""
    return config.tani()


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
