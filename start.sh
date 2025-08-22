#!/usr/bin/env sh
set -e
echo "Starting GlassServer on port "
exec uvicorn main:app --host 0.0.0.0 --port  --log-level info
