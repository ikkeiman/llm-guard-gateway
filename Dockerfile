FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_LINK_MODE=copy
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /uvx /bin/
WORKDIR /app
# 依存だけ先に入れてキャッシュを効かせる。GiNZA（Stage 2）を含めるので数百 MB になる
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --extra ner --no-install-project
COPY . .
RUN uv sync --frozen --no-dev --extra ner
EXPOSE 8000
CMD ["uv", "run", "--no-sync", "uvicorn", "llm_guard.main:app", "--host", "0.0.0.0", "--port", "8000"]
