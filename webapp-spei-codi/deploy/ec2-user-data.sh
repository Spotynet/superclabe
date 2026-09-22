#!/bin/bash
# ============================================================================
# Script de arranque (User Data) para una instancia EC2 con Ubuntu 22.04 LTS.
# Instala Docker + Docker Compose y prepara el entorno de Súper CLABE.
# Pégalo en "Advanced details > User data" al lanzar la instancia, o ejecútalo
# manualmente tras conectarte por SSH.
# ============================================================================
set -euxo pipefail

# --- 1. Dependencias base ---
apt-get update -y
apt-get install -y ca-certificates curl gnupg git

# --- 2. Repositorio oficial de Docker ---
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  > /etc/apt/sources.list.d/docker.list

# --- 3. Instalar Docker Engine + Compose plugin ---
apt-get update -y
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker
usermod -aG docker ubuntu || true

# --- 4. Preparar carpeta del proyecto ---
mkdir -p /opt/superclabe
chown -R ubuntu:ubuntu /opt/superclabe

cat <<'EOF' > /opt/superclabe/SIGUIENTE-PASO.txt
Docker ya está instalado. Ahora:

1) Copia el proyecto a /opt/superclabe  (elige UNA opción):
   a) Con git:   git clone <TU_REPO> /opt/superclabe
   b) Con scp:   desde tu máquina ->
        scp -i tu-llave.pem -r ./webapp-spei-codi/* ubuntu@<IP_PUBLICA>:/opt/superclabe/

2) Configura los secretos:
        cd /opt/superclabe
        cp .env.example .env
        # genera secretos:  openssl rand -hex 32   (para AES_SECRET_KEY y JWT_SECRET)
        nano .env

3) Levanta el sistema:
        docker compose -f docker-compose.prod.yml up -d --build

4) Verifica:
        docker compose -f docker-compose.prod.yml ps
        curl http://localhost/api/health

La app quedará en  http://<IP_PUBLICA>/   y la API en  http://<IP_PUBLICA>/docs
EOF

echo "Bootstrap EC2 completado. Ver /opt/superclabe/SIGUIENTE-PASO.txt"
