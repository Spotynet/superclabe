#!/usr/bin/env bash
# Superclabe PRODUCTION — dedicated machine (project nginx on host :80).
#
# After merge to main: ./deploy.sh
# Optional: ./deploy.sh superclabe.example.com
# Do NOT run on the shared Spotynet multi-app EC2.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

# === Production domains (edit once) ===
SUPERCLABE_WEB_HOST="superclabe.spotynet.com"

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

if [[ "${1:-}" == "down" ]]; then
  echo "Stopping Superclabe PRODUCTION..."
  compose -f compose.yaml -f compose.prod.yaml down
  exit 0
fi

if [[ $# -ge 1 ]]; then
  SUPERCLABE_WEB_HOST="$1"
fi

export SUPERCLABE_WEB_HOST

if [[ -f VERSION ]]; then
  export APP_VERSION="$(head -n1 VERSION | tr -d '[:space:]')"
fi

if [[ ! -f .env ]]; then
  echo "Missing .env" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1091
. ./.env
set +a
case "${DATABASE_URL:-}" in
  postgres://*) DATABASE_URL="postgresql://${DATABASE_URL#postgres://}" ;;
esac
export DATABASE_URL

echo "Pulling latest from git..."
git pull --ff-only

echo "Deploying Superclabe PRODUCTION → :80..."
echo "  web: ${SUPERCLABE_WEB_HOST}"
compose -f compose.yaml -f compose.prod.yaml up -d --build
echo
compose -f compose.yaml -f compose.prod.yaml ps
echo
echo "Stop: ./deploy.sh down"
