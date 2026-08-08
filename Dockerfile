FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    nodejs \
    libva2 \
    libva-drm2 \
    vainfo \
    intel-media-va-driver \
    i965-va-driver \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/* \
    && find /usr -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt \
    && find /usr -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

# Copy pre-installed node_modules for ultra-igdl (npm is NOT installed via apt)
COPY package.json igdl_helper.js ./
COPY node_modules ./node_modules
COPY markov_service.py .
COPY model.json .
COPY messages_clean.txt .
COPY main.py .

RUN mkdir -p downloads logs

CMD ["python", "-u", "main.py"]
