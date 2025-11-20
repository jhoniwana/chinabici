#!/bin/bash

set -e

echo "🚀 Desplegando Telegram Video Downloader Bot"
echo ""

if [ ! -f .env ]; then
    echo "⚠️  Archivo .env no encontrado"
    echo "Creando .env desde .env.example..."
    cp .env.example .env
    echo ""
    echo "⚠️  IMPORTANTE: Edita el archivo .env y agrega tu BOT_TOKEN"
    echo "   nano .env"
    echo ""
    read -p "Presiona Enter cuando hayas configurado el BOT_TOKEN..."
fi

if ! command -v docker &> /dev/null; then
    echo "❌ Docker no está instalado"
    echo ""
    echo "Instala Docker primero:"
    echo "  curl -fsSL https://get.docker.com -o get-docker.sh"
    echo "  sudo sh get-docker.sh"
    exit 1
fi

if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    echo "❌ Docker Compose no está instalado"
    echo ""
    echo "Instala Docker Compose:"
    echo "  sudo apt install docker-compose-plugin"
    exit 1
fi

echo "✓ Verificaciones completadas"
echo ""
echo "🔄 Deteniendo contenedor anterior..."
docker-compose down

echo ""
echo "🧹 Limpiando caché de Docker..."
docker system prune -f

echo ""
echo "📦 Construyendo imagen Docker (sin caché)..."
docker-compose build --no-cache

echo ""
echo "🚀 Iniciando contenedor..."
docker-compose up -d

echo ""
echo "✅ Bot desplegado exitosamente!"
echo ""
echo "📊 Comandos útiles:"
echo "  Ver logs:      docker-compose logs -f"
echo "  Detener bot:   docker-compose down"
echo "  Reiniciar:     docker-compose restart"
echo "  Estado:        docker-compose ps"
echo ""
echo "🎉 El bot está corriendo en segundo plano"
