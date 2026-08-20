"""GitHub Releases üzerinden otomatik güncelleme.

Akış:
    1. `guncelleme_kontrol()` en son sürümü sorar (public depo, token yok).
    2. Yeni sürüm varsa kullanıcı onaylar, `indirmeyi_baslat()` arka planda
       .exe'yi indirir; ilerleme `durum()` ile okunur (belirli yüzde).
    3. `kuruluma_gec()` çalışan .exe'yi yenisiyle değiştirip uygulamayı
       yeniden başlatır.

Windows çalışan bir .exe'nin **üzerine yazmaya** izin vermez ama **adını
değiştirmeye** izin verir. Bu yüzden yardımcı betik yazmak yerine:
    Uygulama.exe -> Uygulama.eski.exe   (yeniden adlandır)
    Uygulama.yeni.exe -> Uygulama.exe   (yeniden adlandır)
Sonraki açılışta `eski_surumu_temizle()` artığı siler.
"""

from __future__ import annotations

import os
import re
import sys
import time
import threading
from pathlib import Path

import httpx

from . import config

SURUM_UCU = f"https://api.github.com/repos/{config.GITHUB_DEPO}/releases/latest"

_durum: dict = {
    "asama": "bos",       # bos | indiriliyor | hazir | hata
    "yuzde": 0,
    "inen": 0,
    "boyut": 0,
    "hata": "",
    "dosya": "",
}
_kilit = threading.Lock()


# ─── sürüm karşılaştırma ─────────────────────────────────────────────


def surum_parcala(ham: str) -> tuple:
    """'v1.2.3' -> (1, 2, 3). Karşılaştırılabilir bir demet döner."""
    sayilar = re.findall(r"\d+", ham or "")
    return tuple(int(s) for s in sayilar[:3]) or (0,)


def daha_yeni_mi(uzak: str, yerel: str) -> bool:
    u, y = surum_parcala(uzak), surum_parcala(yerel)
    # Farklı uzunlukta demetler karşılaştırılabilsin diye eşitliyoruz.
    boy = max(len(u), len(y))
    u += (0,) * (boy - len(u))
    y += (0,) * (boy - len(y))
    return u > y


# ─── kontrol ─────────────────────────────────────────────────────────


def guncelleme_kontrol() -> dict:
    """En son sürümü sorar. Ağ hatasında sessizce 'yok' döner."""
    temel = {
        "var": False,
        "yerel_surum": config.SURUM,
        "paketlenmis": config.paketlenmis(),
    }
    try:
        cevap = httpx.get(
            SURUM_UCU,
            timeout=12,
            headers={"Accept": "application/vnd.github+json"},
            follow_redirects=True,
        )
        if cevap.status_code != 200:
            return {**temel, "mesaj": f"Sürüm bilgisi alınamadı (HTTP {cevap.status_code})."}
        veri = cevap.json()
    except (httpx.HTTPError, ValueError) as hata:
        return {**temel, "mesaj": f"Sürüm sunucusuna ulaşılamadı: {hata}"}

    etiket = veri.get("tag_name") or veri.get("name") or ""
    if not daha_yeni_mi(etiket, config.SURUM):
        return {**temel, "mesaj": "En güncel sürümü kullanıyorsunuz."}

    exe = None
    for varlik in veri.get("assets") or []:
        if (varlik.get("name") or "").lower().endswith(".exe"):
            exe = varlik
            break

    return {
        **temel,
        "var": True,
        "surum": etiket.lstrip("vV"),
        "notlar": (veri.get("body") or "").strip()[:2000],
        "indirme_url": (exe or {}).get("browser_download_url", ""),
        "boyut": (exe or {}).get("size", 0),
        "sayfa": veri.get("html_url", ""),
        "kurulabilir": bool(exe) and config.paketlenmis(),
    }


# ─── indirme ─────────────────────────────────────────────────────────


def durum() -> dict:
    with _kilit:
        return dict(_durum)


def _durumu_yaz(**alanlar) -> None:
    with _kilit:
        _durum.update(alanlar)


def yeni_dosya_yolu() -> Path:
    return Path(sys.executable).with_suffix(".yeni.exe")


# Toplam süre sınırsız (dosya büyük) ama bağlantı ve parçalar arası bekleme
# sınırlı: timeout=None verildiğinde ağ takılınca indirme %0'da sonsuza
# kadar asılı kalıyordu ve kullanıcıya hiçbir şey söylenmiyordu.
_ZAMAN_ASIMI = httpx.Timeout(None, connect=30.0, read=60.0, write=30.0, pool=30.0)
_DENEME = 3


def _bir_kez_indir(url: str, hedef: Path) -> None:
    with httpx.stream("GET", url, timeout=_ZAMAN_ASIMI, follow_redirects=True) as cevap:
        cevap.raise_for_status()
        boyut = int(cevap.headers.get("Content-Length") or 0)
        _durumu_yaz(asama="indiriliyor", yuzde=0, inen=0, boyut=boyut, hata="")
        inen = 0
        with open(hedef, "wb") as dosya:
            for parca in cevap.iter_bytes(chunk_size=262144):
                dosya.write(parca)
                inen += len(parca)
                yuzde = int(inen * 100 / boyut) if boyut else 0
                _durumu_yaz(inen=inen, yuzde=min(yuzde, 100))
    if boyut and inen < boyut:
        raise OSError(f"Dosya eksik indi ({inen}/{boyut}).")


def _indir(url: str) -> None:
    hedef = yeni_dosya_yolu()
    son_hata = None
    for sira in range(_DENEME):
        try:
            _bir_kez_indir(url, hedef)
            _durumu_yaz(asama="hazir", yuzde=100, dosya=str(hedef))
            return
        except Exception as hata:  # ağ, disk, izin
            son_hata = hata
            _gunluge_yaz(f"indirme denemesi {sira + 1} basarisiz: {hata}")
            try:
                hedef.unlink(missing_ok=True)
            except OSError:
                pass
            if sira < _DENEME - 1:
                _durumu_yaz(asama="indiriliyor", yuzde=0, inen=0, boyut=0)
                time.sleep(2 * (sira + 1))
    _durumu_yaz(asama="hata", hata=f"İndirilemedi: {son_hata}")


def indirmeyi_baslat(url: str) -> dict:
    """İndirmeyi arka planda başlatır; ilerleme `durum()` ile okunur."""
    if not config.paketlenmis():
        return {"asama": "hata", "hata": "Güncelleme yalnızca kurulu uygulamada çalışır."}
    if _durum["asama"] == "indiriliyor":
        return durum()
    _durumu_yaz(asama="indiriliyor", yuzde=0, inen=0, boyut=0, hata="", dosya="")
    threading.Thread(target=_indir, args=(url,), daemon=True).start()
    return durum()


# ─── kurulum ─────────────────────────────────────────────────────────


def _gunluge_yaz(metin: str) -> None:
    """Güncelleme adımlarını dosyaya yazar.

    Uygulama penceresiz çalıştığı için buradaki hatalar hiçbir yere
    düşmüyordu; sorun çıkarsa bakılacak tek yer bu dosya.
    """
    try:
        yol = config.veri_klasoru() / "guncelleme.log"
        with yol.open("a", encoding="utf-8") as dosya:
            dosya.write(metin + "\n")
    except OSError:
        pass


def acilisi_gunlukle() -> None:
    """Her açılışı günlüğe yazar.

    Güncelleme sonrası yeni sürümün gerçekten ayağa kalkıp kalkmadığını
    başka türlü görmenin yolu yok; pencere açılmazsa hiçbir iz kalmıyordu.
    """
    _gunluge_yaz(f"acilis: surum {config.SURUM} pid {os.getpid()}")


def eski_surumu_temizle() -> None:
    """Bir önceki güncellemeden kalan .eski.exe dosyasını siler."""
    if not config.paketlenmis():
        return
    eski = Path(sys.executable).with_suffix(".eski.exe")
    try:
        eski.unlink(missing_ok=True)
    except OSError:
        # Hâlâ kilitliyse sorun değil, bir sonraki açılışta yine denenir.
        pass


def kuruluma_gec() -> dict:
    """İnen sürümü yerine koyar ve uygulamayı yeniden başlatır."""
    if _durum["asama"] != "hazir":
        return {"tamam": False, "hata": "İndirme tamamlanmadı."}

    calisan = Path(sys.executable)
    yeni = yeni_dosya_yolu()
    eski = calisan.with_suffix(".eski.exe")
    if not yeni.exists():
        return {"tamam": False, "hata": "İndirilen dosya bulunamadı."}

    _gunluge_yaz(f"--- kurulum: {calisan.name}")
    try:
        eski.unlink(missing_ok=True)
        # Windows çalışan .exe'nin adını değiştirmeye izin verir.
        calisan.rename(eski)
        try:
            yeni.rename(calisan)
        except OSError:
            eski.rename(calisan)  # geri al
            raise
    except OSError as hata:
        _gunluge_yaz(f"dosya degistirilemedi: {hata}")
        return {"tamam": False, "hata": f"Dosya değiştirilemedi: {hata}"}
    _gunluge_yaz("dosya degistirildi")

    # Uygulamayı kendimiz yeniden başlatmıyoruz.
    #
    # Denenenler ve sonuçları (hepsi Windows 11 + PyInstaller onefile):
    #   - os.startfile: yeni örnek açılıyor ama eski sürüm hâlâ ayakta
    #     olduğu için PyInstaller'ın "Error" kutusuyla ölüyor.
    #   - subprocess.Popen (DETACHED_PROCESS / cmd start / gizli powershell):
    #     yardımcı süreç biz kapanınca birlikte ölüyor.
    #   - Bekleyip açan .cmd yardımcısı: .cmd sonuna kadar çalışıyor
    #     (kendini siliyor) ama başlattığı uygulama ayağa kalkmıyor.
    #
    # Güvenilir olan yol: dosyayı değiştirip kullanıcıya söylemek. Uygulama
    # bir sonraki açılışta yeni sürümle gelir. Bir çift tıklama, sıfır risk.
    _gunluge_yaz("kurulum tamam, yeniden baslatma kullaniciya birakildi")
    return {"tamam": True, "yeniden_baslat_gerekli": True}
