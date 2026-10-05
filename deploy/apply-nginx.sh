#!/usr/bin/env bash
# Point Superclabe host-nginx vhost at project Compose nginx gateway (3024).
# Usage: sudo ./deploy/apply-nginx.sh
set -euo pipefail

CONF=/etc/nginx/sites-available/spotynet-dev.conf
BAK="${CONF}.bak.$(date +%F-%H%M%S)"
GATEWAY=3024

if [[ $EUID -ne 0 ]]; then
  echo "Run with sudo: sudo $0" >&2
  exit 1
fi

cp -a "$CONF" "$BAK"
echo "Backup: $BAK"

python3 - "$CONF" "$GATEWAY" <<'PY'
import re
import sys

path, gateway = sys.argv[1], sys.argv[2]
text = open(path, encoding="utf-8").read()

def patch_server(text: str, server_name: str, new_port: str) -> str:
    pattern = re.compile(
        rf"(server_name\s+{re.escape(server_name)}\s*;.*?proxy_pass\s+http://127\.0\.0\.1:)\d+(\s*;)",
        re.DOTALL,
    )
    new_text, n = pattern.subn(rf"\g<1>{new_port}\2", text, count=1)
    if n != 1:
        raise SystemExit(f"Expected 1 proxy_pass for {server_name}, found {n}")
    return new_text

text = patch_server(text, "superclabe-dev.spotynet.com", gateway)
open(path, "w", encoding="utf-8").write(text)
print(f"Updated superclabe-dev.spotynet.com proxy_pass → 127.0.0.1:{gateway}")
PY

nginx -t
systemctl reload nginx
echo "nginx reloaded OK"

SETUP=/home/spotynet/projects/apps/setup.txt
if [[ -f "$SETUP" ]]; then
  echo "==> Updating setup.txt SUPERCLABE section"
  cp -a "$SETUP" "${SETUP}.bak.$(date +%F-%H%M%S)"
  python3 - "$SETUP" <<'PY'
from pathlib import Path
import re
import sys
path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
new = """SUPERCLABE (Docker Compose — per-project nginx)
- Start: cd /home/spotynet/projects/apps/superclabe && ./dev.sh
- Project nginx gateway: 127.0.0.1:3024
- FastAPI serves UI + API (internal): 3017 — superclabe-dev.spotynet.com
- Host nginx proxies superclabe-dev.spotynet.com to http://127.0.0.1:3024
- Apply host nginx: sudo ./deploy/apply-nginx.sh
"""
pat = re.compile(r"SUPERCLABE\n(?:- .+\n)+")
pat2 = re.compile(r"SUPERCLABE \(Docker Compose — per-project nginx\)\n(?:- .+\n)+")
# Also match older SUPERCLABE-W adjacent heading confusion — only replace SUPERCLABE (not -W)
if pat2.search(text):
    text2, n = pat2.subn(new + "\n", text, count=1)
elif pat.search(text):
    text2, n = pat.subn(new + "\n", text, count=1)
else:
    n = 0
    text2 = text
if n:
    path.write_text(text2, encoding="utf-8")
    print("Updated setup.txt SUPERCLABE section")
else:
    print("Warning: setup.txt SUPERCLABE section not replaced")
PY
fi

echo
echo "Verify:"
echo "  curl -sI -H 'Host: superclabe-dev.spotynet.com' http://127.0.0.1:3024/ | head -5"
echo "  curl -s -H 'Host: superclabe-dev.spotynet.com' http://127.0.0.1:3024/api/health"
