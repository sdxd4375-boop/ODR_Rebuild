# Cold start: Postgres -> migrate -> server
docker compose -f docker-compose.dev.yml up -d postgres
do {
    Start-Sleep -Seconds 2
    $health = docker inspect --format '{{.State.Health.Status}}' odr_postgres
} until ($health -eq 'healthy')

uv run alembic upgrade head          # 存量库改：uv run alembic stamp head
python -m uvicorn server.app:app --app-dir src --port 8000