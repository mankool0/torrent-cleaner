#!/bin/bash
set -e

echo "Torrent Cleaner - Entrypoint"
echo "=============================="

# Load environment variables from .env if exists
if [ -f /app/.env ]; then
    echo "Loading environment from /app/.env"
    export $(cat /app/.env | grep -v '^#' | xargs)
fi

CRON_SCHEDULE="${CRON_SCHEDULE:-0 2 * * *}"
echo "Configuring cron schedule: $CRON_SCHEDULE"

# Create cron job
# Note: Cron needs environment variables to be set explicitly
cat > /etc/cron.d/torrent-cleaner << EOF
# Torrent Cleaner Cron Job
SHELL=/bin/bash
PATH=/usr/local/bin:/usr/bin:/bin

# Environment variables for Python
QBITTORRENT_HOST=${QBITTORRENT_HOST:-}
QBITTORRENT_PORT=${QBITTORRENT_PORT:-8080}
QBITTORRENT_USERNAME=${QBITTORRENT_USERNAME:-}
QBITTORRENT_PASSWORD=${QBITTORRENT_PASSWORD:-}
TORRENT_DIR=${TORRENT_DIR:-/data/torrents}
MEDIA_LIBRARY_DIR=${MEDIA_LIBRARY_DIR:-/data/media}
DELETION_CRITERIA=${DELETION_CRITERIA:-30d 2.0}
DRY_RUN=${DRY_RUN:-true}
FIX_HARDLINKS=${FIX_HARDLINKS:-true}
DISCORD_WEBHOOK_URL=${DISCORD_WEBHOOK_URL:-}
LOG_LEVEL=${LOG_LEVEL:-INFO}
LOG_FILE=${LOG_FILE:-/app/data/torrent-cleaner/logs/cleaner.log}

$CRON_SCHEDULE root /app/scripts/run_cleaner.sh >> /app/data/torrent-cleaner/logs/cron.log 2>&1
EOF

chmod 0644 /etc/cron.d/torrent-cleaner

mkdir -p /app/data/torrent-cleaner/logs /app/data/torrent-cleaner/cache
touch /app/data/torrent-cleaner/logs/cron.log
touch /app/data/torrent-cleaner/logs/cleaner.log

echo "Cron job configured successfully"
echo "Schedule: $CRON_SCHEDULE"
echo ""

if [ "${RUN_ON_STARTUP:-false}" = "true" ]; then
    echo "RUN_ON_STARTUP is set, running cleaner now..."
    /app/scripts/run_cleaner.sh
fi

echo "Starting cron daemon..."
echo "Logs: /app/data/torrent-cleaner/logs/cron.log"
echo ""

# Execute the main command (cron -f)
exec "$@"
