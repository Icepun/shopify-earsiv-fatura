"""GİB e-Arşiv Portal istemcisi.

Portalın web arayüzünün kullandığı JSON uçlarıyla konuşur:

    POST /earsiv-services/assos-login   -> token alır
    POST /earsiv-services/dispatch      -> tüm komutlar (cmd + jp)

Bu uçlar GİB tarafından resmî olarak dokümante edilmemiştir; arayüz
değişirse burası güncellenmelidir. Komut adları ve fatura payload'ı
mlevent/fatura ve keyiflerolsun/eArsivPortal projelerinden doğrulandı.

Fatura imzalama SMS ile yapılır ve tek SMS kodu ile birden fazla fatura
onaylanabilir — toplu kesim buna dayanır.
"""

from __future__ import annotations

import json
import ssl
import uuid

import httpx

YAYIN_URL = "https://earsivportal.efatura.gov.tr"
TEST_URL = "https://earsivportaltest.efatura.gov.tr"

# (komut, sayfa) çiftleri
FATURA_OLUSTUR = ("EARSIV_PORTAL_FATURA_OLUSTUR", "RG_BASITFATURA")
TASLAKLARI_GETIR = ("EARSIV_PORTAL_TASLAKLARI_GETIR", "RG_BASITTASLAKLAR")
FATURA_GOSTER = ("EARSIV_PORTAL_FATURA_GOSTER", "RG_BASITTASLAKLAR")
FATURA_SIL = ("EARSIV_PORTAL_FATURA_SIL", "RG_BASITTASLAKLAR")
TELEFON_SORGULA = ("EARSIV_PORTAL_TELEFONNO_SORGULA", "RG_SMSONAY")
SMS_GONDER = ("EARSIV_PORTAL_SMSSIFRE_GONDER", "RG_SMSONAY")
SMS_DOGRULA = ("EARSIV_PORTAL_SMSSIFRE_DOGRULA", "RG_SMSONAY")
KULLANICI_GETIR = ("EARSIV_PORTAL_KULLANICI_BILGILERI_GETIR", "RG_KULLANICI")


class GibHatasi(RuntimeError):
    pass


class OturumDustu(GibHatasi):
    pass


def _ssl_baglami() -> ssl.SSLContext:
    """GİB sunucusu eski TLS renegotiation kullanıyor; buna izin verir."""
    baglam = ssl.create_default_context()
    baglam.options |= 0x4  # OP_LEGACY_SERVER_CONNECT
    try:
        baglam.set_ciphers("DEFAULT@SECLEVEL=1")
    except ssl.SSLError:
        pass
    return baglam


class GibPortal:
    def __init__(self, kullanici_kodu: str, sifre: str, test_modu: bool = True):
        self.kullanici_kodu = kullanici_kodu
        self.sifre = sifre
        self.test_modu = test_modu
        self.url = TEST_URL if test_modu else YAYIN_URL
        self.token: str | None = None
        self._istemci = httpx.Client(
            verify=_ssl_baglami(),
            timeout=60,
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"},
        )

    # ─── oturum ──────────────────────────────────────────────────────

    def giris(self) -> str:
        cevap = self._istemci.post(
            f"{self.url}/earsiv-services/assos-login",
            data={
                "assoscmd": "login" if self.test_modu else "anologin",
                "rtype": "json",
                "userid": self.kullanici_kodu,
                "sifre": self.sifre,
                "sifre2": self.sifre,
                "parola": "1",
            },
        )
        if cevap.status_code != 200:
            raise GibHatasi(f"Giriş başarısız (HTTP {cevap.status_code}).")

        veri = cevap.json()
        token = veri.get("token")
        if not token:
            mesaj = self._hata_metni(veri) or "Kullanıcı kodu veya şifre hatalı."
            raise GibHatasi(f"GİB girişi başarısız: {mesaj}")

        self.token = token
        return token

    def cikis(self) -> None:
        if not self.token:
            return
        try:
            self._istemci.post(
                f"{self.url}/earsiv-services/assos-login",
                data={"assoscmd": "logout", "rtype": "json", "token": self.token},
            )
        finally:
            self.token = None

    def kapat(self) -> None:
        self.cikis()
        self._istemci.close()

    def __enter__(self) -> "GibPortal":
        self.giris()
        return self

    def __exit__(self, *_) -> None:
        self.kapat()

    # ─── çekirdek ────────────────────────────────────────────────────

    @staticmethod
    def _hata_metni(veri) -> str:
        if not isinstance(veri, dict):
            return ""
        mesajlar = veri.get("messages") or []
        if mesajlar:
            ilk = mesajlar[0]
            return ilk.get("text", "") if isinstance(ilk, dict) else str(ilk)
        return ""

    def calistir(self, komut: tuple[str, str], jp: dict, tekrar: bool = True):
        if not self.token:
            self.giris()

        cmd, sayfa = komut
        cevap = self._istemci.post(
            f"{self.url}/earsiv-services/dispatch",
            data={
                "cmd": cmd,
                "callid": str(uuid.uuid4()),
                "pageName": sayfa,
                "token": self.token,
                # ensure_ascii=True şart: GİB tarafı ham UTF-8 gövdeyi
                # çözemeyip bütün alanları boş okuyor ve yanıltıcı bir
                # "Ettn eksik" hatası döndürüyor. \uXXXX kaçışı güvenli.
                "jp": json.dumps(jp),
            },
        )
        if cevap.status_code != 200:
            raise GibHatasi(f"{cmd}: HTTP {cevap.status_code}")

        try:
            veri = cevap.json()
        except ValueError:
            raise GibHatasi(f"{cmd}: beklenmeyen yanıt ({cevap.text[:200]})")

        if veri.get("error"):
            mesaj = self._hata_metni(veri) or "Bilinmeyen GİB hatası."
            if "zamanaşımına" in mesaj or "Oturum" in mesaj:
                if tekrar:
                    self.giris()
                    return self.calistir(komut, jp, tekrar=False)
                raise OturumDustu(mesaj)
            raise GibHatasi(f"{cmd}: {mesaj}")

        return veri.get("data")

    # ─── işlemler ────────────────────────────────────────────────────

    def kullanici_bilgileri(self) -> dict:
        return self.calistir(KULLANICI_GETIR, {}) or {}

    def fatura_olustur(self, fatura_verisi: dict) -> None:
        """Taslak fatura oluşturur. SMS gerekmez.

        ETTN'i portal kendisi üretir ve yanıtta döndürmez; hangi taslağın
        oluştuğunu bulmak için `taslak_ettnleri()` ile öncesi/sonrası
        farkına bakılır.
        """
        sonuc = self.calistir(FATURA_OLUSTUR, fatura_verisi)
        if not sonuc or "başarıyla" not in str(sonuc):
            raise GibHatasi(f"Fatura oluşturulamadı: {sonuc}")

    def taslak_ettnleri(self, baslangic: str, bitis: str) -> set[str]:
        """Verilen aralıktaki taslakların ETTN kümesi."""
        return {
            t.get("ettn") for t in self.taslaklari_getir(baslangic, bitis) if t.get("ettn")
        }

    def taslaklari_getir(self, baslangic: str, bitis: str) -> list[dict]:
        """Verilen tarih aralığındaki taslakları döner (gg/aa/yyyy)."""
        sonuc = self.calistir(
            TASLAKLARI_GETIR,
            {
                "baslangic": baslangic,
                "bitis": bitis,
                "hangiTip": "5000/30000",
                "table": [],
            },
        )
        return sonuc or []

    def fatura_sil(self, taslaklar: list[dict], aciklama: str = "Hatalı kayıt") -> str:
        return self.calistir(
            FATURA_SIL, {"silinecekler": taslaklar, "aciklama": aciklama}
        )

    def fatura_html(self, ettn: str, onay_durumu: str = "Onaylandı") -> str:
        return self.calistir(
            FATURA_GOSTER, {"ettn": ettn, "onayDurumu": onay_durumu}
        )

    def indirme_linki(self, ettn: str, onay_durumu: str = "Onaylandı") -> str:
        from urllib.parse import quote

        return (
            f"{self.url}/earsiv-services/download"
            f"?token={self.token}&ettn={ettn}&belgeTip=FATURA"
            f"&onayDurumu={quote(onay_durumu)}&cmd=downloadResource&"
        )

    # ─── toplu SMS imzalama ──────────────────────────────────────────

    def sms_kodu_iste(self) -> tuple[str, str]:
        """Kayıtlı cep telefonuna SMS gönderir. (oid, telefon) döner."""
        telefon_veri = self.calistir(TELEFON_SORGULA, {}) or {}
        telefon = telefon_veri.get("telefon")
        if not telefon:
            raise GibHatasi(
                "Portalda kayıtlı cep telefonu bulunamadı. "
                "e-Arşiv Portal > Kullanıcı Bilgileri bölümünden telefon ekleyin."
            )

        sonuc = self.calistir(
            SMS_GONDER, {"CEPTEL": telefon, "KCEPTEL": False, "TIP": ""}
        )
        oid = (sonuc or {}).get("oid")
        if not oid:
            raise GibHatasi(f"SMS gönderilemedi: {sonuc}")
        return oid, telefon

    def sms_ile_imzala(self, kod: str, oid: str, taslaklar: list[dict]) -> str:
        """Tek SMS kodu ile verilen taslakların tamamını imzalar."""
        sonuc = self.calistir(
            SMS_DOGRULA,
            {"SIFRE": kod, "OID": oid, "OPR": 1, "DATA": taslaklar},
        )
        mesaj = (sonuc or {}).get("msg", "")
        if "başarı" not in str(mesaj).lower() and "onayland" not in str(mesaj).lower():
            raise GibHatasi(f"İmzalama başarısız: {mesaj or sonuc}")
        return mesaj
