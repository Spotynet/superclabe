#!/usr/bin/env bash
# Superclabe DEVELOPMENT — shared EC2 (project nginx on 127.0.0.1:3024).
#
# Once: sudo ./deploy/apply-nginx.sh
# Day-to-day: ./dev.sh
# Prod (dedicated): ./deploy.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

# === Dev domains (committed) ===
SUPERCLABE_WEB_HOST="superclabe-dev.spotynet.com"

export SUPERCLABE_WEB_HOST

if [[ -f VERSION ]]; then
  export APP_VERSION="$(head -n1 VERSION | tr -d '[:space:]')"
fi

compose() {
  if docker info >/dev/null 2>&1; then
    docker compose "$@"
  elif sudo -n docker info >/dev/null 2>&1; then
    sudo docker compose "$@"
  else
    echo "Docker needs privileges. Prefer: sudo usermod -aG docker \$USER && newgrp docker" >&2
    sudo docker compose "$@"
  fi
}

if [[ ! -f .env ]]; then
  echo "Missing .env (copy from .env.example and set DATABASE_URL, AES_SECRET_KEY, JWT_SECRET, …)" >&2
  exit 1
fi

# SQLAlchemy 2 rejects legacy postgres:// — normalize if present in .env / shell
set -a
# shellcheck disable=SC1091
. ./.env
set +a
case "${DATABASE_URL:-}" in
  postgres://*) DATABASE_URL="postgresql://${DATABASE_URL#postgres://}" ;;
esac
export DATABASE_URL

echo "Cleaning old Superclabe PM2 processes (if any)..."
pm2 delete superclabe-api-dev 2>/dev/null || true
pm2 save 2>/dev/null || true

echo "Starting Superclabe DEV (compose.yaml → 127.0.0.1:3024)..."
echo "  web: ${SUPERCLABE_WEB_HOST}"
compose -f compose.yaml up -d --build
echo
compose -f compose.yaml ps
echo
echo "DEV URL: https://${SUPERCLABE_WEB_HOST}/"
echo
echo "Logs: docker compose -f compose.yaml logs -f"
echo "Stop: docker compose -f compose.yaml down"
echo
echo "If host nginx still points at 3017:"
echo "  sudo ./deploy/apply-nginx.sh"
