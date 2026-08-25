"""Ayarlar.

Ayarlar iki kaynaktan gelebilir:

1. `ayarlar.json` — uygulamanın kendi ayarlar ekranından yazılır. Asıl kaynak
   budur; kullanıcı dosya kurcalamaz.
2. `.env` — eski/geliştirici akışı. `ayarlar.json` yoksa bir kereliğine
   buradan okunup devralınır, böylece mevcut kurulumlar bozulmaz.

Modül düzeyindeki BÜYÜK_HARF adlar geri uyumluluk için duruyor;
`yeniden_yukle()` onları yerinde tazeliyor, dolayısıyla ayarlar ekranından
kaydetmek uygulamayı yeniden başlatmayı gerektirmiyor.
"""

from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path

from dotenv import dotenv_values

KOK = Path(__file__).resolve().parent.parent

SURUM = "1.1.4"
UYGULAMA_ADI = "Magicland Fatura"
GITHUB_DEPO = "Icepun/shopify-earsiv-fatura"

SHOPIFY_API_SURUMU = "2025-07"
ETIKET = "faturalandi"
NIHAI_TUKETICI_TCKN = "11111111111"

# Ayar adı -> (.env karşılığı, varsayılan)
ALANLAR: dict[str, tuple[str, object]] = {
    "shopify_magaza":          ("SHOPIFY_STORE", ""),
    "shopify_istemci_kimligi": ("SHOPIFY_ISTEMCI_KIMLIGI", ""),
    "shopify_gizli_anahtar":   ("SHOPIFY_GIZLI_ANAHTAR", ""),
    "shopify_token":           ("SHOPIFY_TOKEN", ""),
    "gib_kullanici_kodu":      ("GIB_KULLANICI_KODU", ""),
    "gib_sifre":               ("GIB_SIFRE", ""),
    "gib_test_modu":           ("GIB_TEST_MODU", True),
    "kdv_orani":               ("KDV_ORANI", 20),
    "kargoyu_dagit":           ("KARGOYU_DAGIT", True),
    "fatura_notu":             ("FATURA_NOTU", ""),
    "baslangic_tarihi":        ("BASLANGIC_TARIHI", ""),
    # ── Hepsiburada e-Faturam XML üretimi ──
    # Fatura numarası seri + yıl + 9 hane: MGL2026000000001
    "fatura_seri":             ("FATURA_SERI", "MGL"),
    "fatura_sira":             ("FATURA_SIRA", 0),
    # Faturayı kesen (mükellef) bilgileri — örnek faturadan alındı
    "satici_tckn":             ("SATICI_TCKN", ""),
    "satici_ad":               ("SATICI_AD", ""),
    "satici_soyad":            ("SATICI_SOYAD", ""),
    "satici_unvan":            ("SATICI_UNVAN", ""),
    "satici_vergi_dairesi":    ("SATICI_VERGI_DAIRESI", ""),
    "satici_mahalle":          ("SATICI_MAHALLE", ""),
    "satici_bina_no":          ("SATICI_BINA_NO", ""),
    "satici_kapi_no":          ("SATICI_KAPI_NO", ""),
    "satici_ilce":             ("SATICI_ILCE", ""),
    "satici_il":               ("SATICI_IL", ""),
    "satici_posta_kodu":       ("SATICI_POSTA_KODU", ""),
    "satici_telefon":          ("SATICI_TELEFON", ""),
    "satici_eposta":           ("SATICI_EPOSTA", ""),
}

# Ayarlar ekranına değeri gönderilmeyen, yalnızca yazılabilen alanlar.
GIZLI_ALANLAR = {"shopify_gizli_anahtar", "shopify_token", "gib_sifre"}

# Boş gelirse ESKİ DEĞERİ KORUNAN alanlar.
#
# Bunlar kimlik bilgileri: boşaltmanın hiçbir geçerli sebebi yok, ama boş bir
# formun kaydedilmesi (ekran dolmadan Kaydet'e basmak, yarım yüklenen sayfa,
# eski bir sekme) hepsini birden siliyordu. Boş değer artık "değiştirme"
# demek; gerçekten silmek isteyen ayar dosyasını elle düzenler.
KORUNAN_ALANLAR = {
    "shopify_magaza", "shopify_istemci_kimligi",
    "satici_tckn", "satici_ad", "satici_soyad", "satici_vergi_dairesi",
    "satici_mahalle", "satici_bina_no", "satici_kapi_no",
    "satici_ilce", "satici_il", "satici_posta_kodu",
    "satici_telefon", "satici_eposta", "fatura_seri",
} | GIZLI_ALANLAR

_ayarlar: dict = {}


def paketlenmis() -> bool:
    """PyInstaller ile .exe haline getirildi mi?"""
    return getattr(sys, "frozen", False)


def veri_klasoru() -> Path:
    """Ayarların ve veritabanının durduğu klasör.

    .exe tek dosya olarak çalışırken program klasörü geçici bir dizine
    açılıyor ve kapanışta siliniyor; ayarları oraya yazmak olmaz. Kaynaktan
    çalışırken proje klasörü kalıyor ki geliştirme akışı bozulmasın.
    """
    if not paketlenmis():
        return KOK
    taban = os.getenv("APPDATA") or os.getenv("LOCALAPPDATA") or str(Path.home())
    klasor = Path(taban) / UYGULAMA_ADI
    klasor.mkdir(parents=True, exist_ok=True)
    return klasor


def kaynak_klasoru() -> Path:
    """Paketle birlikte gelen dosyaların (static/) kökü.

    PyInstaller tek dosya modunda paketi geçici bir klasöre açar ve yolunu
    sys._MEIPASS'te bildirir; `__file__` oraya güvenilir biçimde işaret
    etmiyor.
    """
    if paketlenmis():
        return Path(getattr(sys, "_MEIPASS", str(KOK)))
    return KOK


def ayar_dosyasi() -> Path:
    return veri_klasoru() / "ayarlar.json"


def _metni_bool(ham, varsayilan: bool) -> bool:
    if isinstance(ham, bool):
        return ham
    if ham is None or str(ham).strip() == "":
        return varsayilan
    return str(ham).strip().lower() in {"1", "true", "evet", "yes", "on"}


def _env_oku() -> dict:
    """.env dosyasını kodlamasından bağımsız okur.

    Windows'ta Not Defteri dosyayı "ANSI" (cp1254) kaydedebiliyor; düz okuma
    UnicodeDecodeError ile patlıyordu.
    """
    yol = KOK / ".env"
    if not yol.exists():
        return {}
    ham = yol.read_bytes()
    for kodlama in ("utf-8-sig", "cp1254", "latin-1"):
        try:
            metin = ham.decode(kodlama)
            break
        except UnicodeDecodeError:
            continue
    else:  # pragma: no cover - latin-1 her baytı çözer
        metin = ham.decode("utf-8", errors="replace")
    okunan = dotenv_values(stream=io.StringIO(metin))
    return {ad: deger for ad, deger in okunan.items() if deger is not None}


def _envden_devral() -> dict:
    env = _env_oku()
    devralinan = {}
    for ad, (env_adi, varsayilan) in ALANLAR.items():
        ham = env.get(env_adi, os.getenv(env_adi))
        if isinstance(varsayilan, bool):
            devralinan[ad] = _metni_bool(ham, varsayilan)
        elif isinstance(varsayilan, int):
            try:
                devralinan[ad] = int(str(ham).strip()) if ham else varsayilan
            except ValueError:
                devralinan[ad] = varsayilan
        else:
            devralinan[ad] = (ham or "").strip()
    return devralinan


def yeniden_yukle() -> dict:
    """Ayarları diskten okur ve modül değişkenlerini tazeler."""
    global _ayarlar

    yol = ayar_dosyasi()
    yedek = yol.with_name("ayarlar.yedek.json")

    kayitli = None
    for aday in (yol, yedek):
        if not aday.exists():
            continue
        try:
            okunan = json.loads(aday.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        # Boş/anlamsız bir dosya yüzünden her şeyi sıfırlamıyoruz; yedeğe
        # düşüyoruz. (Ayarların "kendiliğinden gitmesi" böyle görünüyordu.)
        if isinstance(okunan, dict) and okunan.get("shopify_magaza"):
            kayitli = okunan
            break
        if kayitli is None and isinstance(okunan, dict):
            kayitli = okunan

    if kayitli is not None:
        temel = {ad: varsayilan for ad, (_, varsayilan) in ALANLAR.items()}
        temel.update({ad: d for ad, d in kayitli.items() if ad in ALANLAR})
        _ayarlar = temel
    else:
        # İlk açılış: varsa .env'den devral, yoksa varsayılanlarla başla.
        _ayarlar = _envden_devral()

    _globalleri_tazele()
    return dict(_ayarlar)


def kaydet(yeni: dict) -> dict:
    """Ayarları diske yazar. Boş bırakılan gizli alanlar korunur."""
    guncel = dict(_ayarlar)
    for ad, (_, varsayilan) in ALANLAR.items():
        if ad not in yeni:
            continue
        deger = yeni[ad]
        if ad in KORUNAN_ALANLAR and (deger is None or str(deger).strip() == ""):
            # Boş gelen kimlik alanı "değiştirme" demek (bkz. KORUNAN_ALANLAR).
            continue
        if isinstance(varsayilan, bool):
            guncel[ad] = _metni_bool(deger, varsayilan)
        elif isinstance(varsayilan, int):
            try:
                guncel[ad] = int(str(deger).strip())
            except (ValueError, AttributeError):
                guncel[ad] = varsayilan
        else:
            guncel[ad] = str(deger).strip()

    yol = ayar_dosyasi()
    yol.parent.mkdir(parents=True, exist_ok=True)
    # Önce geçici dosyaya yazıp yerine koyuyoruz: yazma sırasında uygulama
    # kapanırsa yarım kalmış bir ayar dosyası kalmasın (o dosya okunamayınca
    # bütün ayarlar sıfırlanmış görünüyor).
    metin = json.dumps(guncel, ensure_ascii=False, indent=2)
    gecici = yol.with_suffix(".json.yeni")
    gecici.write_text(metin, encoding="utf-8")
    os.replace(gecici, yol)

    # Dolu bir ayar takımını ayrıca yedekliyoruz; asıl dosya bir şekilde
    # bozulur ya da boşalırsa açılışta buradan geri alınıyor.
    if guncel.get("shopify_magaza"):
        try:
            yol.with_name("ayarlar.yedek.json").write_text(metin, encoding="utf-8")
        except OSError:
            pass

    globals()["_ayarlar"] = guncel
    _globalleri_tazele()
    return dict(guncel)


def ayarlar() -> dict:
    return dict(_ayarlar)


def _globalleri_tazele() -> None:
    g = globals()
    a = _ayarlar
    g["SHOPIFY_STORE"] = a.get("shopify_magaza", "")
    g["SHOPIFY_ISTEMCI_KIMLIGI"] = a.get("shopify_istemci_kimligi", "")
    g["SHOPIFY_GIZLI_ANAHTAR"] = a.get("shopify_gizli_anahtar", "")
    g["SHOPIFY_TOKEN"] = a.get("shopify_token", "")
    g["GIB_KULLANICI_KODU"] = a.get("gib_kullanici_kodu", "")
    g["GIB_SIFRE"] = a.get("gib_sifre", "")
    g["GIB_TEST_MODU"] = bool(a.get("gib_test_modu", True))
    g["KDV_ORANI"] = int(a.get("kdv_orani", 20))
    g["KARGOYU_DAGIT"] = bool(a.get("kargoyu_dagit", True))
    g["FATURA_NOTU"] = a.get("fatura_notu", "")
    g["BASLANGIC_TARIHI"] = a.get("baslangic_tarihi", "")
    # Test kayıtları ayrı dosyada; test denemeleri gerçek siparişleri
    # "faturalandı" saymasın diye.
    g["VERITABANI"] = veri_klasoru() / (
        "fatura-test.db" if g["GIB_TEST_MODU"] else "fatura.db"
    )
    g["FATURA_KLASORU"] = veri_klasoru() / "faturalar"


def eksik_ayarlar() -> list[str]:
    """Araç çalışmadan önce doldurulması gereken ayarlar.

    GİB alanları burada aranmıyor: fatura artık Hepsiburada e-Faturam'a XML
    olarak yükleniyor, GİB'e bağlanmıyoruz. Bunlar hâlâ istenseydi temiz bir
    kurulumda ekranda olmayan alanlar için uyarı çıkardı.
    """
    eksik = []
    if not SHOPIFY_STORE:
        eksik.append("Shopify mağaza adresi")
    if not SHOPIFY_TOKEN and not (SHOPIFY_ISTEMCI_KIMLIGI and SHOPIFY_GIZLI_ANAHTAR):
        eksik.append("Shopify istemci kimliği ve gizli anahtarı")
    a = _ayarlar
    if not a.get("satici_tckn"):
        eksik.append("TCKN / VKN")
    if not a.get("satici_vergi_dairesi"):
        eksik.append("vergi dairesi")
    if not (a.get("satici_ad") or a.get("satici_unvan")):
        eksik.append("ad soyad ya da ünvan")
    return eksik


yeniden_yukle()
