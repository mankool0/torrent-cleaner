#!/bin/bash

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
