# 🎬 Telegram Video Downloader Bot

Bot de Telegram para descargar videos de YouTube, Instagram, TikTok, Facebook, Twitter y 1000+ sitios.

## ✨ Características

- 🎵 **YouTube:** Elige entre MP3 (audio) o MP4 (video)
- 📹 **Otras plataformas:** Descarga automática en mejor calidad
- 🤖 **Markov:** Generador de frases con `/xd`, mensajes automáticos cada 2 horas, y aprendizaje de mensajes del grupo
- 🚀 **Rápido:** Descargas optimizadas por plataforma
- 🐳 **Docker:** Despliega fácilmente en cualquier VPS
- 🔄 **Auto-limpieza:** Elimina archivos temporales automáticamente

## 🌐 Plataformas Soportadas

YouTube • Instagram • TikTok • Facebook • Twitter/X • Reddit • Vimeo • Dailymotion • Twitch • SoundCloud • y 1000+ más

## 🚀 Despliegue Rápido (VPS con Docker)

```bash
# 1. Instalar Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo apt install docker-compose-plugin -y

# 2. Clonar repositorio
git clone https://github.com/TU_USUARIO/chinabici.git
cd chinabici

# 3. Configurar token
echo "BOT_TOKEN=tu_token_de_botfather" > .env

# 4. Desplegar
chmod +x deploy.sh
./deploy.sh
```

**¡Listo!** Tu bot está corriendo 24/7.

## 📱 Uso

1. Abre tu bot en Telegram
2. Envía `/start`
3. Envía cualquier link de video
4. **YouTube:** Elige MP3 o MP4 con botones
5. **Otras plataformas:** Descarga automática

### Ejemplo con YouTube

```
Tú: https://youtube.com/watch?v=xxxxx

Bot: YouTube detected!
     Choose format:
     [🎵 MP3 (Audio)]  [🎬 MP4 (Video)]

Tú: *presionas MP3*

Bot: ⏳ Downloading MP3...
     🎵 [Audio enviado]
```

## 🛠️ Comandos Docker

```bash
# Ver logs
docker-compose logs -f

# Reiniciar bot
docker-compose restart

# Detener bot
docker-compose down

# Iniciar bot
docker-compose up -d

# Actualizar después de git pull
docker-compose down && docker-compose build && docker-compose up -d
```

## 📋 Instalación Local (sin Docker)

### Arch Linux

```bash
# Actualizar e instalar Python
sudo pacman -Syu --noconfirm
sudo pacman -S --noconfirm python python-pip ffmpeg

# Crear entorno virtual
python -m venv venv
source venv/bin/activate

# Instalar dependencias
pip install -U pip
pip install -r requirements.txt

# Configurar entorno
cp .env.example .env
# Edita .env y coloca tu BOT_TOKEN

# Ejecutar
python main.py
```

### Debian/Ubuntu

```bash
# Instalar dependencias del sistema
sudo apt install python3 python3-pip ffmpeg -y

# Crear entorno virtual
python3 -m venv venv
source venv/bin/activate

# Instalar dependencias Python
pip install -r requirements.txt

# Configurar token
echo "BOT_TOKEN=tu_token" > .env

# Ejecutar
python main.py
```

## 🔧 Configuración

Crea un archivo `.env` con tu token:

```env
BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz

# Markov (generador de frases)
MARKOV_ENABLED=true
MARKOV_CHAT_ID=@tu_grupo_o_chat
MARKOV_INTERVAL_MINUTES=120
MARKOV_MODEL_PATH=./model.json
MARKOV_LEARN_ENABLED=true
MARKOV_RETRAIN_INTERVAL_HOURS=24
```

### Obtener Token

1. Abre Telegram
2. Busca `@BotFather`
3. Envía `/newbot`
4. Sigue las instrucciones
5. Copia el token

### Configurar mensajes automáticos Markov

- `MARKOV_ENABLED=true` — Activa el generador y el envío automático.
- `MARKOV_CHAT_ID` — Chat o grupo donde se enviarán los mensajes automáticos. Puede ser un ID numérico (`-1001234567890`) o un alias (`@mi_grupo`).
- `MARKOV_INTERVAL_MINUTES` — Intervalo en minutos entre mensajes automáticos. Por defecto: `120` (2 horas).
- `MARKOV_MODEL_PATH` — Ruta al modelo entrenado (`model.json`).

> **Nota:** Si `MARKOV_CHAT_ID` está vacío, el bot responderá `/xd` pero no enviará mensajes automáticos. El aprendizaje (`MARKOV_LEARN_ENABLED`) funciona en cualquier chat donde esté el bot.

## 📁 Estructura del Proyecto

```
chinabici/
├── main.py                 # Código principal del bot
├── markov_service.py       # Servicio de generación Markov
├── model.json              # Modelo Markov entrenado
├── Dockerfile              # Imagen Docker
├── docker-compose.yml      # Orquestación
├── requirements.txt        # Dependencias Python
├── deploy.sh               # Script de despliegue
├── .env                    # Token y config (crear desde .env.example)
└── README.md              # Este archivo
```

## 🎯 Características Técnicas

### YouTube (con botones de elección)
- **MP3:** Audio 192kbps, archivos pequeños (~7MB)
- **MP4:** Video 720p + audio, mejor calidad (~35MB)

### Otras Plataformas (auto-descarga)
- Mejor calidad disponible en MP4
- Optimización por plataforma

### Markov (`/xd`)
- **`/xd`** — Genera una frase aleatoria usando el modelo entrenado.
- **`/xd <semilla>`** — Intenta generar una frase que empiece con la palabra dada (ej: `/xd hola`).
- **Mensajes automáticos** — El bot envía una frase generada cada 2 horas (configurable) al chat indicado en `MARKOV_CHAT_ID`.
- **Aprendizaje automático** — El bot guarda los mensajes de texto del grupo (excluyendo comandos y URLs) y reentrena el modelo cada 24 horas automáticamente.

### Límites
- Videos < 50MB → Enviados como video
- Videos > 50MB → Enviados como documento
- Máximo: 2GB (límite de Telegram)

## 🐛 Troubleshooting

### Bot no responde
```bash
docker-compose logs --tail=50
```

### Actualizar yt-dlp
```bash
docker-compose exec bot pip install -U yt-dlp
docker-compose restart
```

### Limpiar espacio
```bash
rm -rf downloads/*
docker system prune -a
```

## 📚 Documentación Completa

- [DEPLOY.md](DEPLOY.md) - Guía completa de despliegue
- [MP3_MP4_GUIDE.md](MP3_MP4_GUIDE.md) - Guía de formatos
- [YOUTUBE_GUIDE.md](YOUTUBE_GUIDE.md) - Guía de YouTube

## 🔐 Seguridad

- ✅ Token en `.env` (no subir a Git)
- ✅ Archivos temporales auto-eliminados
- ✅ Contenedor Docker aislado
- ✅ Logs rotados automáticamente

## 📊 Monitoreo

```bash
# Logs en tiempo real
docker-compose logs -f

# Estado del contenedor
docker-compose ps

# Uso de recursos
docker stats chinabici-bot
```

## 🔄 Actualización

```bash
cd chinabici
git pull
docker-compose down
docker-compose build
docker-compose up -d
```

## 📝 Licencia

Este proyecto es solo para uso educativo. Los usuarios son responsables de respetar los derechos de autor y términos de servicio de cada plataforma.

## ⭐ Créditos

- **Bot Framework:** [Aiogram 3](https://docs.aiogram.dev/)
- **Downloader:** [yt-dlp](https://github.com/yt-dlp/yt-dlp)
- **Media Processing:** [FFmpeg](https://ffmpeg.org/)

---

**Made with ❤️ using Python & Docker**
