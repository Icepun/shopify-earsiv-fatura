#!/usr/bin/env python3
"""Uygulamayı tek dosyalık .exe haline getirir.

    .venv\\Scripts\\python.exe derle.py

Çıktı: dist\\MagiclandFatura.exe

Tek dosya (onefile) seçildi çünkü güncelleme mekanizması çalışan .exe'nin
adını değiştirip yerine yenisini koyuyor; bu yalnızca tek dosyada işe yarar.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

KOK = Path(__file__).resolve().parent
sys.path.insert(0, str(KOK))

from fatura import config  # noqa: E402

CIKTI_ADI = "MagiclandFatura"

# uvicorn ve pywebview alt modüllerini çalışma anında import ettiği için
# PyInstaller onları kendiliğinden bulamıyor.
GIZLI_ICE_AKTARIMLAR = [
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.asyncio",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "webview.platforms.edgechromium",
    "webview.platforms.winforms",
    "clr",
]


def temizle() -> None:
    for klasor in ("build", "dist"):
        yol = KOK / klasor
        if yol.exists():
            shutil.rmtree(yol, ignore_errors=True)
    spec = KOK / f"{CIKTI_ADI}.spec"
    spec.unlink(missing_ok=True)


def main() -> int:
    if sys.platform != "win32":
        print("Bu betik Windows icin yazildi.")
        return 1

    print(f"Surum {config.SURUM} derleniyor...")
    temizle()

    komut = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--onefile",
        "--windowed",                      # konsol penceresi acilmasin
        "--name", CIKTI_ADI,
        "--add-data", f"{KOK / 'static'}{';'}static",
    ]
    for modul in GIZLI_ICE_AKTARIMLAR:
        komut += ["--hidden-import", modul]

    simge = KOK / "simge.ico"
    if simge.exists():
        komut += ["--icon", str(simge)]

    komut.append(str(KOK / "masaustu.py"))

    sonuc = subprocess.run(komut, cwd=KOK)
    if sonuc.returncode != 0:
        print("\nDerleme basarisiz.")
        return sonuc.returncode

    exe = KOK / "dist" / f"{CIKTI_ADI}.exe"
    if not exe.exists():
        print("\n.exe olusmadi.")
        return 1

    mb = exe.stat().st_size / 1048576
    print(f"\nHazir: {exe}  ({mb:.1f} MB)")
    print("GitHub'da 'v" + config.SURUM + "' etiketiyle release olusturup "
          "bu dosyayi ekleyin; uygulama guncellemeyi oradan alir.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
