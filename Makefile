# Makefile
.PHONY: help build up down logs shell clean

help:
	@echo "Available commands:"
	@echo "  build     - Build all Docker images"
	@echo "  up        - Start all services"
	@echo "  down      - Stop all services"
	@echo "  logs      - View logs"
	@echo "  shell     - Open shell in backend container"
	@echo "  clean     - Clean up volumes and containers"
	@echo "  restart   - Restart all services"
	@echo "  test      - Run tests"
	@echo "  production - Start in production mode"

build:
	docker-compose build

up:
	docker-compose up -d

down:
	docker-compose down

logs:
	docker-compose logs -f

shell:
	docker-compose exec backend /bin/bash

clean:
	docker-compose down -v
	docker system prune -f

restart: down up

test:
	docker-compose exec backend pytest

production:
	docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d

dev:
	docker-compose -f docker-compose.yml -f docker-compose.dev.yml up -d