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
import urllib.error
import urllib.request
from pathlib import Path

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


def _istek(yol: str, veri=None, yontem=None, ham=None, tur=None, taban=API):
    istek = urllib.request.Request(taban + yol, method=yontem)
    istek.add_header("Authorization", "Bearer " + _token())
    istek.add_header("Accept", "application/vnd.github+json")
    istek.add_header("User-Agent", "magicland-fatura")
    if ham is not None:
        istek.data = ham
        istek.add_header("Content-Type", tur or "application/octet-stream")
    elif veri is not None:
        istek.data = json.dumps(veri).encode()
        istek.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(istek) as cevap:
        govde = cevap.read()
        return json.loads(govde) if govde else {}


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
    except urllib.error.HTTPError as hata:
        if hata.code != 404:
            print("  release okunamadi:", hata.code, hata.read().decode()[:200])
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
