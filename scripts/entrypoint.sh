#!/bin/bash
set -e

echo "Torrent Cleaner - Entrypoint"
echo "=============================="

# Load environment variables from .env if exists
if [ -f /app/.env ]; then
    echo "Loading environment from /app/.env"
    set -a
    . /app/.env
    set +a
fi

# Create path aliases (symlinks) so qBittorrent's container paths resolve
# inside a single volume mount. Hardlinks cannot cross separate bind mounts,
# so torrents and media must live under ONE mount — aliases bridge the naming.
# Format: PATH_ALIASES=/downloads=/data/torrents/downloads,/other=/data/other
if [ -n "${PATH_ALIASES:-}" ]; then
    IFS=',' read -ra path_aliases <<< "$PATH_ALIASES"
    for alias in "${path_aliases[@]}"; do
        link="${alias%%=*}"
        target="${alias#*=}"
        if [ -z "$link" ] || [ -z "$target" ] || [ "$link" = "$target" ]; then
            echo "WARNING: invalid PATH_ALIASES entry: '$alias' (expected /link=/target)"
            continue
        fi
        if [ -e "$link" ] && [ ! -L "$link" ]; then
            echo "WARNING: $link already exists and is not a symlink, skipping alias"
            continue
        fi
        mkdir -p "$(dirname "$link")"
        ln -sfn "$target" "$link"
        echo "Path alias: $link -> $target"
    done
fi

CRON_SCHEDULE="${CRON_SCHEDULE:-0 2 * * *}"
echo "Configuring cron schedule: $CRON_SCHEDULE"

# Create cron job
cat > /etc/cron.d/torrent-cleaner << EOF
# Torrent Cleaner Cron Job
SHELL=/bin/bash

$CRON_SCHEDULE root /app/scripts/run_cleaner.sh > /proc/1/fd/1 2>&1
EOF

chmod 0644 /etc/cron.d/torrent-cleaner

mkdir -p /app/data/torrent-cleaner/logs /app/data/torrent-cleaner/cache

# Save full environment for cron (contains credentials — keep it root-only)
export -p > /app/data/torrent-cleaner/.env.cron
chmod 600 /app/data/torrent-cleaner/.env.cron
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
