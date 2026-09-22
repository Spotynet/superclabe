# Despliegue de Súper CLABE en AWS EC2

Guía paso a paso para publicar el sistema (frontend + API FastAPI + PostgreSQL + Redis)
en una instancia EC2, usando Docker Compose y Nginx como reverse-proxy.

## Arquitectura desplegada

```
                    ┌──────────────────────── EC2 (Ubuntu 22.04) ─────────────────────────┐
   Internet  :80    │                                                                      │
  ───────────────▶  │  Nginx  ──/──────────▶  frontend (index.html, SPA estática)          │
                    │         ──/api/──────▶  backend  (FastAPI + Gunicorn/Uvicorn :8000)   │
                    │                              │                                        │
                    │                              ├──▶ PostgreSQL 16  (volumen persistente)│
                    │                              └──▶ Redis 7.2       (sesiones / rate)    │
                    └──────────────────────────────────────────────────────────────────────┘
```

Todo corre en contenedores orquestados por `docker-compose.prod.yml`. Solo el puerto 80
(y 443 si habilitas HTTPS) queda expuesto a Internet; la base de datos y la API no se
publican directamente.

---

## 1. Requisitos previos

- Una cuenta de AWS con permisos para lanzar instancias EC2.
- Un par de llaves SSH (`.pem`) para conectarte.
- (Opcional) Un dominio propio si quieres HTTPS con certificado.

## 2. Lanzar la instancia EC2

1. **AMI:** Ubuntu Server 22.04 LTS (x86_64).
2. **Tipo:** `t3.small` o superior (2 GB RAM mínimo recomendado; `t2.micro` funciona para pruebas ligeras).
3. **Almacenamiento:** 20 GB gp3.
4. **Security Group (firewall):** abre estos puertos de entrada:
   - `22/tcp` (SSH) — idealmente solo tu IP.
   - `80/tcp` (HTTP) — `0.0.0.0/0`.
   - `443/tcp` (HTTPS) — `0.0.0.0/0` (si usarás TLS).
5. **User data (opcional):** pega el contenido de `deploy/ec2-user-data.sh` para que Docker
   se instale solo al arrancar.

## 3. Instalar Docker (si no usaste user-data)

Conéctate y ejecuta el script:

```bash
ssh -i tu-llave.pem ubuntu@<IP_PUBLICA>
sudo bash ec2-user-data.sh      # o copia/pega los comandos del script
# cierra y reabre la sesión SSH para aplicar el grupo docker
```

## 4. Subir el proyecto a la instancia

Elige **una** opción:

**a) Con git** (si el código está en un repositorio):
```bash
git clone <TU_REPO> /opt/superclabe
```

**b) Con scp** (desde tu computadora, en la carpeta que contiene `webapp-spei-codi`):
```bash
scp -i tu-llave.pem -r ./webapp-spei-codi/* ubuntu@<IP_PUBLICA>:/opt/superclabe/
```

## 5. Configurar secretos

```bash
cd /opt/superclabe
cp .env.example .env
# Genera dos secretos fuertes:
openssl rand -hex 32   # úsalo para AES_SECRET_KEY
openssl rand -hex 32   # úsalo para JWT_SECRET
nano .env              # pega los valores y una contraseña fuerte para POSTGRES_PASSWORD
```

> Atajo: `make secrets` imprime ambos secretos listos para copiar.

## 6. Levantar el sistema

```bash
docker compose -f docker-compose.prod.yml up -d --build
# o simplemente:  make up
```

Verifica:

```bash
docker compose -f docker-compose.prod.yml ps      # todos "running/healthy"
curl http://localhost/api/health                  # {"status":"ok",...}
```

Abre en el navegador:
- **App:** `http://<IP_PUBLICA>/`
- **API / Swagger:** `http://<IP_PUBLICA>/docs`

## 6.1 Migración de esquema (BD PostgreSQL existente)

En una instalación **nueva** no hace falta: `init.sql` ya crea el esquema completo.
Sólo se requiere al **actualizar** una base con datos previos (p. ej. para incorporar
las funciones de QR de cobro CoDi: monto libre, cobros personalizados, número de usos,
etiqueta "Pagar a:" y favoritos). La migración es **idempotente** (segura de re-ejecutar)
y **no destruye datos**.

**Opción A — SQL declarativo (recomendado en producción):**

```bash
# Carga las variables POSTGRES_* del .env y aplica la migración dentro del contenedor db
set -a; . ./.env; set +a
docker compose -f docker-compose.prod.yml exec -T db \
  psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" < backend/migrations/001_codi_qr_features.sql
```

**Opción B — runner Python multi-dialecto** (útil en dev SQLite o si prefieres Python):

```bash
docker compose -f docker-compose.prod.yml exec api python migrate.py --check   # sólo reporta
docker compose -f docker-compose.prod.yml exec api python migrate.py           # aplica
```

Verifica que la columna `amount` admita NULL y que exista la tabla `favorites`:

```bash
docker compose -f docker-compose.prod.yml exec -T db \
  psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "\d charges" -c "\d favorites"
```

> Haz un respaldo antes (`make backup` o `pg_dump`). Reinicia la API tras migrar:
> `docker compose -f docker-compose.prod.yml restart api`.

## 7. (Opcional) HTTPS con dominio propio

1. Apunta un registro **A** de tu dominio a la IP pública de la instancia.
2. La forma más simple: instalar Certbot en el host y un Nginx del host, o usar un
   contenedor `nginx-proxy` + `acme-companion`. Alternativa rápida con Certbot standalone:

```bash
sudo apt-get install -y certbot
docker compose -f docker-compose.prod.yml stop nginx
sudo certbot certonly --standalone -d tudominio.com
# copia los certificados a ./nginx/certs y añade el bloque server 443 en nginx.conf
docker compose -f docker-compose.prod.yml up -d
```

3. En `nginx.conf` agrega un `server { listen 443 ssl; ... ssl_certificate ...; }` y
   redirige 80 → 443. Descomenta el puerto `443` y el montaje `./nginx/certs` en
   `docker-compose.prod.yml`.

## 8. Operación

| Acción | Comando |
|--------|---------|
| Ver logs | `make logs` (o `docker compose -f docker-compose.prod.yml logs -f`) |
| Estado | `make ps` |
| Reiniciar | `make restart` |
| Detener | `make down` |
| Actualizar código | `git pull` (o re-scp) y `make up` |
| Respaldo de BD | `make backup` |

## 9. Notas de seguridad y cumplimiento

- Cambia **todos** los secretos de `.env.example` antes de exponer a Internet.
- Restringe el puerto 22 a tu IP; considera AWS Systems Manager Session Manager en vez de SSH abierto.
- Habilita HTTPS (paso 7) antes de manejar datos reales — la Regla 58a exige canales cifrados.
- En producción real, la `AES_SECRET_KEY` debe residir en un **HSM/KMS** (p. ej. AWS KMS),
  no en un archivo `.env`. Este stack es la base técnica; la certificación ante Banxico
  (Sandbox, Apéndice O y auditoría Regla 74a) es un paso posterior.
- Programa respaldos automáticos del volumen `postgres_data` (snapshots EBS o `pg_dump` a S3).

## 10. Solución de problemas

- **La app no carga:** revisa `make logs`; confirma que `nginx` y `backend` están `running`.
- **502 Bad Gateway:** el backend aún inicia o falló; `docker compose ... logs backend`.
- **La BD no arranca:** verifica que `POSTGRES_PASSWORD` esté definido en `.env`.
- **Cambié `.env` y no aplica:** `make down && make up` para recrear contenedores.
