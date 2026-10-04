FROM ghcr.io/astral-sh/uv:0.12.23 AS uv
FROM python:3.12-slim-bookworm AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev --no-install-project
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev --no-editable

FROM python:3.12-slim-bookworm AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PATH="/app/.venv/bin:$PATH"
WORKDIR /app
RUN groupadd --gid 10001 tipnews && useradd --uid 10001 --gid 10001 --no-create-home tipnews \
    && install -d -o 10001 -g 10001 /app/data
COPY --from=build /app/.venv /app/.venv
COPY config ./config
COPY migrations ./migrations
COPY alembic.ini ./
USER 10001:10001
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
  CMD python -c "import pathlib,time; assert time.time()-pathlib.Path('/app/data/heartbeat').stat().st_mtime < 90"
ENTRYPOINT ["tipnews"]
CMD ["run"]
