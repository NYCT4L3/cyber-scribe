#!/usr/bin/env bash
# Launches Cyber Scribe: activates the venv, loads config from scribe.env,
# starts the Flask app, and opens it in your browser.
set -euo pipefail
cd "$(dirname "$0")"

if [ -f scribe.env ]; then
    set -a
    source scribe.env
    set +a
fi

if [ ! -d venv ]; then
    echo "No venv found. Run this first:"
    echo "  python -m venv venv && source venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi

source venv/bin/activate
echo "Starting Cyber Scribe..."
echo "Journal root: ${SCRIBE_JOURNAL_ROOT:-./journal}"
echo "Ollama model: ${OLLAMA_MODEL:-llama3.1}"

python app.py