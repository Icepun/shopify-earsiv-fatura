#!/usr/bin/env bash
# Fatura panelini başlatır: http://127.0.0.1:8787
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "→ Sanal ortam kuruluyor…"
  python3 -m venv .venv
  ./.venv/bin/pip install --quiet --upgrade pip
  ./.venv/bin/pip install --quiet -r requirements.txt
fi

if [ ! -f .env ]; then
  cp .env.example .env
  echo "⚠  .env oluşturuldu — Shopify ve GİB bilgilerini doldurup tekrar çalıştırın."
  exit 1
fi

echo "→ Panel: http://127.0.0.1:8787"
exec ./.venv/bin/uvicorn fatura.web:uygulama --host 127.0.0.1 --port 8787
