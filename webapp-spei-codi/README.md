# Súper CLABE — Webapp de Cobros y Pagos SPEI / CoDi (capa no-custodia)

Webapp fullstack construida a partir del análisis de los 9 documentos de la carpeta `Origen`.
Implementa una **capa de software no-custodia** para cobros y pagos sobre los rieles del
Banco de México (SPEI, CoDi y Dimo), bajo el modelo de **Proveedor de Servicios de
Participación Indirecta (PSPI)**: el dinero viaja directo cuenta-a-cuenta entre usuarios y
la plataforma **nunca capta ni custodia fondos** (evita la clasificación como IFPE y el
capital mínimo de 5M UDIS). La única deducción es el **0.05%** de una membresía de software.

## Los 6 módulos

| # | Módulo | Función | Regulación |
|---|--------|---------|------------|
| 1 | Onboarding y KYC | Identidad única + verificación gradual (niveles 1–4) | Regla 72a |
| 2 | Bóveda bancaria | Resguardo cifrado AES-256 de la CLABE, RFC, etc. | Regla 58a |
| 3 | Cobros CoDi | Generador de **códigos QR** y Mensajes de Cobro | Apéndice AD |
| 4 | Pagos y 2FA | **Lector de QR** (cámara/imagen), enmascaramiento Dimo | Regla 71a |
| 5 | Membresía prepago | Deducción del 0.05% y bloqueo por saldo | Exclusión IFPE / LTOSF |
| 6 | Bitácoras y auditoría | Registro inmutable con hash encadenado | Regla 58a |

## Estructura

```
webapp-spei-codi/
├── docker-compose.yml          # Desarrollo: PostgreSQL + Redis + API (uvicorn --reload)
├── docker-compose.prod.yml     # Producción: + Nginx + Gunicorn (para EC2)
├── Makefile                    # make up / down / logs / secrets / backup
├── .env.example                # Plantilla de secretos (copiar a .env)
├── .gitignore  ·  .dockerignore
├── nginx/
│   └── nginx.conf              # Reverse-proxy: estático + /api + /docs
├── deploy/
│   ├── DEPLOY-AWS-EC2.md       # Guía de despliegue en EC2 (paso a paso)
│   └── ec2-user-data.sh        # Bootstrap: instala Docker en la instancia
├── frontend/
│   ├── index.html              # SPA (6 módulos, multiusuario, QR, persistencia)
│   └── config.js               # API_BASE / modo API
└── backend/
    ├── Dockerfile              # Imagen de desarrollo (uvicorn)
    ├── Dockerfile.prod         # Imagen de producción (gunicorn + healthcheck)
    ├── gunicorn_conf.py        # Workers Uvicorn, timeouts, logs
    ├── requirements.txt
    ├── init.sql                # Esquema PostgreSQL completo (users con alias $@)
    └── app/
        ├── main.py             # FastAPI + routers + frontend estático
        ├── config.py           # Variables de entorno / reglas de negocio
        ├── database.py         # SQLAlchemy (PostgreSQL o SQLite fallback)
        ├── models.py           # 8 modelos ORM (UUID portable)
        ├── schemas.py          # Contratos Pydantic
        ├── crypto.py           # AES-256, máscara CLABE, mod-10, hash-chain, PBKDF2
        ├── security.py         # JWT de sesión + 2FA TOTP
        ├── audit.py            # Escritura de bitácora encadenada
        └── routers/            # auth, kyc, vault, billing, checkout, membership, compliance
```

## Versión del sistema

Fuente de verdad: archivo `VERSION` (semver) + `frontend/version.js`.

```bash
python tools/bump_version.py              # ver versión actual
python tools/bump_version.py --patch      # 1.2.0 → 1.2.1
python tools/bump_version.py --minor      # 1.2.0 → 1.3.0
python tools/bump_version.py --major      # 1.2.0 → 2.0.0
pm2 restart superclabe-api-dev            # refrescar /api/health
```

Se muestra en el footer del menú izquierdo (`app.html`) y en el “Powered by Spotynet” de la landing.

## Documentación

- **Documentación técnica y operativa completa (vigente):** `docs/DOCUMENTACION-SISTEMA-COMPLETA.md`
- **Documento Word (portada, logo, índice, paginación):** `docs/DOCUMENTACION-SISTEMA-COMPLETA.docx`  
  (también descargable en `/docs/DOCUMENTACION-SISTEMA-COMPLETA.docx` si el API sirve el frontend)
- **Documentación técnica v1 (histórica):** `docs/DOCUMENTACION-TECNICA.md`
- **Guía de despliegue en AWS EC2:** `deploy/DEPLOY-AWS-EC2.md`

## Cómo ejecutar

### Opción A — Sólo el frontend (inmediato, sin servidor)
Abre `frontend/index.html` en el navegador. Es una demo totalmente funcional con
lógica real en el cliente (validación CLABE módulo-10, niveles KYC, cálculo del 0.05%,
bloqueo por saldo, cadena de auditoría SHA-256 verificable).

Incluye **sistema multiusuario con login** (sin contraseña por ahora): cada usuario
elige tipo de registro (Persona física o Empresa) y define un **alias único** que
siempre inicia con `$@` (puede ser su celular, p. ej. `$@5512345678`, o el alias de su
correo, p. ej. `$@juan.perez`). Cada usuario tiene su propio expediente KYC, bóveda,
cobros y saldo de membresía; los datos se conservan en el navegador para pruebas y hay
un usuario demo (`$@empresa.demo`) precargado.

### Opción B — Fullstack con Docker (API + PostgreSQL + Redis)
```bash
cd webapp-spei-codi
docker compose up --build -d
```
- API + docs interactivos (Swagger): http://localhost:8000/docs
- Frontend servido por la API: http://localhost:8000/
- Health check: http://localhost:8000/api/health

### Opción C — Backend local sin Docker
```bash
cd webapp-spei-codi/backend
pip install -r requirements.txt
# Usa SQLite por defecto; para PostgreSQL exporta DATABASE_URL
uvicorn app.main:app --reload
```

### Opción D — Producción en AWS EC2 (recomendada para publicar en web)
Stack productivo con **Nginx + Gunicorn + PostgreSQL + Redis** orquestado por
`docker-compose.prod.yml`. Nginx sirve el frontend y publica la API en el mismo origen.

```bash
cd webapp-spei-codi
cp .env.example .env      # define secretos (make secrets ayuda a generarlos)
docker compose -f docker-compose.prod.yml up -d --build   # o: make up
```
- App: `http://<IP>/`  ·  API/Swagger: `http://<IP>/docs`  ·  Health: `http://<IP>/api/health`

Guía completa de instancia, security groups, dominio y HTTPS: **`deploy/DEPLOY-AWS-EC2.md`**.
Arranque automático de la instancia: **`deploy/ec2-user-data.sh`**.

## Flujo de prueba de la API (verificado)

1. `POST /api/v1/auth/register` — crea usuario por **alias `$@...`** y tipo (Persona/Empresa), sin contraseña (KYC 1).
2. `POST /api/v1/auth/login` — inicia sesión por **alias** (sin contraseña); devuelve el JWT y el `totp_secret` (2FA) la primera vez. `GET /api/v1/auth/users` lista los alias.
3. `POST /api/v1/kyc/upgrade` — sube a Nivel 2/3/4 según documentos (Regla 72a).
4. `POST /api/v1/vault/accounts` — registra CLABE (validación módulo-10, cifrado AES-256).
5. `POST /api/v1/membership/recharge` — recarga el saldo prepago.
6. `POST /api/v1/billing/charges` — genera el cobro y su `qr_payload` (Mensaje de Cobro CoDi en QR).
7. `POST /api/v1/checkout/scan` — decodifica el contenido del QR escaneado y devuelve el checkout.
8. `GET  /api/v1/checkout/{folio}` — vista del pagador (beneficiario enmascarado + CEP).
9. `POST /api/v1/checkout/{folio}/pay` — liquida, genera clave de rastreo y deduce el 0.05%.
9. `GET  /api/v1/compliance/audit-logs/verify` — confirma la integridad de la bitácora.

## Notas de cumplimiento implementadas

- **Sin custodia de fondos**: no hay endpoints de depósito/retiro/wallet; sólo enrutamiento.
- **AES-256 en reposo** para CLABE, RFC, CURP, nombre (Regla 58a).
- **Enmascaramiento** de CLABE y beneficiario en pantalla (Regla 71a / Dimo).
- **2FA** (contraseña ≥8 + TOTP) y expiración de sesión a 20 min (Circular 9/2026).
- **0.05% al emisor**, nunca al receptor CoDi; bloqueo lógico al agotarse el saldo (LTOSF).
- **Bitácora inmutable** con hash SHA-256 encadenado y política de retención 6 meses / 1 año.
- **Máx. 3 recordatorios** de cobro por WhatsApp.

> Aviso: esta implementación es una base de desarrollo/demostración. Para operar en
> producción se requiere el patrocinio de un participante directo, HSM certificado,
> certificación en el Sandbox de Banxico (Apéndice O) y la auditoría externa (Regla 74a),
> según el roadmap de 16 semanas del documento de origen.
