#!/bin/bash
cd "$(dirname "$0")"

if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
else
    source venv/bin/activate
fi

# Accept project directory as argument or use ADE_PROJECT_DIR env var
if [ -n "$1" ]; then
    export ADE_PROJECT_DIR="$(realpath "$1")"
fi

if [ -n "$ADE_PROJECT_DIR" ]; then
    echo "Project directory: $ADE_PROJECT_DIR"
else
    echo "Project directory: (default)"
fi

PORT="${ADE_PORT:-9800}"
echo "Port: $PORT"

exec uvicorn server.main:app --host 127.0.0.1 --port "$PORT" --reload --reload-dir server --reload-dir static
