#!/bin/bash
# Serves the map over localhost (needed for Safari) and opens the browser.
cd "$(dirname "$0")/docs"
PORT=8777
until lsof -i :$PORT >/dev/null 2>&1; do
  if ! pgrep -f "http.server $PORT" >/dev/null; then
    nohup python3 -m http.server $PORT >/dev/null 2>&1 &
    sleep 1
  fi
done
open "http://localhost:$PORT/index.html"
