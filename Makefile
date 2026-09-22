.PHONY: up down migrate seed api front test worker

up:
	docker compose up -d

down:
	docker compose down

migrate:
	cd backend && . .venv/bin/activate && alembic upgrade head

seed:
	cd backend && . .venv/bin/activate && python -m app.seed

api:
	cd backend && . .venv/bin/activate && uvicorn app.main:app --reload --port 8002

front:
	cd frontend && npm run dev

worker:
	cd backend && . .venv/bin/activate && rq worker oficinaflow-billing --url redis://localhost:6383/0

test:
	cd backend && . .venv/bin/activate && pytest -q
