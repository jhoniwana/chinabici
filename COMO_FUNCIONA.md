# ¿Cómo Funciona el Bot?

## 📱 Flujo de Usuario

```
1. Usuario envía URL → https://youtube.com/watch?v=xxxxx
2. Bot responde     → "⏳ Downloading..."
3. Bot descarga     → Usa yt-dlp para descargar el video
4. Bot envía        → "📤 Sending..."
5. Usuario recibe   → Video en el chat de Telegram
6. Bot limpia       → Elimina archivo temporal
```

## ⚙️ Funcionamiento Técnico

### Paso 1: Usuario envía un link
```
Usuario: https://www.youtube.com/watch?v=dQw4w9WgXcQ
```

### Paso 2: Bot valida la URL
```python
if not url.startswith(('http://', 'https://')):
    return "Invalid URL"
```

### Paso 3: Bot descarga con yt-dlp
```python
ydl_opts = {
    'outtmpl': 'downloads/%(id)s.%(ext)s',  # Guarda en downloads/
    'format': 'best[ext=mp4]/best',         # Mejor calidad MP4
    'retries': 3,                            # Reintenta 3 veces
}

with yt_dlp.YoutubeDL(ydl_opts) as ydl:
    info = ydl.extract_info(url, download=True)
    filename = ydl.prepare_filename(info)
```

**Resultado:**
- Archivo descargado: `downloads/dQw4w9WgXcQ.mp4`
- Info extraída: título, duración, tamaño

### Paso 4: Bot decide cómo enviar

```python
filesize = os.path.getsize(filename)

if filesize > 50 MB:
    # Videos grandes → Enviar como DOCUMENTO
    await message.answer_document(video_file)
else:
    # Videos pequeños → Enviar como VIDEO
    await message.answer_video(video_file)
```

### Paso 5: Bot envía a Telegram

```python
async with aiofiles.open(filename, 'rb') as f:
    video_data = await f.read()
    video_input = BufferedInputFile(video_data, filename="video.mp4")
    await message.answer_video(video_input)
```

### Paso 6: Bot limpia el archivo

```python
await asyncio.to_thread(os.remove, filename)
```

**Archivo temporal eliminado** para ahorrar espacio.

## 🌐 Plataformas Soportadas

El bot usa **yt-dlp** que soporta:

### Principales:
- ✅ **YouTube** - Videos, shorts, playlists
- ✅ **Instagram** - Posts, Reels, Stories, IGTV
- ✅ **TikTok** - Videos (sin watermark en algunos casos)
- ✅ **Facebook** - Videos públicos
- ✅ **Twitter/X** - Videos y GIFs
- ✅ **Reddit** - v.redd.it videos
- ✅ **Vimeo** - Videos públicos
- ✅ **Dailymotion** - Videos

### Otras plataformas (1000+):
- Twitch clips y VODs
- SoundCloud (audio)
- Streamable
- Imgur (videos/GIFs)
- Bilibili
- VK (VKontakte)
- Y muchas más...

## 📊 Ejemplos de URLs Válidas

```bash
# YouTube
https://www.youtube.com/watch?v=dQw4w9WgXcQ
https://youtu.be/dQw4w9WgXcQ

# Instagram
https://www.instagram.com/reel/C1234567890/
https://www.instagram.com/p/C1234567890/

# TikTok
https://www.tiktok.com/@user/video/1234567890
https://vt.tiktok.com/ZS1234567/

# Twitter
https://twitter.com/user/status/1234567890
https://x.com/user/status/1234567890

# Facebook
https://www.facebook.com/watch/?v=1234567890
https://fb.watch/xxxxx/
```

## 🔍 Detección de Errores

### Error: Video Privado
```
❌ Download failed

The video might be private or unavailable.
```
**Solución:** El video debe ser público

### Error: URL Inválida
```
Please send a valid URL starting with http:// or https://
```
**Solución:** Copia la URL completa del navegador

### Error: Archivo muy grande
```
File is too large for Telegram (limit: 2GB)
```
**Solución:** Telegram tiene límite de 2GB por archivo

## 💡 Características Técnicas

### Async/Await
El bot usa programación asíncrona:
```python
async def download_video(message):
    await message.answer("Downloading...")
    # No bloquea otros usuarios mientras descarga
```

### Limpieza Automática
```python
await cleanup_file(filename)
# Elimina archivos después de enviar
# Evita llenar el disco
```

### Manejo de Errores
```python
try:
    # Descargar
except yt_dlp.utils.DownloadError:
    # Error específico de descarga
except Exception as e:
    # Cualquier otro error
```

### Logs
Todo se registra en `logs/bot.log`:
```
2025-11-15 21:27:58 - INFO - Bot starting...
2025-11-15 21:28:15 - INFO - Download request: https://youtube.com/...
2025-11-15 21:28:23 - INFO - Download completed: downloads/xxxxx.mp4
2025-11-15 21:28:25 - INFO - Cleaned up: downloads/xxxxx.mp4
```

## 🚀 Comandos del Bot

### /start
Muestra mensaje de bienvenida:
```
Video Downloader Bot

Send me any video link and I'll download it for you.

Supported: YouTube, Instagram, TikTok, Facebook, Twitter, and 1000+ sites
```

### Cualquier URL
Descarga automáticamente el video del enlace

## 📦 Estructura de Archivos

```
downloads/
├── dQw4w9WgXcQ.mp4          # Video descargado
├── C1234567890.mp4          # Otro video
└── ...                       # (se eliminan tras enviar)

logs/
└── bot.log                   # Registro de actividad

main.py                       # Código del bot
.env                          # Token secreto
```

## 🔐 Seguridad

- ✅ Token en `.env` (no se sube a Git)
- ✅ Validación de URLs
- ✅ Manejo seguro de archivos
- ✅ Límites de tamaño
- ✅ Limpieza automática

## ⚡ Rendimiento

- **Concurrente:** Múltiples usuarios simultáneos
- **Async I/O:** No bloquea durante descargas
- **Reintentos:** 3 intentos automáticos si falla
- **Timeout:** 30 segundos por socket

## 🛠️ Troubleshooting

### Bot no responde
```bash
# Verifica que esté corriendo
ps aux | grep python

# Revisa logs
tail -f logs/bot.log
```

### Downloads fallan
```bash
# Actualiza yt-dlp
pip install -U yt-dlp

# Verifica espacio en disco
df -h
```

### Errores de permisos
```bash
# Da permisos a carpetas
chmod 755 downloads logs
```
