#!/bin/bash

echo "🚀 Starting SUPERCLABE DEV (api + frontend)"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/backend"
VENV_PY="$BACKEND_DIR/venv/bin/python"

APP_NAME="superclabe-api-dev"
PORT=3017
HOST=127.0.0.1

# -------------------------
# 🌿 Load environment
# -------------------------
if [ ! -f "$SCRIPT_DIR/.env" ]; then
  echo "❌ Missing $SCRIPT_DIR/.env (copy from .env.example and set DATABASE_URL)"
  exit 1
fi
set -a
# shellcheck disable=SC1091
. "$SCRIPT_DIR/.env"
set +a

if [ ! -x "$VENV_PY" ]; then
  echo "❌ Missing venv python: $VENV_PY"
  echo "   Create it: python3 -m venv --without-pip backend/venv && backend/venv/bin/pip install -r backend/requirements.txt"
  exit 1
fi

# SQLAlchemy 2 no longer accepts the legacy postgres:// scheme
case "$DATABASE_URL" in
  postgres://*) DATABASE_URL="postgresql://${DATABASE_URL#postgres://}" ;;
esac
export DATABASE_URL AES_SECRET_KEY JWT_SECRET JWT_EXPIRE_MIN SEED_DEMO_USERS

# -------------------------
# 🧹 Clean old process
# -------------------------
echo "🧹 Cleaning old PM2 process..."
pm2 delete $APP_NAME 2>/dev/null

# -------------------------
# 🐍 Start FastAPI (uvicorn)
# -------------------------
echo "🐍 Starting FastAPI ($APP_NAME) on $HOST:$PORT..."
pm2 start "$VENV_PY" \
  --name "$APP_NAME" \
  --cwd "$BACKEND_DIR" \
  -- -m uvicorn app.main:app --host "$HOST" --port "$PORT"

# -------------------------
# 💾 Save PM2 state
# -------------------------
pm2 save

# -------------------------
# 📊 Status
# -------------------------
echo "✅ SUPERCLABE DEV running:"
pm2 list
echo ""
echo "  superclabe-dev -> https://superclabe-dev.spotynet.com  (localhost:$PORT)"
echo "                  http://$HOST:$PORT"
