#!/bin/bash
# Double-click launcher. Binds the panel to 127.0.0.1 only.
cd "$(dirname "$0")"

if [[ ! -x bin/minerd ]]; then
  echo "bin/minerd no está. Compilando desde el repositorio oficial de pooler..."
  ./scripts/build-minerd.sh
fi

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
fi

if lsof -nP -iTCP:8765 -sTCP:LISTEN >/dev/null 2>&1; then
  open "http://127.0.0.1:8765/"
  echo "El panel ya estaba en http://127.0.0.1:8765/"
  exit 0
fi

.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8765 &
PID=$!
trap 'kill "$PID" 2>/dev/null || true' EXIT INT TERM

for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
  if curl -fsS "http://127.0.0.1:8765/api/health" >/dev/null 2>&1; then
    open "http://127.0.0.1:8765/"
    wait "$PID"
    exit $?
  fi
  sleep 0.3
done

echo "El panel no respondió en el puerto 8765."
exit 1
