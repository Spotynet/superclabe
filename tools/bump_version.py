#!/usr/bin/env python3
"""Actualiza la versión del sistema (VERSION + frontend/version.js + referencia).

Uso:
  python tools/bump_version.py              # muestra versión actual
  python tools/bump_version.py --patch      # 1.2.0 -> 1.2.1
  python tools/bump_version.py --minor      # 1.2.0 -> 1.3.0
  python tools/bump_version.py --major      # 1.2.0 -> 2.0.0
  python tools/bump_version.py --set 1.4.0  # fija versión
"""
from __future__ import annotations

import argparse
import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = ROOT / "VERSION"
VERSION_JS = ROOT / "frontend" / "version.js"


def read_version() -> str:
    return VERSION_FILE.read_text(encoding="utf-8").strip().splitlines()[0].strip()


def bump(ver: str, part: str) -> str:
    major, minor, patch = (int(x) for x in ver.split("."))
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def write_all(ver: str) -> None:
    build = date.today().strftime("%Y.%m.%d")
    VERSION_FILE.write_text(ver + "\n", encoding="utf-8")
    VERSION_JS.write_text(
        f"""/* Fuente de verdad de versión del frontend.
   Sincronizar con /VERSION vía: python tools/bump_version.py [--patch|--minor|--major] */
window.SUPERCLABE_VERSION = {{
  version: "{ver}",
  build: "{build}",
  name: "Súper CLABE",
  label: function () {{
    return "v" + this.version;
  }},
  poweredLine: function () {{
    return "Powered by Spotynet · " + this.label();
  }},
}};
""",
        encoding="utf-8",
    )
    print(f"OK → {ver} (build {build})")
    print(f"  - {VERSION_FILE.relative_to(ROOT)}")
    print(f"  - {VERSION_JS.relative_to(ROOT)}")
    print("Reinicia la API (pm2 restart superclabe-api-dev) para exponer la versión en /api/health.")


def main() -> int:
    ap = argparse.ArgumentParser(description="Bump de versión Súper CLABE")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--patch", action="store_true")
    g.add_argument("--minor", action="store_true")
    g.add_argument("--major", action="store_true")
    g.add_argument("--set", metavar="X.Y.Z")
    args = ap.parse_args()

    current = read_version()
    if not re.fullmatch(r"\d+\.\d+\.\d+", current):
        raise SystemExit(f"VERSION inválida: {current!r}")

    if args.set:
        if not re.fullmatch(r"\d+\.\d+\.\d+", args.set):
            raise SystemExit("--set requiere formato X.Y.Z")
        write_all(args.set)
        return 0
    if args.major:
        write_all(bump(current, "major"))
        return 0
    if args.minor:
        write_all(bump(current, "minor"))
        return 0
    if args.patch:
        write_all(bump(current, "patch"))
        return 0

    print(f"Versión actual: {current}")
    print("Usa --patch | --minor | --major | --set X.Y.Z para actualizar.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
