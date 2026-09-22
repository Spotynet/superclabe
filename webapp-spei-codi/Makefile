COMPOSE = docker compose -f docker-compose.prod.yml

.PHONY: help secrets up down restart logs ps build pull backup

help:
	@echo "Objetivos disponibles:"
	@echo "  make secrets   -> genera AES_SECRET_KEY y JWT_SECRET"
	@echo "  make up        -> construye e inicia todos los servicios"
	@echo "  make down      -> detiene y elimina los contenedores"
	@echo "  make restart   -> reinicia los servicios"
	@echo "  make logs      -> sigue los logs en vivo"
	@echo "  make ps        -> estado de los servicios"
	@echo "  make backup    -> respaldo de la base de datos PostgreSQL"

secrets:
	@echo "AES_SECRET_KEY=$$(openssl rand -hex 32)"
	@echo "JWT_SECRET=$$(openssl rand -hex 32)"

up:
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

restart:
	$(COMPOSE) restart

logs:
	$(COMPOSE) logs -f

ps:
	$(COMPOSE) ps

build:
	$(COMPOSE) build

backup:
	$(COMPOSE) exec -T db pg_dump -U $${POSTGRES_USER:-superclabe} $${POSTGRES_DB:-webapp_spei} > backup_$$(date +%Y%m%d_%H%M%S).sql
	@echo "Respaldo creado."
