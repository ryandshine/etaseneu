#!/bin/bash
set -e

# Ensure WeasyPrint system deps are present (survives Dokploy restarts without rebuild)
if ! ldconfig -p 2>/dev/null | grep -q "libgobject-2.0"; then
    echo "[entrypoint] Installing WeasyPrint system dependencies..."
    apt-get update -qq && apt-get install -y -qq \
        libgobject-2.0-0 libglib2.0-0 libpango-1.0-0 libpangocairo-1.0-0 \
        libpangoft2-1.0-0 libgdk-pixbuf-2.0-0 libffi8 \
        shared-mime-info fonts-dejavu-core \
        && rm -rf /var/lib/apt/lists/*
    echo "[entrypoint] Done."
fi

exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
