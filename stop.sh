#!/bin/bash
# FVFactory — Stop web server
PID=$(lsof -ti :8000)
if [ -z "$PID" ]; then
    echo "FVFactory is not running."
else
    kill "$PID"
    echo "FVFactory stopped (PID $PID)."
fi
