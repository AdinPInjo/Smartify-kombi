#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATUS_PATH="${REPO_ROOT}/smartify/data/db_integrity_status.json"

# Attempt to read DB_PATH from config; fall back to default path.
DB_PATH="$(
  python3 - <<'PY' 2>/dev/null | tail -n 1
from smartify.config import DB_PATH
print(DB_PATH)
PY
)"

if [ -z "${DB_PATH:-}" ]; then
  DB_PATH="${REPO_ROOT}/smartify/data/smartify.db"
fi

STATUS="ok"
MESSAGE="ok"
RESULT=""

if [ ! -f "$DB_PATH" ]; then
  STATUS="error"
  MESSAGE="DB file not found"
  RESULT="DB file not found at ${DB_PATH}"
else
  RESULT="$(sqlite3 "$DB_PATH" "PRAGMA integrity_check;" || true)"
  if [ "$RESULT" != "ok" ]; then
    STATUS="error"
    MESSAGE="integrity_check failed"
  fi
fi

export STATUS MESSAGE RESULT DB_PATH STATUS_PATH
python3 - <<'PY'
import json
import os
import time

status = os.environ.get("STATUS", "unknown")
message = os.environ.get("MESSAGE", "")
result = os.environ.get("RESULT", "")
db_path = os.environ.get("DB_PATH", "")
status_path = os.environ.get("STATUS_PATH", "")
now = int(time.time())

payload = {
    "status": status,
    "message": message,
    "result": result,
    "db_path": db_path,
    "last_run_ts": now,
}

if status_path:
    with open(status_path, "w", encoding="utf-8") as f:
        json.dump(payload, f)
PY

if [ "$STATUS" != "ok" ]; then
  echo "[DB Integrity] FAILED: ${RESULT}"
  exit 2
fi

echo "[DB Integrity] ok"
