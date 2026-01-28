#!/bin/sh
set -e

DB_PATH="/app/data/wearai.db"

mkdir -p /app/data
if [ ! -f "$DB_PATH" ]; then
  touch "$DB_PATH"
fi

exec python main.py
