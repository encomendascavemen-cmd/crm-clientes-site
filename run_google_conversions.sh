#!/bin/bash
# Cavemen Store — Envio diário de Enhanced Conversions para o Google Ads

DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/google_conversions.log"

echo "$(date '+%Y-%m-%d %H:%M:%S') — Início do envio Google Ads" >> "$LOG"

cd "$DIR"
MOLONI_PASSWORD="7+LVn*QU+4sdrXN" /usr/bin/python3 google_offline_conversions.py >> "$LOG" 2>&1

echo "$(date '+%Y-%m-%d %H:%M:%S') — Envio concluído" >> "$LOG"
echo "---" >> "$LOG"
