# Firma de autoría oculta (SC-DEV-SIG-v1)

Cada módulo del sistema incluye un comentario cifrado `SC-DEV-SIG-v1` con la
reclamación de autoría del desarrollo. El texto en claro **no** aparece en el
código; solo el ciphertext AES-256-GCM.

## Qué protege

- Evidencia técnica de autoría embebida en el código fuente.
- Verificable en auditorías exhaustivas con la contraseña externa.
- No sustituye por sí sola un registro de patente/derecho de autor; es un
  refuerzo técnico de trazabilidad.

## Dónde está

- Comentarios `SC-DEV-SIG-v1` en routers, núcleo backend y frontend.
- Registro de firmas (solo ciphertext): `docs/dev-signatures.registry.json`
- Verificador: `tools/verify_dev_signature.py`

## Cómo verificar

```bash
cd webapp-spei-codi
export SC_DEV_SIG_PASS='<contraseña guardada externamente>'
backend/venv/bin/python tools/verify_dev_signature.py
```

Si la contraseña es correcta, cada módulo descifrará:

`Desarrollado por Christian David Torres Parra | Súper CLABE | módulo: <nombre>`

## Contraseña

La contraseña **no** se almacena en el repositorio. Debe guardarse fuera del
código (gestor de secretos, archivo cifrado personal, notaría, etc.).

Algoritmo: `AES-256-GCM` · clave = `SHA-256(utf-8 passphrase)` · AAD = `superclabe-dev-sig-v1`
