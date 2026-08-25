"""Masaüstü uygulaması giriş noktası.

FastAPI sunucusunu arka planda 127.0.0.1'de açar ve paneli kendi
penceresinde gösterir (Windows'ta Edge WebView2). Tarayıcı, konsol ya da
.bat dosyası görünmez.

    .venv\\Scripts\\python.exe masaustu.py      # kaynaktan
    MagiclandFatura.exe                        # paketlenmiş
"""

from __future__ import annotations

import socket
import sys
import threading
import time

import uvicorn
import webview

from fatura import config, guncelleme
from fatura.web import uygulama

PENCERE_BASLIGI = f"{config.UYGULAMA_ADI}  {config.SURUM}"

ACILIS_EKRANI = """
<!doctype html><html lang="tr"><head><meta charset="utf-8">
<style>
  :root { color-scheme: light dark; }
  body {
    margin: 0; height: 100vh; display: grid; place-items: center;
    font: 15px/1.5 "Segoe UI", system-ui, sans-serif;
    background: #f6f7f9; color: #1a1d21;
  }
  @media (prefers-color-scheme: dark) {
    body { background: #0f1115; color: #e8eaed; }
    .cubuk { background: #2a2f38 !important; }
  }
  .kutu { text-align: center; }
  .ad { font-size: 19px; font-weight: 600; margin-bottom: 6px; }
  .alt { font-size: 13px; opacity: .6; margin-bottom: 18px; }
  .cubuk { width: 220px; height: 3px; border-radius: 999px; background: #e3e6ea; overflow: hidden; }
  .cubuk > i { display: block; height: 100%; width: 38%; border-radius: 999px;
               background: #2563eb; animation: kayar 1.1s ease-in-out infinite; }
  @keyframes kayar { 0% { transform: translateX(-100%); } 100% { transform: translateX(320%); } }
  @media (prefers-reduced-motion: reduce) { .cubuk > i { animation: none; width: 100%; } }
</style></head>
<body><div class="kutu">
  <div class="ad">Magicland Fatura</div>
  <div class="alt">Başlatılıyor…</div>
  <div class="cubuk"><i></i></div>
</div></body></html>
"""


def bos_port() -> int:
    """Boşta bir port seçer; 8787 doluysa uygulama açılmasın istemiyoruz."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def sunucuyu_baslat(port: int) -> uvicorn.Server:
    ayar = uvicorn.Config(
        uygulama, host="127.0.0.1", port=port,
        log_level="warning", access_log=False,
    )
    sunucu = uvicorn.Server(ayar)
    threading.Thread(target=sunucu.run, daemon=True).start()
    return sunucu


def sunucuyu_bekle(port: int, saniye: float = 25.0) -> bool:
    son = time.monotonic() + saniye
    while time.monotonic() < son:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.4):
                return True
        except OSError:
            time.sleep(0.12)
    return False


def main() -> int:
    guncelleme.acilisi_gunlukle()
    config.taniyi_gunlukle()
    # Bir önceki güncellemeden kalan .eski.exe varsa şimdi silinebilir.
    guncelleme.eski_surumu_temizle()

    port = bos_port()
    sunucuyu_baslat(port)

    pencere = webview.create_window(
        PENCERE_BASLIGI,
        html=ACILIS_EKRANI,
        width=1280, height=860,
        min_size=(940, 620),
        text_select=True,
    )

    def hazir_olunca() -> None:
        if sunucuyu_bekle(port):
            pencere.load_url(f"http://127.0.0.1:{port}/")
        else:
            pencere.load_html(
                "<body style='font:15px system-ui;padding:40px'>"
                "<h3>Uygulama başlatılamadı</h3>"
                "<p>Lütfen kapatıp yeniden açın.</p></body>"
            )

    # private_mode=True (varsayılan) şart: kapalıyken WebView2 sabit bir
    # profil klasörü kullanıyor ve aynı anda iki örnek açılamıyor. Güncelleme
    # sırasında eski sürüm birkaç saniye daha ayakta kaldığı için yeni sürüm
    # o profili alamayıp sessizce ölüyordu. Kalıcı veri zaten sunucu
    # tarafında (ayarlar.json + SQLite), tarayıcı profilinde tutulan bir şey
    # yok.
    webview.start(hazir_olunca)
    return 0


if __name__ == "__main__":
    sys.exit(main())
