# Despliegue en VPS con Docker

Guía completa para desplegar el bot en tu VPS Ubuntu usando Docker.

## 📋 Prerequisitos

- VPS con Ubuntu 20.04 o superior
- Acceso SSH al VPS
- Git instalado
- Bot Token de @BotFather

## 🚀 Instalación Rápida (3 pasos)

### 1. Conectar al VPS e Instalar Docker

```bash
# Conectar a tu VPS
ssh usuario@tu-vps-ip

# Instalar Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Instalar Docker Compose
sudo apt update
sudo apt install docker-compose-plugin -y

# Agregar tu usuario al grupo docker (opcional, evita usar sudo)
sudo usermod -aG docker $USER
newgrp docker
```

### 2. Clonar el Repositorio

```bash
# Clonar desde GitHub
git clone https://github.com/TU_USUARIO/chinabici.git
cd chinabici
```

### 3. Configurar y Desplegar

```bash
# Crear archivo .env con tu token
echo "BOT_TOKEN=tu_token_aqui" > .env

# Desplegar con un solo comando
./deploy.sh
```

**¡Listo!** El bot está corriendo.

---

## 📦 Opción Manual (paso a paso)

Si prefieres hacerlo manualmente:

### 1. Configurar Variables de Entorno

```bash
# Crear .env desde el ejemplo
cp .env.example .env

# Editar y agregar tu token
nano .env
```

Contenido del `.env`:
```
BOT_TOKEN=8589751159:AAEiwsRqQb_gY9BUAQ38GGT1Ld8up4lP3HA
```

### 2. Construir la Imagen Docker

```bash
docker-compose build
```

Esto instalará:
- Python 3.11
- FFmpeg (para conversión de video/audio)
- Todas las dependencias de requirements.txt

### 3. Iniciar el Bot

```bash
docker-compose up -d
```

El flag `-d` lo ejecuta en segundo plano (detached).

---

## 🛠️ Comandos Útiles

### Ver Logs en Tiempo Real
```bash
docker-compose logs -f
```

### Detener el Bot
```bash
docker-compose down
```

### Reiniciar el Bot
```bash
docker-compose restart
```

### Ver Estado
```bash
docker-compose ps
```

### Actualizar el Bot (después de git pull)
```bash
git pull
docker-compose down
docker-compose build
docker-compose up -d
```

### Entrar al Contenedor
```bash
docker-compose exec bot bash
```

### Ver Uso de Recursos
```bash
docker stats chinabici-bot
```

---

## 📁 Estructura de Archivos

```
chinabici/
├── Dockerfile              # Configuración de la imagen Docker
├── docker-compose.yml      # Orquestación del contenedor
├── .dockerignore          # Archivos a ignorar en build
├── deploy.sh              # Script de despliegue automático
├── main.py                # Código del bot
├── requirements.txt       # Dependencias Python
├── .env                   # Variables de entorno (tu token)
├── downloads/             # Videos temporales (montado como volumen)
└── logs/                  # Logs del bot (montado como volumen)
```

---

## 🔄 Flujo de Actualización

Cuando hagas cambios en GitHub:

```bash
# En tu VPS
cd chinabici
git pull                    # Descargar últimos cambios
docker-compose down         # Detener bot actual
docker-compose build        # Reconstruir imagen
docker-compose up -d        # Iniciar nueva versión
docker-compose logs -f      # Ver logs
```

**Tip:** Puedes crear un script de actualización:

```bash
#!/bin/bash
# update.sh
cd /home/usuario/chinabici
git pull
docker-compose down
docker-compose build
docker-compose up -d
echo "✅ Bot actualizado!"
```

---

## 🐛 Troubleshooting

### El bot no inicia

```bash
# Ver logs completos
docker-compose logs

# Verificar que el token esté correcto
cat .env

# Verificar que Docker esté corriendo
sudo systemctl status docker
```

### Error: "Cannot connect to Docker daemon"

```bash
# Iniciar Docker
sudo systemctl start docker

# Habilitar Docker al inicio
sudo systemctl enable docker
```

### Bot se detiene solo

```bash
# Verificar logs
docker-compose logs --tail=100

# El restart: unless-stopped en docker-compose.yml
# debería reiniciarlo automáticamente
```

### No hay espacio en disco

```bash
# Limpiar descargas antiguas
rm -rf downloads/*

# Limpiar imágenes Docker no usadas
docker system prune -a
```

### Actualizar yt-dlp sin reconstruir

```bash
docker-compose exec bot pip install -U yt-dlp
docker-compose restart
```

---

## 🔐 Seguridad

### Proteger el archivo .env

```bash
chmod 600 .env
```

### Firewall (opcional pero recomendado)

```bash
# Permitir SSH
sudo ufw allow 22/tcp

# Habilitar firewall
sudo ufw enable
```

### Actualizar el sistema

```bash
sudo apt update && sudo apt upgrade -y
```

---

## 📊 Monitoreo

### Ver logs de las últimas 24 horas

```bash
docker-compose logs --since 24h
```

### Ver solo errores

```bash
docker-compose logs | grep ERROR
```

### Logs con timestamps

```bash
docker-compose logs -f --timestamps
```

---

## 🎯 Configuración Avanzada

### Cambiar zona horaria

Edita `docker-compose.yml`:

```yaml
environment:
  - TZ=America/Mexico_City
```

### Limitar recursos

Edita `docker-compose.yml`:

```yaml
services:
  bot:
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 512M
```

### Reinicio automático al reiniciar VPS

```yaml
restart: always
```

---

## 🚀 Deploy con GitHub Actions (opcional)

Crea `.github/workflows/deploy.yml`:

```yaml
name: Deploy to VPS

on:
  push:
    branches: [ main ]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - name: Deploy via SSH
        uses: appleboy/ssh-action@master
        with:
          host: ${{ secrets.VPS_HOST }}
          username: ${{ secrets.VPS_USER }}
          key: ${{ secrets.VPS_SSH_KEY }}
          script: |
            cd chinabici
            git pull
            docker-compose down
            docker-compose build
            docker-compose up -d
```

---

## ✅ Checklist de Despliegue

- [ ] VPS con Ubuntu listo
- [ ] Docker instalado
- [ ] Docker Compose instalado
- [ ] Repositorio clonado
- [ ] Archivo .env creado con BOT_TOKEN
- [ ] `./deploy.sh` ejecutado
- [ ] Bot funcionando (`docker-compose ps`)
- [ ] Logs sin errores (`docker-compose logs`)
- [ ] Probado en Telegram

---

## 💡 Tips

1. **Usa screen o tmux** para mantener sesiones SSH:
   ```bash
   screen -S bot
   cd chinabici
   docker-compose logs -f
   # Ctrl+A+D para detach
   ```

2. **Backup del .env**:
   ```bash
   cp .env .env.backup
   ```

3. **Limpiar descargas diariamente**:
   ```bash
   # Agregar a crontab
   0 3 * * * rm -rf /home/usuario/chinabici/downloads/*
   ```

4. **Monitoreo con Portainer** (UI para Docker):
   ```bash
   docker volume create portainer_data
   docker run -d -p 9000:9000 --name portainer \
     --restart=always \
     -v /var/run/docker.sock:/var/run/docker.sock \
     -v portainer_data:/data \
     portainer/portainer-ce
   ```

---

## 🎉 ¡Listo!

Tu bot ahora está:
- ✅ Corriendo en Docker
- ✅ Reinicio automático si falla
- ✅ Logs persistentes
- ✅ Fácil de actualizar
- ✅ Aislado del sistema

**Comandos que usarás frecuentemente:**

```bash
docker-compose logs -f      # Ver logs
docker-compose restart      # Reiniciar
docker-compose down         # Detener
docker-compose up -d        # Iniciar
```
