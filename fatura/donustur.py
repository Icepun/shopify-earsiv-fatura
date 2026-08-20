"""Shopify siparişini GİB e-Arşiv fatura verisine çevirir.

Para hesapları float ile yapılmaz; her tutar Decimal üzerinden kuruşa
yuvarlanır. Amaç faturanın kendi içinde kusursuz tutarlı olması:
    malHizmetTutari = birimFiyat x miktar
    kdvTutari       = malHizmetTutari x kdvOrani
    odenecekTutar   = toplam matrah + toplam kdv
Shopify'ın tahsil ettiği tutarla arada kuruş farkı kalırsa gizlenmez,
`sapma` alanında panele taşınır.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from . import config

SIFIR = Decimal("0.00")

# Posta kodunun ilk iki hanesi il plaka kodudur; şehir alanını buradan
# güvenilir biçimde türetiyoruz.
PLAKA_IL = {
    "01": "Adana", "02": "Adıyaman", "03": "Afyonkarahisar", "04": "Ağrı",
    "05": "Amasya", "06": "Ankara", "07": "Antalya", "08": "Artvin",
    "09": "Aydın", "10": "Balıkesir", "11": "Bilecik", "12": "Bingöl",
    "13": "Bitlis", "14": "Bolu", "15": "Burdur", "16": "Bursa",
    "17": "Çanakkale", "18": "Çankırı", "19": "Çorum", "20": "Denizli",
    "21": "Diyarbakır", "22": "Edirne", "23": "Elazığ", "24": "Erzincan",
    "25": "Erzurum", "26": "Eskişehir", "27": "Gaziantep", "28": "Giresun",
    "29": "Gümüşhane", "30": "Hakkari", "31": "Hatay", "32": "Isparta",
    "33": "Mersin", "34": "İstanbul", "35": "İzmir", "36": "Kars",
    "37": "Kastamonu", "38": "Kayseri", "39": "Kırklareli", "40": "Kırşehir",
    "41": "Kocaeli", "42": "Konya", "43": "Kütahya", "44": "Malatya",
    "45": "Manisa", "46": "Kahramanmaraş", "47": "Mardin", "48": "Muğla",
    "49": "Muş", "50": "Nevşehir", "51": "Niğde", "52": "Ordu",
    "53": "Rize", "54": "Sakarya", "55": "Samsun", "56": "Siirt",
    "57": "Sinop", "58": "Sivas", "59": "Tekirdağ", "60": "Tokat",
    "61": "Trabzon", "62": "Tunceli", "63": "Şanlıurfa", "64": "Uşak",
    "65": "Van", "66": "Yozgat", "67": "Zonguldak", "68": "Aksaray",
    "69": "Bayburt", "70": "Karaman", "71": "Kırıkkale", "72": "Batman",
    "73": "Şırnak", "74": "Bartın", "75": "Ardahan", "76": "Iğdır",
    "77": "Yalova", "78": "Karabük", "79": "Kilis", "80": "Osmaniye",
    "81": "Düzce",
}

ILLER = {ad.casefold(): ad for ad in PLAKA_IL.values()}


def kurusa(deger: Decimal) -> Decimal:
    """Kuruş hassasiyetine yuvarlar (yarım yukarı)."""
    return deger.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def para(ham) -> Decimal:
    """Shopify'dan gelen tutar metnini Decimal'e çevirir."""
    if ham is None or ham == "":
        return SIFIR
    if isinstance(ham, dict):
        ham = ham.get("shopMoney", {}).get("amount", "0")
    return Decimal(str(ham))


def telefon_duzelt(ham: str | None) -> str:
    """Karışık telefon formatlarını 10 haneye indirger (5xxxxxxxxx)."""
    if not ham:
        return ""
    rakam = re.sub(r"\D", "", ham)
    if rakam.startswith("90") and len(rakam) == 12:
        rakam = rakam[2:]
    if rakam.startswith("0") and len(rakam) == 11:
        rakam = rakam[1:]
    return rakam if len(rakam) == 10 else ""


@dataclass
class Kalem:
    ad: str
    miktar: Decimal
    birim_fiyat: Decimal      # KDV hariç birim fiyat
    matrah: Decimal           # birim_fiyat x miktar
    kdv: Decimal
    kdv_orani: int

    @property
    def dahil(self) -> Decimal:
        return self.matrah + self.kdv

    def gib_sozlugu(self) -> dict:
        return {
            "malHizmet": self.ad,
            "miktar": float(self.miktar),
            "birim": "C62",  # UN/ECE birim kodu: adet
            "birimFiyat": f"{self.birim_fiyat:.2f}",
            "fiyat": f"{self.matrah:.2f}",
            "iskontoOrani": 0,
            "iskontoTutari": "0.00",
            "iskontoNedeni": "",
            "malHizmetTutari": f"{self.matrah:.2f}",
            "kdvOrani": str(self.kdv_orani),
            "vergiOrani": 0,
            "kdvTutari": f"{self.kdv:.2f}",
            "vergininKdvTutari": "0.00",
            "ozelMatrahTutari": "0.00",
            "hesaplananotvtevkifatakatkisi": "0.00",
        }


@dataclass
class Alici:
    ad: str = ""
    soyad: str = ""
    unvan: str = ""
    vkn_tckn: str = config.NIHAI_TUKETICI_TCKN
    vergi_dairesi: str = ""
    adres: str = ""
    ilce: str = ""
    sehir: str = ""
    posta_kodu: str = ""
    telefon: str = ""
    eposta: str = ""

    @property
    def kurumsal(self) -> bool:
        return bool(self.unvan)


@dataclass
class Fatura:
    siparis_id: str
    siparis_no: str
    tarih: str                # gg/aa/yyyy
    saat: str                 # ss:dd:ss
    alici: Alici
    kalemler: list[Kalem]
    tahsil_edilen: Decimal    # Shopify'ın gerçekte tahsil ettiği tutar
    uyarilar: list[str] = field(default_factory=list)

    @property
    def matrah(self) -> Decimal:
        return sum((k.matrah for k in self.kalemler), SIFIR)

    @property
    def kdv(self) -> Decimal:
        return sum((k.kdv for k in self.kalemler), SIFIR)

    @property
    def toplam(self) -> Decimal:
        return self.matrah + self.kdv

    @property
    def sapma(self) -> Decimal:
        """Fatura toplamı ile tahsil edilen tutar arasındaki kuruş farkı."""
        return self.toplam - self.tahsil_edilen


def _alici_cikar(siparis: dict) -> tuple[Alici, list[str]]:
    """Fatura adresi varsa onu, yoksa teslimat adresini kullanır."""
    uyarilar: list[str] = []
    adres = siparis.get("billingAddress") or siparis.get("shippingAddress") or {}
    musteri = siparis.get("customer") or {}

    ad = (adres.get("firstName") or "").strip()
    soyad = (adres.get("lastName") or "").strip()
    if not ad and not soyad:
        ham = (musteri.get("displayName") or "").strip()
        parcalar = ham.split()
        ad = " ".join(parcalar[:-1]) if len(parcalar) > 1 else ham
        soyad = parcalar[-1] if len(parcalar) > 1 else ""
    if not ad and not soyad:
        uyarilar.append("Alıcı adı boş — elle doldurulmalı.")

    sehir_ham = (adres.get("city") or "").strip()
    il_ham = (adres.get("province") or "").strip()
    posta = re.sub(r"\D", "", adres.get("zip") or "")

    # Şehir alanını sırayla posta kodundan, province'tan ve city'den türet.
    sehir = ""
    if len(posta) >= 2:
        sehir = PLAKA_IL.get(posta[:2], "")
    if not sehir and il_ham:
        sehir = ILLER.get(il_ham.casefold(), il_ham)
    if not sehir and sehir_ham:
        sehir = ILLER.get(sehir_ham.casefold(), "")

    # city il değilse ilçedir (ör. "Milas" -> Muğla ili, Milas ilçesi).
    ilce = ""
    if sehir_ham and sehir_ham.casefold() != sehir.casefold():
        ilce = sehir_ham
    elif il_ham and il_ham.casefold() != sehir.casefold():
        ilce = il_ham

    if not sehir:
        sehir = sehir_ham
        if not sehir:
            uyarilar.append("Şehir belirlenemedi — elle doldurulmalı.")

    telefon = telefon_duzelt(adres.get("phone") or musteri.get("phone"))
    unvan = (adres.get("company") or "").strip()
    if unvan:
        uyarilar.append(
            f"Kurumsal sipariş görünüyor ({unvan}) — VKN ve vergi dairesi girilmeli."
        )

    alici = Alici(
        ad=ad,
        soyad=soyad,
        unvan=unvan,
        adres=(adres.get("address1") or "").strip(),
        ilce=ilce,
        sehir=sehir,
        posta_kodu=posta,
        telefon=telefon,
        eposta=(musteri.get("email") or siparis.get("email") or "").strip(),
    )
    return alici, uyarilar


def _kalemleri_cikar(siparis: dict, kdv_orani: int) -> tuple[list[Kalem], list[str]]:
    """Satır kalemlerini, kargoyu dağıtarak KDV hariç/dahil olarak ayrıştırır."""
    uyarilar: list[str] = []
    oran = Decimal(kdv_orani) / Decimal(100)
    bolen = Decimal(1) + oran

    # 1) İade sonrası kalan miktarlar üzerinden KDV dahil satır tutarları.
    ham: list[tuple[str, Decimal, Decimal]] = []
    for satir in siparis.get("lineItems", {}).get("nodes", []):
        miktar = Decimal(str(satir.get("currentQuantity", satir.get("quantity", 0))))
        if miktar <= 0:
            continue
        toplam = para(satir.get("discountedTotalSet"))
        if satir.get("currentQuantity") not in (None, satir.get("quantity")):
            # Kısmi iade: kalan miktara orantıla.
            asil = Decimal(str(satir.get("quantity", 1)))
            if asil > 0:
                toplam = kurusa(toplam * miktar / asil)
        ad = (satir.get("title") or "Ürün").strip()[:200]
        ham.append((ad, miktar, toplam))

    if not ham:
        return [], ["Faturalanacak satır kalemi yok."]

    # 2) Net kargo bedelini satırlara tutar oranında dağıt.
    kargo = SIFIR
    for kargo_satiri in siparis.get("shippingLines", {}).get("nodes", []):
        kargo += para(kargo_satiri.get("discountedPriceSet"))

    if kargo > SIFIR and config.KARGOYU_DAGIT:
        urun_toplami = sum((t for _, _, t in ham), SIFIR)
        kalan = kargo
        dagitilmis = []
        for sira, (ad, miktar, toplam) in enumerate(ham):
            if sira == len(ham) - 1 or urun_toplami <= SIFIR:
                pay = kalan
            else:
                pay = kurusa(kargo * toplam / urun_toplami)
                kalan -= pay
            dagitilmis.append((ad, miktar, toplam + pay))
        ham = dagitilmis
    elif kargo > SIFIR:
        ham.append(("Kargo Bedeli", Decimal(1), kargo))

    # 3) Birim fiyat ekseninde yuvarlayarak matrah ve KDV'yi ayrıştır.
    kalemler = []
    for ad, miktar, dahil in ham:
        birim_dahil = kurusa(dahil / miktar)
        birim_matrah = kurusa(birim_dahil / bolen)
        matrah = kurusa(birim_matrah * miktar)
        kdv = kurusa(matrah * oran)
        kalemler.append(
            Kalem(
                ad=ad,
                miktar=miktar,
                birim_fiyat=birim_matrah,
                matrah=matrah,
                kdv=kdv,
                kdv_orani=kdv_orani,
            )
        )
    return kalemler, uyarilar


def siparisi_faturaya_cevir(siparis: dict, kdv_orani: int | None = None) -> Fatura:
    """Shopify sipariş sözlüğünü onaya hazır bir Fatura nesnesine çevirir."""
    kdv_orani = kdv_orani if kdv_orani is not None else config.KDV_ORANI

    alici, alici_uyari = _alici_cikar(siparis)
    kalemler, kalem_uyari = _kalemleri_cikar(siparis, kdv_orani)

    olusturma = siparis.get("createdAt", "")
    tarih, saat = "", ""
    kalip = re.match(r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})", olusturma)
    if kalip:
        yil, ay, gun, ss, dd, sn = kalip.groups()
        tarih = f"{gun}/{ay}/{yil}"
        saat = f"{ss}:{dd}:{sn}"

    fatura = Fatura(
        siparis_id=siparis.get("id", ""),
        siparis_no=siparis.get("name", ""),
        tarih=tarih,
        saat=saat,
        alici=alici,
        kalemler=kalemler,
        tahsil_edilen=para(siparis.get("currentTotalPriceSet")),
        uyarilar=alici_uyari + kalem_uyari,
    )

    if fatura.sapma != SIFIR:
        fatura.uyarilar.append(
            f"Yuvarlama farkı {fatura.sapma:+.2f} TL "
            f"(fatura {fatura.toplam:.2f} / tahsilat {fatura.tahsil_edilen:.2f})."
        )
    return fatura
