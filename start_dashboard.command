#!/bin/bash
# Duplo clique neste ficheiro para arrancar o dashboard
cd "$(dirname "$0")"
echo "🪨 Cavemen Store Dashboard"
echo ""
echo "A verificar dependências..."
pip3 install flask requests --quiet 2>/dev/null

echo ""
echo "A arrancar servidor..."
echo "→ Abre http://localhost:5001 no browser"
echo ""
python3 server.py
