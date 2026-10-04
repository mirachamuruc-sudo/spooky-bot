# ------------------------------------------------------------------------------
# 🎃 HALLOWEEN DISCORD BOT DOCKERFILE (Python 3.11-slim)
# ------------------------------------------------------------------------------
FROM python:3.11-slim

# Verhindert .pyc Dateien & puffert Logs nicht (für sofortige Konsolenlogs)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System-Abhängigkeiten installieren
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Abhängigkeiten kopieren & installieren (Layer-Caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Persistenter Speicherordner für SQLite (/data Volume auf Fly.io)
RUN mkdir -p /data

# Bot-Code kopieren
COPY bot.py .

# Standard-Befehl
CMD ["python", "bot.py"]
