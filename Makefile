PY=python3
PIP=pip3

.PHONY: install dev qdrant-up qdrant-down run-app-backend run-app-frontend stop-app-backend docker-up docker-down docker-logs

install:
	$(PIP) install -e .

dev:
	$(PIP) install -e .[dev]

run-app-frontend:
	cd app/frontend && npm install && npm run dev

run-app-backend:
	 cd app/backend && uv run --active uvicorn app.main:app --reload --port 8002

stop-app-backend:
	 -pkill -f "uvicorn app.main:app --reload --port 8002" || true
	 -lsof -t -i:8002 | xargs kill -9 || true

qdrant-up:
	docker compose -f docker/docker-compose.qdrant.yaml up -d

qdrant-down:
	docker compose -f docker/docker-compose.qdrant.yaml down --remove-orphans

docker-up:
	docker compose up -d --build

docker-down:
	docker compose down

docker-logs:
	docker compose logs -f backend frontend db
