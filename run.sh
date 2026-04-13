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

exec uvicorn server.main:app --host 127.0.0.1 --port 9800 --reload --reload-dir server --reload-dir static
