#!/bin/bash
# Agent Desktop Environment - Run Script
#
# Usage:
#   ./run.sh                           # Use default project (single-project mode)
#   ./run.sh /path/to/project          # Serve single project
#   ./run.sh /path/to/projects-root    # Serve multiple projects (multi-project mode)
#
# The script auto-detects whether the path is a single project or a
# multi-project root based on directory structure.

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
    echo "  (Mode will be auto-detected: single-project or multi-project)"
else
    echo "Project directory: (default)"
fi

PORT="${ADE_PORT:-9800}"
echo "Port: $PORT"
echo ""
echo "Starting Agent Desktop Environment..."
echo "Access at: http://localhost:$PORT"

exec uvicorn server.main:app --host 127.0.0.1 --port "$PORT" --reload --reload-dir server --reload-dir static
