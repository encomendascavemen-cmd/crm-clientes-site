#!/bin/bash
# Cavemen Store — Atualização diária de dados de produtos
# Corre: extract_products.py e recarrega o servidor se estiver ativo

DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/update.log"

echo "$(date '+%Y-%m-%d %H:%M:%S') — Início da atualização" >> "$LOG"

cd "$DIR"
/usr/bin/python3 extract_products.py >> "$LOG" 2>&1

# Recarregar servidor se estiver a correr
curl -s http://localhost:5001/api/reload_products >> "$LOG" 2>&1

echo "$(date '+%Y-%m-%d %H:%M:%S') — Atualização concluída" >> "$LOG"
echo "---" >> "$LOG"
