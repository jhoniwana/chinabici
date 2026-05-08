FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    chromium \
    chromium-driver \
    curl \
    nodejs \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/* \
    && find /usr -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt \
    && find /usr -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

COPY markov_service.py .
COPY model.json .
COPY messages_clean.txt .
COPY main.py .

RUN mkdir -p downloads logs

CMD ["python", "-u", "main.py"]
