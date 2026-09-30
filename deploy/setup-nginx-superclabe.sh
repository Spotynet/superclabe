#!/usr/bin/env bash
# Adds superclabe-dev.spotynet.com → 127.0.0.1:3017 to host nginx, tests, reloads.
# Usage: sudo ./deploy/setup-nginx-superclabe.sh
set -euo pipefail

CONF=/etc/nginx/sites-available/spotynet-dev.conf
BAK="${CONF}.bak.$(date +%F-%H%M%S)"

if [[ $EUID -ne 0 ]]; then
  echo "Run with sudo: sudo $0" >&2
  exit 1
fi

cp -a "$CONF" "$BAK"
echo "Backup: $BAK"

if grep -q 'server_name superclabe-dev.spotynet.com' "$CONF"; then
  echo "superclabe-dev block already present — skipping insert"
else
  python3 - "$CONF" <<'PY'
import sys

path = sys.argv[1]
block = """
# =========================
# SUPERCLABE
# =========================

# Superclabe app (FastAPI serves frontend + API on same origin)
server {
    server_name superclabe-dev.spotynet.com;

    location / {
        proxy_pass http://127.0.0.1:3017;
        proxy_http_version 1.1;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    listen 80;
    listen [::]:80;
}
"""

text = open(path).read()
marker = "if ($host ="
idx = text.find(marker)
if idx < 0:
    text = text.rstrip() + "\n" + block
    print("Appended superclabe-dev block at end of file")
else:
    start = text.rfind("server {", 0, idx)
    if start < 0:
        start = idx
    text = text[:start] + block.lstrip("\n") + "\n" + text[start:]
    print("Inserted superclabe-dev block before first Certbot HTTP redirect block")
open(path, "w").write(text)
PY
fi

nginx -t
systemctl reload nginx
echo "nginx reloaded OK"
echo
echo "Next (after DNS A record exists):"
echo "  sudo certbot --nginx -d superclabe-dev.spotynet.com --redirect"
