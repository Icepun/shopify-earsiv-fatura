#!/usr/bin/env python3
"""Derlenmiş .exe'yi GitHub Releases'e yayınlar.

    .venv\\Scripts\\python.exe derle.py
    .venv\\Scripts\\python.exe yayinla.py

Sürüm numarası `fatura/config.py` içindeki SURUM'dan okunur; etiket
`vSURUM` olur. GH_TOKEN ortam değişkeni gerekir (repo yetkisi olan bir
GitHub tokeni).
"""

from __future__ import annotations

import json
import mimetypes
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

KOK = Path(__file__).resolve().parent
sys.path.insert(0, str(KOK))

from fatura import config  # noqa: E402

EXE = KOK / "dist" / "MagiclandFatura.exe"
API = "https://api.github.com"


def _token() -> str:
    tok = os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN")
    if not tok:
        print("GH_TOKEN ortam degiskeni yok.")
        raise SystemExit(1)
    return tok


class YayinHatasi(RuntimeError):
    def __init__(self, kod: int, govde: str):
        self.kod = kod
        super().__init__(f"HTTP {kod}: {govde[:300]}")


def _istek(yol: str, veri=None, yontem=None, ham=None, tur=None, taban=API,
           deneme: int = 4):
    """GitHub API çağrısı. Ağ koparsa yeniden dener.

    19 MB'lık .exe yüklerken bağlantı zaman zaman düşüyor; tek denemede
    bırakmak release'i yarım bırakıyordu.
    """
    basliklar = {
        "Authorization": "Bearer " + _token(),
        "Accept": "application/vnd.github+json",
        "User-Agent": "magicland-fatura",
    }
    govde_tipi = {}
    if ham is not None:
        basliklar["Content-Type"] = tur or "application/octet-stream"
        govde_tipi = {"content": ham}
    elif veri is not None:
        govde_tipi = {"json": veri}

    son_hata = None
    for sira in range(deneme):
        try:
            with httpx.Client(timeout=httpx.Timeout(300.0, connect=30.0)) as istemci:
                cevap = istemci.request(
                    yontem or "GET", taban + yol, headers=basliklar, **govde_tipi
                )
            if cevap.status_code >= 400:
                # 4xx tekrar denemeye değmez (404 hariç, çağıran ele alıyor).
                raise YayinHatasi(cevap.status_code, cevap.text)
            return cevap.json() if cevap.content else {}
        except httpx.HTTPError as hata:
            son_hata = hata
            if sira < deneme - 1:
                bekle = 2 ** sira
                print(f"    baglanti koptu, {bekle} sn sonra tekrar ({sira + 2}/{deneme})")
                time.sleep(bekle)
    raise RuntimeError(f"GitHub'a ulasilamadi: {son_hata}")


def _etiketi_hazirla(etiket: str) -> None:
    """Etiketi yerelde oluşturup uzağa iter (yoksa)."""
    mevcut = subprocess.run(
        ["git", "tag", "-l", etiket], cwd=KOK, capture_output=True, text=True
    ).stdout.strip()
    if not mevcut:
        subprocess.run(["git", "tag", etiket], cwd=KOK, check=True)
    subprocess.run(["git", "push", "origin", etiket], cwd=KOK, check=False)


def main() -> int:
    if not EXE.exists():
        print(f"{EXE} yok. Once derle.py calistirin.")
        return 1

    surum = config.SURUM
    etiket = f"v{surum}"
    depo = config.GITHUB_DEPO
    print(f"Yayinlaniyor: {depo} {etiket}  ({EXE.stat().st_size / 1048576:.1f} MB)")

    _etiketi_hazirla(etiket)

    # Aynı etiketle release varsa varlığı ona ekleyelim, yenisini açmayalım.
    try:
        yayin = _istek(f"/repos/{depo}/releases/tags/{etiket}")
        print("  mevcut release bulundu, varlik guncellenecek")
    except YayinHatasi as hata:
        if hata.kod != 404:
            print("  release okunamadi:", hata)
            return 1
        yayin = _istek(
            f"/repos/{depo}/releases",
            {
                "tag_name": etiket,
                "name": f"Magicland Fatura {surum}",
                "body": (
                    "Windows icin tek dosyalik uygulama.\n\n"
                    "`MagiclandFatura.exe` dosyasini indirip cift tiklayin. "
                    "Kurulum gerekmez.\n\n"
                    "Windows ilk acilista \"bilinmeyen yayimci\" uyarisi "
                    "gosterebilir: **Daha fazla bilgi -> Yine de calistir**."
                ),
                "draft": False,
                "prerelease": False,
            },
            "POST",
        )
        print("  release olusturuldu")

    # Aynı adlı eski varlık varsa silinmeli; GitHub üzerine yazmıyor.
    for varlik in yayin.get("assets", []):
        if varlik["name"] == EXE.name:
            _istek(f"/repos/{depo}/releases/assets/{varlik['id']}", yontem="DELETE")
            print("  eski varlik silindi")

    yukleme = yayin["upload_url"].split("{")[0]
    tur = mimetypes.guess_type(EXE.name)[0] or "application/octet-stream"
    print("  .exe yukleniyor...")
    varlik = _istek(
        f"?name={EXE.name}", ham=EXE.read_bytes(), tur=tur, yontem="POST", taban=yukleme
    )
    print("  yuklendi:", varlik["browser_download_url"])
    print()
    print("Yayin sayfasi:", yayin["html_url"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
