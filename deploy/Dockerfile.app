# api/worker 共用镜像（技术方案 §16）：不同 command 启动
FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY apps/api apps/api
COPY apps/worker apps/worker
COPY packages packages
COPY migrations migrations
COPY scripts scripts
COPY alembic.ini ./
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"

# api:    uvicorn api.main:app --host 0.0.0.0 --port 8000
# worker: arq worker.main.WorkerSettings
# migrate: alembic upgrade head
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
