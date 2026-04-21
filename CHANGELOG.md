# Changelog - chinabici bot

## [2026-04-21] - Limpieza y arreglo de bugs

### Cambios realizados:

#### 1. ✅ Removida función de chat OpenRouter
- **antes**: El bot tenía funcionalidad de chat con IA usando OpenRouter
- **ahora**: El bot solo descarga videos de redes sociales
- **archivo modificado**: `main.py`, `docker-compose.yml`

#### 2. ✅ Arreglado error de cookies.txt
- **antes**: Error `ERROR: '/app/cookies.txt' does not look like a Netscape format cookies file`
- **原因**: El archivo cookies.txt estaba vacío y el docker-compose intentaba montarlo
- **ahora**: Removido el mount de cookies.txt del docker-compose.yml
- **archivo modificado**: `docker-compose.yml`

#### 3. ✅ Commits subidos a Git
- Commit: `3314a58` - Remove empty cookies.txt and update Dockerfile

---

## Pendiente - Bugs Críticos (Fase 1):

### 🔴 Bug 1: Facebook Reels → solo imagen
- **Causa**: `is_image_platform()` atrapa cualquier facebook.com, incluyendo Reels
- **Solución**: Agregar función `is_facebook_video()` que detecte Reels/videos
- **Estado**: 🔴 PENDIENTE

### 🔴 Bug 2: Facebook video formato incorrecto  
- **Causa**: `best[ext=mp4]/best` falla en FB porque video y audio vienen separados
- **Solución**: Usar `bestvideo[ext=mp4]+bestaudio/best` + merge_output_format
- **Estado**: 🔴 PENDIENTE

### 🔴 Bug 3: Instagram scraping con curl no funciona
- **Causa**: Instagram sirve HTML vacío a curl, contenido es JS
- **Solución**: Usar gallery-dl (ya instalado en requirements.txt)
- **Estado**: 🔴 PENDIENTE

### 🔴 Bug 4: Videos cargados en RAM
- **Causa**: `file_data = await f.read()` carga video entero en memoria
- **Solución**: Usar `FSInputFile` de Aiogram 3 para stream directo
- **Estado**: 🔴 PENDIENTE

---

## Estado por Red Social

| Red | Estado | Notas |
|-----|--------|-------|
| YouTube | ⚠️ | Funciona pero puede fallar sin cookies |
| Facebook Reels | ❌ | Bug de routing - va a imágenes |
| Facebook Posts | ⚠️ | Selenium frágil |
| Instagram Reels | ✅ | Funciona |
| Instagram Posts | ❌ | curl no funciona - necesita gallery-dl |
| TikTok | ⚠️ | Con watermark |
| Twitter/X | ⚠️ | Sin detección completa |
| Reddit | ❌ | No implementado |

---

## Comandos útiles

```bash
# Ver logs del bot
docker logs chinabici-bot --tail=50

# Reiniciar bot
docker restart chinabici-bot

# Rebuild después de cambios
docker-compose down && docker-compose build && docker-compose up -d
```
