@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Shopify - e-Arsiv Fatura

where python >nul 2>nul
if errorlevel 1 (
    echo.
    echo [HATA] Python bulunamadi.
    echo python.org/downloads adresinden Python 3.11+ kurun.
    echo Kurulum sirasinda "Add python.exe to PATH" secenegini isaretleyin.
    echo.
    pause
    exit /b 1
)

if not exist .venv (
    echo Sanal ortam kuruluyor, bu islem bir kac dakika surebilir...
    python -m venv .venv
    if errorlevel 1 goto :venvhata
    .venv\Scripts\python.exe -m pip install --quiet --upgrade pip
    .venv\Scripts\python.exe -m pip install --quiet -r requirements.txt
    if errorlevel 1 goto :pakethata
    echo Kurulum tamam.
)

if not exist .env (
    copy .env.example .env >nul
    echo.
    echo .env dosyasi olusturuldu.
    echo Shopify ve GIB bilgilerinizi doldurup bu dosyayi tekrar calistirin.
    echo.
    notepad .env
    pause
    exit /b 1
)

echo.
echo Panel aciliyor: http://127.0.0.1:8787
echo Kapatmak icin bu pencerede Ctrl+C
echo.
start "" http://127.0.0.1:8787
.venv\Scripts\python.exe -m uvicorn fatura.web:uygulama --host 127.0.0.1 --port 8787
goto :eof

:venvhata
echo [HATA] Sanal ortam olusturulamadi.
pause
exit /b 1

:pakethata
echo [HATA] Paketler kurulamadi. Internet baglantinizi kontrol edin.
pause
exit /b 1
