"""Uygulamanın aynı anda tek kopya çalışmasını sağlar (Windows).

Açılış birkaç saniye sürdüğü için simgeye ikinci kez tıklamak ikinci bir
uygulama açıyordu. İkinci kopya artık açılmaz; açık olan pencere öne gelir.
"""

from __future__ import annotations

import ctypes
import os
import sys
import time
from ctypes import wintypes

from . import config

KILIT_ADI = "MagiclandFatura.TekOrnek"
_ZATEN_VAR = 183                    # ERROR_ALREADY_EXISTS
_SINIRLI_SORGU = 0x1000             # PROCESS_QUERY_LIMITED_INFORMATION
_GERI_YUKLE = 9                     # SW_RESTORE

# Tutamaç süreç yaşadıkça açık kalmalı; kapanırsa kilit de kalkar.
_kilit = None


def kilidi_al(bekleme: float = 15.0) -> bool:
    """Bu kopya çalışmaya devam etsin mi?

    Başka bir kopya açıksa onun penceresini öne getirir ve False döner.
    Kilit duruyor ama pencere bir türlü çıkmıyorsa önceki kopya kapanırken
    takılmıştır; kullanıcıyı uygulamasız bırakmamak için True döner.
    """
    global _kilit
    if sys.platform != "win32":
        return True

    cekirdek = ctypes.WinDLL("kernel32", use_last_error=True)
    cekirdek.CreateMutexW.restype = wintypes.HANDLE
    cekirdek.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    cekirdek.CloseHandle.argtypes = [wintypes.HANDLE]

    son = time.monotonic() + bekleme
    while True:
        ctypes.set_last_error(0)
        tutamac = cekirdek.CreateMutexW(None, False, KILIT_ADI)
        if ctypes.get_last_error() != _ZATEN_VAR:
            _kilit = tutamac
            return True
        cekirdek.CloseHandle(tutamac)
        # Öteki kopya ya penceresini açmak üzere ya da kapanmak üzere:
        # penceresi görünürse ona geç, kilit kalkarsa yerini al.
        if _pencereyi_one_getir():
            return False
        if time.monotonic() >= son:
            return True
        time.sleep(0.25)


def _pencereyi_one_getir() -> bool:
    """Açık uygulama penceresini bulur ve öne getirir."""
    arayuz = ctypes.WinDLL("user32", use_last_error=True)
    geri_cagri = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    arayuz.EnumWindows.argtypes = [geri_cagri, wintypes.LPARAM]
    arayuz.IsWindowVisible.argtypes = [wintypes.HWND]
    arayuz.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    arayuz.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    arayuz.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    arayuz.IsIconic.argtypes = [wintypes.HWND]
    arayuz.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    arayuz.SetForegroundWindow.argtypes = [wintypes.HWND]

    bulunan: list[int] = []
    # sys.executable ile karşılaştırılmıyor: sanal ortamda o yol asıl
    # yorumlayıcıyı başlatan küçük bir aracıya ait, pencere ise asıl
    # yorumlayıcının. Sürecin kendi yolu her kurulumda doğru sonucu verir.
    kendi_yolu = _surec_yolu(os.getpid())

    @geri_cagri
    def bak(pencere, _):
        if not arayuz.IsWindowVisible(pencere):
            return True
        uzunluk = arayuz.GetWindowTextLengthW(pencere)
        if not uzunluk:
            return True
        baslik = ctypes.create_unicode_buffer(uzunluk + 1)
        arayuz.GetWindowTextW(pencere, baslik, uzunluk + 1)
        if not baslik.value.startswith(config.UYGULAMA_ADI):
            return True
        # Aynı adı taşıyan bir klasör penceresi de olabilir; yalnızca bizim
        # programın penceresi sayılır.
        surec = wintypes.DWORD()
        arayuz.GetWindowThreadProcessId(pencere, ctypes.byref(surec))
        if surec.value == os.getpid() or not kendi_yolu:
            return True
        if _surec_yolu(surec.value) != kendi_yolu:
            return True
        bulunan.append(pencere)
        return False

    arayuz.EnumWindows(bak, 0)
    if not bulunan:
        return False
    if arayuz.IsIconic(bulunan[0]):
        arayuz.ShowWindow(bulunan[0], _GERI_YUKLE)
    arayuz.SetForegroundWindow(bulunan[0])
    return True


def _surec_yolu(surec_no: int) -> str:
    """Sürecin çalıştığı .exe'nin tam yolu; okunamazsa boş."""
    cekirdek = ctypes.WinDLL("kernel32", use_last_error=True)
    cekirdek.OpenProcess.restype = wintypes.HANDLE
    cekirdek.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    cekirdek.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD)]
    cekirdek.CloseHandle.argtypes = [wintypes.HANDLE]

    tutamac = cekirdek.OpenProcess(_SINIRLI_SORGU, False, surec_no)
    if not tutamac:
        return ""
    try:
        boy = wintypes.DWORD(32768)
        yol = ctypes.create_unicode_buffer(boy.value)
        if not cekirdek.QueryFullProcessImageNameW(tutamac, 0, yol, ctypes.byref(boy)):
            return ""
        return os.path.normcase(yol.value)
    finally:
        cekirdek.CloseHandle(tutamac)
