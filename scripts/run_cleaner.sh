#!/bin/bash

if [ -f /app/data/torrent-cleaner/.env.cron ]; then
    . /app/data/torrent-cleaner/.env.cron
fi

echo ""
echo "========================================"
echo "Torrent Cleaner - $(date)"
echo "========================================"
echo ""

cd /app
python3 -m src.main

exit_code=$?

echo ""
echo "========================================"
echo "Finished with exit code: $exit_code"
echo "========================================"
echo ""

exit $exit_code
