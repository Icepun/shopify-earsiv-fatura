#!/usr/bin/env python3
"""Bağlantıları sınar: .env doğru mu, Shopify ve GİB erişilebiliyor mu.

    ./.venv/bin/python kontrol.py
"""

import sys

# Windows konsolu varsayılan olarak cp1254 kullanır; Türkçe karakterler ve
# işaretler UnicodeEncodeError'a yol açmasın diye çıktıyı UTF-8'e alıyoruz.
# stderr de dahil: beklenmeyen bir hatada traceback'teki Türkçe mesaj
# okunamaz hale geliyordu.
for _akis in (sys.stdout, sys.stderr):
    if hasattr(_akis, "reconfigure"):
        try:
            _akis.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

from fatura import config
from fatura.donustur import siparisi_faturaya_cevir
from fatura.gib import GibHatasi, GibPortal
from fatura.payload import gib_payloadu
from fatura.shopify_api import Shopify, ShopifyHatasi

IYI, KOTU, BILGI = "✅", "❌", "•"


def baslik(metin: str) -> None:
    # ANSI kaçışı kullanılmıyor: eski cmd.exe bunları ham metin olarak basar.
    print(f"\n{metin}")
    print("-" * len(metin))


def main() -> int:
    hata_sayisi = 0

    baslik("1) Ayarlar")
    eksik = config.eksik_ayarlar()
    if eksik:
        print(f"  {KOTU} .env dosyasında eksik: {', '.join(eksik)}")
        return 1
    print(f"  {IYI} .env okundu")
    ortam = "TEST (resmî fatura kesilmez)" if config.GIB_TEST_MODU else "GERÇEK"
    print(f"  {BILGI} GİB ortamı : {ortam}")
    print(f"  {BILGI} Veritabanı : {config.VERITABANI.name}")
    print(f"  {BILGI} KDV        : %{config.KDV_ORANI}")
    print(f"  {BILGI} Kargo      : "
          f"{'ürün satırlarına dağıtılıyor' if config.KARGOYU_DAGIT else 'ayrı satır'}")

    baslik("2) Shopify bağlantısı")
    siparisler = []
    try:
        shopify = Shopify()
        siparisler = shopify.faturalanmamis_siparisler(limit=5)
        print(f"  {IYI} {shopify.magaza} bağlantısı çalışıyor")
        print(f"  {BILGI} Kimlik yöntemi: {shopify.kimlik_yontemi}")
        print(f"  {BILGI} Faturalanmamış sipariş (ilk 5): {len(siparisler)}")
        for siparis in siparisler:
            print(f"      {siparis['name']}  {siparis['createdAt'][:10]}  "
                  f"{siparis['currentTotalPriceSet']['shopMoney']['amount']} TL")
    except ShopifyHatasi as hata:
        print(f"  {KOTU} {hata}")
        hata_sayisi += 1

    baslik("3) Fatura hesabı")
    if siparisler:
        fatura = siparisi_faturaya_cevir(siparisler[0])
        payload = gib_payloadu(fatura)
        print(f"  {IYI} {fatura.siparis_no} faturaya çevrildi")
        print(f"      Alıcı  : {fatura.alici.ad} {fatura.alici.soyad} "
              f"({fatura.alici.ilce or '—'} / {fatura.alici.sehir or '—'})")
        print(f"      Matrah : {fatura.matrah} + KDV {fatura.kdv} "
              f"= {fatura.toplam} TL")
        print(f"      Tahsilat {fatura.tahsil_edilen} TL, sapma {fatura.sapma}")
        print(f"      GİB payload alan sayısı: {len(payload)}")
        for uyari in fatura.uyarilar:
            print(f"      ⚠ {uyari}")
    else:
        print(f"  {BILGI} Çevrilecek sipariş yok, atlandı")

    baslik("4) GİB e-Arşiv Portal bağlantısı")
    portal = GibPortal(
        config.GIB_KULLANICI_KODU, config.GIB_SIFRE, config.GIB_TEST_MODU
    )
    try:
        portal.giris()
        print(f"  {IYI} Giriş başarılı ({portal.url})")
        bilgi = portal.kullanici_bilgileri()
        unvan = bilgi.get("unvan") or f"{bilgi.get('adi','')} {bilgi.get('soyadi','')}"
        print(f"  {BILGI} Mükellef : {unvan.strip() or '—'}")
        print(f"  {BILGI} VKN/TCKN : {bilgi.get('vknTckn', '—')}")
        if bilgi.get("telefon"):
            print(f"  {BILGI} SMS için kayıtlı telefon: {bilgi['telefon']}")
        else:
            print("      ⚠ Portalda kayıtlı telefon yok — SMS imzalama çalışmaz.")
    except GibHatasi as hata:
        print(f"  {KOTU} {hata}")
        hata_sayisi += 1
    finally:
        portal.kapat()

    baslik("Sonuç")
    if hata_sayisi:
        print(f"  {KOTU} {hata_sayisi} sorun var, yukarıya bak.\n")
        return 1
    baslatici = "baslat.bat" if sys.platform == "win32" else "./baslat.sh"
    print(f"  {IYI} Her şey hazır — {baslatici} ile paneli açabilirsin.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
