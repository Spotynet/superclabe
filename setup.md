# Superclabe — Setup & Use Guide

FastAPI serves the static UI and `/api/` on the same origin. Jay-style Compose.  
Company playbook: [`../setup.md`](../setup.md).

## Architecture (shared EC2)

```text
Browser → host nginx :443
  → 127.0.0.1:3024 (project nginx)
       └─ superclabe-dev.spotynet.com → backend:3017
            (StaticFiles + /api/*)
```

| | Value |
|--|--------|
| Gateway | `127.0.0.1:3024` |
| Internal | FastAPI `3017` |
| Dev domain | `superclabe-dev.spotynet.com` (set in `dev.sh`) |
| DB | RDS via root `.env` (`DATABASE_URL`) — no compose Postgres on shared EC2 |

## One-time on this machine

1. Root `.env` with `DATABASE_URL`, `AES_SECRET_KEY`, `JWT_SECRET`, …
2. **Host nginx:** `sudo ./deploy/apply-nginx.sh`
3. **Start:** `./dev.sh`

## Day-to-day

```bash
./dev.sh
docker compose -f compose.yaml logs -f
docker compose -f compose.yaml down
```

URL: `https://superclabe-dev.spotynet.com/`

## Production (dedicated machine)

```bash
./deploy.sh                           # default: superclabe.spotynet.com on :80
./deploy.sh superclabe.example.com
./deploy.sh down
```

Legacy `docker-compose*.yml` (+ local Postgres/Redis) remains for standalone demos; shared EC2 uses `compose.yaml` + RDS.
