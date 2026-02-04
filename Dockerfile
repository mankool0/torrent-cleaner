FROM python:3.14-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    cron \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY scripts/ ./scripts/
RUN chmod +x ./scripts/*.sh

RUN mkdir -p /var/log/torrent-cleaner

ENTRYPOINT ["/app/scripts/entrypoint.sh"]

# Run cron in foreground
CMD ["cron", "-f"]
