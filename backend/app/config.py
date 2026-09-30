"""Configuración central de la Webapp SPEI/CoDi (capa no-custodia).

Todas las variables sensibles se leen de entorno para no exponer secretos
en el código (Regla 58a - manejo seguro de datos).
"""

# SC-DEV-SIG-v1: kKWdBcNGvWSeuUiwNlOW1biXPN_20-JUxGWAqwu0egb62URJ9-m60dl1lECksig-gk1MDIxO_gQ8qKbicWdkPHFpReWQfXst6kHO5To13Z7HMafaSWautap4j9oHkPFGHkmtUWaw_INswQ==
# (firma de autoría cifrada AES-256-GCM — verificar con tools/verify_dev_signature.py)
import os


class Settings:
    # Base de datos. Por defecto SQLite para que el proyecto arranque sin
    # infraestructura; en producción/Docker se usa PostgreSQL.
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL", "sqlite:///./webapp_spei.db"
    )

    # Llave de cifrado AES-256 (32 bytes). En producción proviene de un HSM.
    # Se acepta hex de 64 chars o texto; se normaliza a 32 bytes.
    AES_SECRET_KEY: str = os.getenv(
        "AES_SECRET_KEY",
        "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    )

    # Firma de tokens JWT de sesión.
    JWT_SECRET: str = os.getenv("JWT_SECRET", "dev-jwt-secret-cambiar-en-produccion")
    JWT_ALG: str = "HS256"
    JWT_EXPIRE_MIN: int = int(os.getenv("JWT_EXPIRE_MIN", "20"))  # Regla 71a: inactividad 20 min
    ADMIN_JWT_EXPIRE_MIN: int = int(os.getenv("ADMIN_JWT_EXPIRE_MIN", "30"))

    # Reglas de negocio
    # Modelo de negocio v5: tarifas escalonadas por monto de la operación.
    # La tasa del rango aplica sobre el monto completo (no es marginal).
    # Un monto pertenece al último rango cuyo "min" sea <= monto.
    FEE_MODEL_VERSION: str = "v5"
    FEE_TIERS = [
        {"min": 0.00, "max": 999.99, "rate": 0.0100,
         "segment": "Micro-comercio informal, taxis, tienditas"},
        {"min": 1000.00, "max": 9999.99, "rate": 0.0083,
         "segment": "Comercio medio B2B, restaurantes y proveedores"},
        {"min": 10000.00, "max": None, "rate": 0.0050,
         "segment": "Corporativos medianos e integraciones API"},
    ]
    IVA_RATE: float = 0.16                # 16% IVA sobre la tarifa de software
    MAX_WHATSAPP_REMINDERS: int = 3       # Máximo 3 recordatorios por cobro
    SESSION_TIMEOUT_MIN: int = 20         # Cierre por inactividad (Circular 9/2026)

    # Límites mensuales KYC en UDIS (Regla 72a)
    KYC_LIMITS_UDIS = {1: 0, 2: 3000, 3: 8000, 4: None}  # None = sin límite


settings = Settings()
