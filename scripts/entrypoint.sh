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
cat > /etc/cron.d/torrent-cleaner << EOF
# Torrent Cleaner Cron Job
SHELL=/bin/bash

$CRON_SCHEDULE root /app/scripts/run_cleaner.sh > /dev/null 2>&1
EOF

chmod 0644 /etc/cron.d/torrent-cleaner

mkdir -p /app/data/torrent-cleaner/logs /app/data/torrent-cleaner/cache

# Save full environment for cron
export -p > /app/data/torrent-cleaner/.env.cron
touch /app/data/torrent-cleaner/logs/cleaner.log

echo "Cron job configured successfully"
echo "Schedule: $CRON_SCHEDULE"
echo ""

if [ "${RUN_ON_STARTUP:-false}" = "true" ]; then
    echo "RUN_ON_STARTUP is set, running cleaner now..."
    /app/scripts/run_cleaner.sh
fi

echo "Starting cron daemon..."
echo "Logs: /app/data/torrent-cleaner/logs/cleaner.log"
echo ""

# Execute the main command (cron -f)
exec "$@"
