#!/usr/bin/env python3
"""Shopify siparişlerinden Hepsiburada e-Faturam için toplu XML üretir.

    python xml_uret.py 1077 1075 1073          # sipariş numaralarıyla
    python xml_uret.py --tarih 2026-08-01 2026-08-26
    python xml_uret.py --etiketle 1077 1075    # ONAYDAN SONRA işaretle

Çıktı `faturalar/<tarih-saat>/` altına düşer: her fatura için bir .xml,
hepsini içeren bir .zip ve okunabilir bir rapor. Portalda
Fatura > Toplu Fatura Yükle > XML ekranına .zip'i bırakman yeterli.

Üretim Shopify'a hiçbir şey yazmaz. Sen portalda onayladıktan sonra
`--etiketle` ile siparişleri "faturalandi" olarak işaretliyoruz; ikinci kez
fatura kesilmesini bu engelliyor.
"""

from __future__ import annotations

import sys
import uuid
import zipfile
from datetime import datetime
from pathlib import Path

for _akis in (sys.stdout, sys.stderr):
    if hasattr(_akis, "reconfigure"):
        try:
            _akis.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

from fatura import config, depo  # noqa: E402
from fatura.donustur import siparisi_faturaya_cevir  # noqa: E402
from fatura.shopify_api import Shopify, ShopifyHatasi  # noqa: E402
from fatura.ubl import Satici, dosya_adi, ubl_fatura  # noqa: E402

IYI, KOTU, BILGI, UYARI = "✅", "❌", "•", "⚠"


def _satici() -> Satici:
    a = config.ayarlar()
    return Satici(
        tckn=a.get("satici_tckn", ""),
        ad=a.get("satici_ad", ""),
        soyad=a.get("satici_soyad", ""),
        unvan=a.get("satici_unvan", ""),
        vergi_dairesi=a.get("satici_vergi_dairesi", ""),
        mahalle=a.get("satici_mahalle", ""),
        bina_no=a.get("satici_bina_no", ""),
        kapi_no=a.get("satici_kapi_no", ""),
        ilce=a.get("satici_ilce", ""),
        il=a.get("satici_il", ""),
        posta_kodu=a.get("satici_posta_kodu", ""),
        telefon=a.get("satici_telefon", ""),
        eposta=a.get("satici_eposta", ""),
    )


def _siparisleri_getir(numaralar: list[str], baslangic: str, bitis: str) -> list[dict]:
    istemci = Shopify()
    if numaralar:
        # name:1077 biçimi tek tek sorgulanıyor; Shopify OR desteği sınırlı.
        bulunan, eksik = [], []
        for no in numaralar:
            temiz = no.lstrip("#")
            sonuc = istemci.siparis_ara(temiz)
            if sonuc:
                bulunan.append(sonuc)
            else:
                eksik.append(no)
        if eksik:
            print(f"  {UYARI} Bulunamayan sipariş: {', '.join(eksik)}")
        return bulunan
    return istemci.faturalanmamis_siparisler(
        limit=200, baslangic=baslangic, bitis=bitis
    )


def uret(numaralar: list[str], baslangic: str = "", bitis: str = "") -> int:
    eksik_ayar = [a for a in ("satici_tckn", "satici_ad", "satici_vergi_dairesi")
                  if not config.ayarlar().get(a)]
    if eksik_ayar:
        print(f"{KOTU} Satıcı bilgileri eksik: {', '.join(eksik_ayar)}")
        return 1

    try:
        siparisler = _siparisleri_getir(numaralar, baslangic, bitis)
    except ShopifyHatasi as hata:
        print(f"{KOTU} {hata}")
        return 1

    if not siparisler:
        print(f"{BILGI} Faturalanacak sipariş bulunamadı.")
        return 0

    depo.hazirla()
    islenmis = depo.islenmis_idler()
    satici = _satici()
    seri = config.ayarlar().get("fatura_seri", "MGL")
    sira = int(config.ayarlar().get("fatura_sira", 0))
    yil = datetime.now().year

    klasor = config.veri_klasoru() / "faturalar" / datetime.now().strftime("%Y-%m-%d_%H%M")
    klasor.mkdir(parents=True, exist_ok=True)

    uretilen, atlanan, uyarilar, toplam_tutar = [], [], [], 0
    for siparis in siparisler:
        fatura = siparisi_faturaya_cevir(siparis)
        if siparis["id"] in islenmis:
            atlanan.append((fatura.siparis_no, "daha önce faturalandı"))
            continue

        sira += 1
        belge_no = f"{seri}{yil}{sira:09d}"
        ettn = str(uuid.uuid4())
        xml = ubl_fatura(fatura, satici, belge_no=belge_no, ettn=ettn)
        ad = dosya_adi(satici.tckn, belge_no, ettn)
        (klasor / ad).write_text(xml, encoding="utf-8")

        uretilen.append((fatura, belge_no, ettn, ad))
        toplam_tutar += float(fatura.toplam)

        # Üretim anında kaydediyoruz. Portal bir UUID'yi bir kez kabul ediyor;
        # yükleme başarılı olup etiketleme unutulursa iz kalmazsa aynı sipariş
        # için ikinci bir fatura üretilir. Durum 'taslak', onaydan sonra
        # --etiketle ile 'imzalandi'ya çekiliyor.
        depo.kaydet(
            siparis_id=siparis["id"], siparis_no=fatura.siparis_no,
            durum="taslak", ettn=ettn, tutar=f"{fatura.toplam:.2f}",
        )

        # Portala gitmeden önce göze çarpması gerekenler
        if not fatura.alici.ilce:
            uyarilar.append(f"{fatura.siparis_no}: ilçe boş")
        if not fatura.alici.adres:
            uyarilar.append(f"{fatura.siparis_no}: adres boş")
        if fatura.sapma != 0:
            uyarilar.append(
                f"{fatura.siparis_no}: sapma {fatura.sapma:+.2f} TL "
                f"(fatura {fatura.toplam} / tahsilat {fatura.tahsil_edilen})"
            )
        for u in fatura.uyarilar:
            if "Yuvarlama" not in u:
                uyarilar.append(f"{fatura.siparis_no}: {u}")

    if not uretilen:
        print(f"{BILGI} Yeni fatura üretilmedi.")
        for no, sebep in atlanan:
            print(f"    {no}: {sebep}")
        return 0

    zip_yolu = klasor / f"faturalar_{len(uretilen)}_adet.zip"
    with zipfile.ZipFile(zip_yolu, "w", zipfile.ZIP_DEFLATED) as z:
        for _, _, _, ad in uretilen:
            z.write(klasor / ad, arcname=ad)

    satirlar = [
        f"Üretim: {datetime.now():%d.%m.%Y %H:%M}",
        f"Seri   : {seri}{yil} — {uretilen[0][1]} ... {uretilen[-1][1]}",
        "",
        f"{'Sipariş':10}{'Belge No':20}{'Matrah':>10}{'KDV':>9}{'Toplam':>10}  Alıcı",
    ]
    for fatura, belge_no, _, _ in uretilen:
        alici = fatura.alici.unvan or f"{fatura.alici.ad} {fatura.alici.soyad}".strip()
        satirlar.append(
            f"{fatura.siparis_no:10}{belge_no:20}{fatura.matrah:>10}"
            f"{fatura.kdv:>9}{fatura.toplam:>10}  {alici}"
        )
    satirlar += [
        "", f"TOPLAM: {len(uretilen)} fatura, {toplam_tutar:.2f} TL",
        "",
        "Not: Portal her UUID'yi bir kez kabul eder. Bir dosya yüklendikten",
        "sonra (portaldan silinse bile) aynısı tekrar yüklenemez; yeniden",
        "denemek gerekirse bu betiği yeniden çalıştır, yeni UUID üretilir.",
    ]
    if uyarilar:
        satirlar += ["", "Gözden geçir:"] + [f"  - {u}" for u in uyarilar]
    if atlanan:
        satirlar += ["", "Atlananlar:"] + [f"  - {n}: {s}" for n, s in atlanan]
    rapor = "\n".join(satirlar)
    (klasor / "rapor.txt").write_text(rapor, encoding="utf-8")

    print(rapor)
    print()
    print(f"{IYI} {len(uretilen)} XML üretildi")
    print(f"    Klasör : {klasor}")
    print(f"    Yükle  : {zip_yolu.name}")
    print()
    print(f"{BILGI} Sıra numarası {sira} olarak kaydedildi; sonraki üretim buradan devam eder.")
    print(f"{BILGI} Portalda onayladıktan sonra:")
    print(f"    python xml_uret.py --etiketle "
          + " ".join(f.siparis_no.lstrip('#') for f, _, _, _ in uretilen))
    config.kaydet({"fatura_sira": sira})
    return 0


def etiketle(numaralar: list[str]) -> int:
    """Portalda onaylanan siparişleri Shopify'da işaretler."""
    try:
        istemci = Shopify()
    except ShopifyHatasi as hata:
        print(f"{KOTU} {hata}")
        return 1

    depo.hazirla()
    basarili = 0
    for no in numaralar:
        temiz = no.lstrip("#")
        siparis = istemci.siparis_ara(temiz)
        if not siparis:
            print(f"  {KOTU} #{temiz} bulunamadı")
            continue
        fatura = siparisi_faturaya_cevir(siparis)
        try:
            istemci.faturalandi_isaretle(siparis["id"])
            depo.kaydet(
                siparis_id=siparis["id"], siparis_no=fatura.siparis_no,
                durum="imzalandi", tutar=f"{fatura.toplam:.2f}",
            )
            print(f"  {IYI} {fatura.siparis_no} işaretlendi")
            basarili += 1
        except ShopifyHatasi as hata:
            print(f"  {KOTU} {fatura.siparis_no}: {hata}")
    print()
    print(f"{basarili}/{len(numaralar)} sipariş 'faturalandi' olarak işaretlendi.")
    return 0


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 1
    if argv[0] == "--etiketle":
        return etiketle(argv[1:])
    if argv[0] == "--tarih":
        if len(argv) < 3:
            print(f"{KOTU} Kullanım: --tarih 2026-08-01 2026-08-26")
            return 1
        return uret([], argv[1], argv[2])
    return uret(argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
