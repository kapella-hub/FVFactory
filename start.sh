#!/bin/bash
# FVFactory — Start web server
cd "$(dirname "$0")"

source .venv/bin/activate

echo "Starting FVFactory on http://localhost:8000"
python main.py --serve
