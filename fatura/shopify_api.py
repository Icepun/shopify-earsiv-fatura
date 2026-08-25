"""Shopify Admin GraphQL API istemcisi."""

from __future__ import annotations

import time
from datetime import datetime

import httpx

from . import config

SIPARIS_ALANLARI = """
  id
  name
  createdAt
  cancelledAt
  displayFinancialStatus
  displayFulfillmentStatus
  email
  tags
  currentTotalPriceSet { shopMoney { amount } }
  shippingLines(first: 5) { nodes { discountedPriceSet { shopMoney { amount } } } }
  billingAddress { firstName lastName address1 address2 city province countryCode zip phone company }
  shippingAddress { firstName lastName address1 address2 city province countryCode zip phone company }
  customer { email phone displayName }
  lineItems(first: 100) {
    nodes {
      title
      quantity
      currentQuantity
      originalTotalSet { shopMoney { amount } }
      discountedTotalSet { shopMoney { amount } }
      discountAllocations { allocatedAmountSet { shopMoney { amount } } }
    }
  }
"""

SIPARIS_SORGUSU = f"""
query Siparisler($sorgu: String!, $adet: Int!, $imlec: String) {{
  orders(first: $adet, after: $imlec, query: $sorgu, sortKey: CREATED_AT, reverse: true) {{
    nodes {{ {SIPARIS_ALANLARI} }}
    pageInfo {{ hasNextPage endCursor }}
  }}
}}
"""

ETIKET_EKLE = """
mutation EtiketEkle($id: ID!, $etiketler: [String!]!) {
  tagsAdd(id: $id, tags: $etiketler) {
    userErrors { field message }
  }
}
"""

METAFIELD_YAZ = """
mutation MetafieldYaz($girdiler: [MetafieldsSetInput!]!) {
  metafieldsSet(metafields: $girdiler) {
    userErrors { field message }
  }
}
"""


class ShopifyHatasi(RuntimeError):
    pass


def _tarih_dogrula(ham: str) -> str:
    """YYYY-AA-GG biçimini doğrular.

    Değer arama sorgusu metnine doğrudan gömüldüğü için serbest metne izin
    verilmiyor; takvimde var olmayan tarihler de burada eleniyor.
    """
    ham = (ham or "").strip()
    try:
        return datetime.strptime(ham, "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        raise ShopifyHatasi(f"Tarih YYYY-AA-GG biçiminde olmalı: {ham!r}")


class _TokenDeposu:
    """client_credentials ile alınan erişim tokenini süresince saklar.

    Token 24 saat geçerli; her istekte yeniden almak gereksiz. Panel her
    çağrıda yeni bir Shopify nesnesi kurduğu için depo modül düzeyinde
    tutuluyor, yoksa önbellek hiç işe yaramazdı.
    """

    # Süre dolmadan önce yenile: uzun süren toplu kesim ortasında token ölmesin.
    PAY = 300

    def __init__(self) -> None:
        self._token = ""
        self._biter = 0.0

    def temizle(self) -> None:
        self._token = ""
        self._biter = 0.0

    def getir(self, magaza: str, istemci_kimligi: str, gizli_anahtar: str) -> str:
        if self._token and time.time() < self._biter - self.PAY:
            return self._token

        try:
            cevap = httpx.post(
                f"https://{magaza}/admin/oauth/access_token",
                data={
                    "client_id": istemci_kimligi,
                    "client_secret": gizli_anahtar,
                    "grant_type": "client_credentials",
                },
                timeout=30,
            )
        except httpx.HTTPError as hata:
            raise ShopifyHatasi(f"Shopify token sunucusuna ulaşılamadı: {hata}")

        try:
            veri = cevap.json()
        except ValueError:
            raise ShopifyHatasi(
                f"Shopify token yanıtı okunamadı (HTTP {cevap.status_code}): "
                f"{cevap.text[:200]}"
            )

        token = veri.get("access_token")
        if not token:
            raise ShopifyHatasi(_token_hatasi(veri, cevap.status_code))

        self._token = token
        self._biter = time.time() + float(veri.get("expires_in", 86399))
        return token


def _token_hatasi(veri: dict, durum: int) -> str:
    """Token uçlarından gelen hatayı anlaşılır Türkçeye çevirir."""
    ham = str(veri.get("error", "") or veri.get("errors", "") or "")
    aciklama = str(veri.get("error_description", "") or "")
    if "shop_not_permitted" in ham or "shop_not_permitted" in aciklama:
        return (
            "Uygulama ile mağaza aynı Shopify organizasyonunda görünmüyor "
            "(shop_not_permitted). Dev Dashboard'da uygulamanın bu mağazaya "
            "kurulu olduğunu ve SHOPIFY_STORE değerinin doğru olduğunu kontrol edin."
        )
    if "invalid_client" in ham or durum in (400, 401):
        return (
            "İstemci kimliği veya gizli anahtar kabul edilmedi. Dev Dashboard > "
            "Ayarlar > Kimlik bilgileri'ndeki değerlerle birebir aynı olmalı "
            f"(HTTP {durum}: {ham or aciklama or 'ayrıntı yok'})."
        )
    return f"Shopify token alınamadı (HTTP {durum}): {ham or aciklama or veri}"


_token_deposu = _TokenDeposu()


class Shopify:
    def __init__(
        self,
        magaza: str | None = None,
        token: str | None = None,
        istemci_kimligi: str | None = None,
        gizli_anahtar: str | None = None,
    ):
        self.magaza = (magaza or config.SHOPIFY_STORE).strip()
        self._sabit_token = (
            token if token is not None else config.SHOPIFY_TOKEN
        ).strip()
        self.istemci_kimligi = (
            istemci_kimligi if istemci_kimligi is not None
            else config.SHOPIFY_ISTEMCI_KIMLIGI
        ).strip()
        self.gizli_anahtar = (
            gizli_anahtar if gizli_anahtar is not None
            else config.SHOPIFY_GIZLI_ANAHTAR
        ).strip()

        if not self.magaza:
            raise ShopifyHatasi("SHOPIFY_STORE ayarlanmalı (.env).")
        if not self._sabit_token and not (self.istemci_kimligi and self.gizli_anahtar):
            raise ShopifyHatasi(
                "Shopify kimliği eksik (.env): ya SHOPIFY_TOKEN, ya da "
                "SHOPIFY_ISTEMCI_KIMLIGI + SHOPIFY_GIZLI_ANAHTAR doldurulmalı."
            )
        self.url = f"https://{self.magaza}/admin/api/{config.SHOPIFY_API_SURUMU}/graphql.json"

    @property
    def kimlik_yontemi(self) -> str:
        return "token" if self._sabit_token else "istemci kimliği"

    @property
    def token(self) -> str:
        if self._sabit_token:
            return self._sabit_token
        return _token_deposu.getir(
            self.magaza, self.istemci_kimligi, self.gizli_anahtar
        )

    def _cagir(self, sorgu: str, degiskenler: dict, tekrar: bool = True) -> dict:
        with httpx.Client(timeout=30) as istemci:
            cevap = istemci.post(
                self.url,
                headers={
                    "X-Shopify-Access-Token": self.token,
                    "Content-Type": "application/json",
                },
                json={"query": sorgu, "variables": degiskenler},
            )
        if cevap.status_code == 401 and not self._sabit_token and tekrar:
            # Token 24 saatte doluyor; uzun açık kalan panelde süresi geçmiş
            # olabilir. Önbelleği atıp bir kez yeniden dene.
            _token_deposu.temizle()
            return self._cagir(sorgu, degiskenler, tekrar=False)
        if cevap.status_code != 200:
            raise ShopifyHatasi(f"Shopify HTTP {cevap.status_code}: {cevap.text[:300]}")

        veri = cevap.json()
        if veri.get("errors"):
            raise ShopifyHatasi(f"Shopify GraphQL hatası: {veri['errors']}")
        return veri.get("data", {})

    def faturalanmamis_siparisler(
        self,
        tetikleyici: str = "fulfilled",
        limit: int = 100,
        baslangic: str = "",
        bitis: str = "",
    ) -> list[dict]:
        """Henüz faturalandırılmamış, ödemesi alınmış siparişleri getirir.

        tetikleyici: "fulfilled" (kargolananlar) veya "paid" (ödenenler).
        baslangic/bitis: YYYY-AA-GG, ikisi de isteğe bağlı. Verilirse sipariş
        tarihi bu aralığın dışında kalanlar hiç çekilmez — birikmiş siparişleri
        küçük partiler halinde faturalayabilmek için.
        """
        durum = "fulfillment_status:shipped" if tetikleyici == "fulfilled" else ""
        parcalar = ["financial_status:paid", f"-tag:{config.ETIKET}"]
        if durum:
            parcalar.append(durum)
        if baslangic:
            parcalar.append(f"created_at:>={_tarih_dogrula(baslangic)}T00:00:00Z")
        if bitis:
            # Bitiş günü dahil olsun diye günün sonuna kadar alınıyor.
            parcalar.append(f"created_at:<={_tarih_dogrula(bitis)}T23:59:59Z")
        sorgu = " AND ".join(parcalar)

        siparisler: list[dict] = []
        imlec = None
        while len(siparisler) < limit:
            veri = self._cagir(
                SIPARIS_SORGUSU,
                {
                    "sorgu": sorgu,
                    "adet": min(50, limit - len(siparisler)),
                    "imlec": imlec,
                },
            )
            blok = veri.get("orders", {})
            for siparis in blok.get("nodes", []):
                if siparis.get("cancelledAt"):
                    continue
                siparisler.append(siparis)

            sayfa = blok.get("pageInfo", {})
            if not sayfa.get("hasNextPage"):
                break
            imlec = sayfa.get("endCursor")

        return siparisler

    def siparis_ara(self, numara: str) -> dict | None:
        """Sipariş numarasıyla tek sipariş getirir ('#1077' ya da '1077').

        Durum/etiket filtresi uygulanmaz; elle verilen numarayı olduğu gibi
        bulur. Shopify 'name:1077' aramasında benzer numaraları da
        döndürebildiği için sonuç birebir doğrulanıyor.
        """
        numara = numara.strip().lstrip("#")
        if not numara:
            return None
        veri = self._cagir(
            SIPARIS_SORGUSU, {"sorgu": f"name:{numara}", "adet": 10, "imlec": None}
        )
        for siparis in veri.get("orders", {}).get("nodes", []):
            if (siparis.get("name") or "").lstrip("#") == numara:
                return siparis
        return None

    def faturalandi_isaretle(self, siparis_id: str, ettn: str = "") -> None:
        """Siparişe 'faturalandi' etiketini ve ETTN metafield'ını yazar."""
        sonuc = self._cagir(
            ETIKET_EKLE, {"id": siparis_id, "etiketler": [config.ETIKET]}
        )
        hatalar = sonuc.get("tagsAdd", {}).get("userErrors", [])
        if hatalar:
            raise ShopifyHatasi(f"Etiket eklenemedi: {hatalar}")

        if ettn:
            self._cagir(
                METAFIELD_YAZ,
                {
                    "girdiler": [
                        {
                            "ownerId": siparis_id,
                            "namespace": "fatura",
                            "key": "ettn",
                            "type": "single_line_text_field",
                            "value": ettn,
                        }
                    ]
                },
            )
