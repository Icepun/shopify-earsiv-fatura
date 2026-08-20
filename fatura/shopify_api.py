"""Shopify Admin GraphQL API istemcisi."""

from __future__ import annotations

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
  billingAddress { firstName lastName address1 city province countryCode zip phone company }
  shippingAddress { firstName lastName address1 city province countryCode zip phone company }
  customer { email phone displayName }
  lineItems(first: 100) {
    nodes {
      title
      quantity
      currentQuantity
      discountedTotalSet { shopMoney { amount } }
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


class Shopify:
    def __init__(self, magaza: str | None = None, token: str | None = None):
        self.magaza = (magaza or config.SHOPIFY_STORE).strip()
        self.token = (token or config.SHOPIFY_TOKEN).strip()
        if not self.magaza or not self.token:
            raise ShopifyHatasi("SHOPIFY_STORE ve SHOPIFY_TOKEN ayarlanmalı (.env).")
        self.url = f"https://{self.magaza}/admin/api/{config.SHOPIFY_API_SURUMU}/graphql.json"

    def _cagir(self, sorgu: str, degiskenler: dict) -> dict:
        with httpx.Client(timeout=30) as istemci:
            cevap = istemci.post(
                self.url,
                headers={
                    "X-Shopify-Access-Token": self.token,
                    "Content-Type": "application/json",
                },
                json={"query": sorgu, "variables": degiskenler},
            )
        if cevap.status_code != 200:
            raise ShopifyHatasi(f"Shopify HTTP {cevap.status_code}: {cevap.text[:300]}")

        veri = cevap.json()
        if veri.get("errors"):
            raise ShopifyHatasi(f"Shopify GraphQL hatası: {veri['errors']}")
        return veri.get("data", {})

    def faturalanmamis_siparisler(
        self, tetikleyici: str = "fulfilled", limit: int = 100
    ) -> list[dict]:
        """Henüz faturalandırılmamış, ödemesi alınmış siparişleri getirir.

        tetikleyici: "fulfilled" (kargolananlar) veya "paid" (ödenenler).
        """
        durum = "fulfillment_status:shipped" if tetikleyici == "fulfilled" else ""
        parcalar = ["financial_status:paid", f"-tag:{config.ETIKET}"]
        if durum:
            parcalar.append(durum)
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
