#!/bin/bash

echo "🤖 Iniciando bot de descarga de videos..."
echo ""

if [ ! -f .env ]; then
    echo "❌ Error: Archivo .env no encontrado"
    echo "Crea el archivo .env con tu BOT_TOKEN"
    exit 1
fi

source china/bin/activate 2>/dev/null || {
    echo "⚠️  Activando entorno virtual..."
    source venv/bin/activate 2>/dev/null || {
        echo "❌ No se encontró entorno virtual"
        exit 1
    }
}

echo "✓ Entorno activado"
echo "✓ Iniciando bot..."
echo ""

python main.py
