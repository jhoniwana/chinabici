# Telegram Video Downloader Bot

Bot simple para descargar videos de YouTube, Instagram, TikTok, Facebook, Twitter y 1000+ sitios.

## Instalación Rápida

1. **Instalar dependencias:**
```bash
pip install -r requirements.txt
```

2. **Configurar token:**
Edita el archivo `.env` y agrega tu token de @BotFather:
```
BOT_TOKEN=tu_token_aqui
```

3. **Ejecutar:**
```bash
python main.py
```

## Uso

1. Abre tu bot en Telegram
2. Envía `/start`
3. Envía cualquier link de video
4. El bot descargará y enviará el video

## Plataformas Soportadas

- YouTube
- Instagram
- TikTok
- Facebook
- Twitter/X
- Reddit
- Vimeo
- Dailymotion
- Y 1000+ más (via yt-dlp)

## Notas

- Videos grandes (>50MB) se envían como documentos
- Videos pequeños (<50MB) se envían como videos
- Los archivos se eliminan automáticamente después de enviar

## Estructura Simple

```
chinabici/
├── main.py              # Todo el código del bot
├── requirements.txt     # Dependencias
├── .env                 # Tu token (no subir a git)
└── downloads/           # Archivos temporales
```

Eso es todo! Bot simple y funcional.
