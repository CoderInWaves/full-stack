.PHONY: up down build test integration-test frontend-test load-test clean logs dev-backend dev-demo dev-frontend

up:
	docker compose up -d

down:
	docker compose down

build:
	docker compose build

test:
	cd backend && ../venv/bin/pytest tests/unit/ -v

integration-test:
	cd backend && ../venv/bin/pytest tests/integration/ tests/concurrency/ -v

frontend-test:
	cd frontend && npm run test

load-test:
	k6 run loadtests/rate_limiter.js

clean:
	docker compose down -v --remove-orphans
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true

logs:
	docker compose logs -f

dev-backend:
	cd backend && ../venv/bin/uvicorn app.main:app --reload --port 8000

dev-demo:
	cd backend && ../venv/bin/uvicorn demo_backend:app --reload --port 8001

dev-frontend:
	cd frontend && npm run dev
