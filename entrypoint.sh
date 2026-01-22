#!/bin/bash
# =============================================================================
# GreenGate - Entrypoint Script
# =============================================================================

set -e

echo "=========================================="
echo "  GreenGate - Iniciando..."
echo "=========================================="

# Verificar DATABASE_URL
if [ -z "$DATABASE_URL" ]; then
    echo "ERRO: DATABASE_URL não configurada!"
    exit 1
fi

echo "[1/2] DATABASE_URL configurada"
echo "[2/2] Iniciando servidor..."
echo ""
echo "=========================================="
echo "  API iniciando em http://0.0.0.0:${PORT:-8000}"
echo "=========================================="
echo ""

exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port ${PORT:-8000} \
    --workers 1 \
    --timeout-keep-alive 5
