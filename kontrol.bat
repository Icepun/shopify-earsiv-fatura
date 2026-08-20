@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Baglanti Kontrolu

if not exist .venv (
    echo [HATA] Once baslat.bat calistirilmali - kurulumu o yapiyor.
    pause
    exit /b 1
)
if not exist .env (
    echo [HATA] .env dosyasi yok. Once baslat.bat calistirin.
    pause
    exit /b 1
)

.venv\Scripts\python.exe kontrol.py
echo.
pause
