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

rem Klasorun degil, python.exe'nin varligina bakiyoruz: yarim kalmis bir
rem kurulumda .venv klasoru olusur ama ici bos kalir.
if not exist ".venv\Scripts\python.exe" (
    echo Sanal ortam kuruluyor, bu islem bir kac dakika surebilir...
    python -m venv .venv
    if errorlevel 1 goto :venvhata
    .venv\Scripts\python.exe -m pip install --quiet --upgrade pip
    .venv\Scripts\python.exe -m pip install --quiet -r requirements.txt
    if errorlevel 1 goto :pakethata
    echo Kurulum tamam.
)

rem Paket kurulumu daha once yarida kesildiyse burada yakalanir.
.venv\Scripts\python.exe -c "import fastapi, uvicorn, httpx, dotenv" >nul 2>nul
if errorlevel 1 (
    echo Eksik paketler tamamlaniyor...
    .venv\Scripts\python.exe -m pip install --quiet -r requirements.txt
    if errorlevel 1 goto :pakethata
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

rem Tarayiciyi hemen degil, sunucu portu dinlemeye basladiginda ac.
start "" /b powershell -NoProfile -WindowStyle Hidden -Command "for($i=0;$i -lt 80;$i++){try{$c=New-Object Net.Sockets.TcpClient('127.0.0.1',8787);$c.Close();break}catch{Start-Sleep -Milliseconds 250}}; Start-Process 'http://127.0.0.1:8787'"

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
