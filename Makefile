.PHONY: up down logs test api worker web

export PYTHONPATH := $(CURDIR)/api

up:
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f --tail=100

test:
	EMBEDDING_PROVIDER=hash pytest

api:
	uvicorn archive_workbench.main:app --host 0.0.0.0 --port 8000

worker:
	python -m archive_workbench.worker

web:
	cd web && npm run dev
