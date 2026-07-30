# syntax=docker/dockerfile:1.7
FROM ghcr.io/astral-sh/uv:0.8.14 AS uv

FROM python:3.12.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/app/.venv/bin:${PATH}

RUN groupadd --gid 10001 thesistrace \
    && useradd --uid 10001 --gid thesistrace --create-home thesistrace

WORKDIR /app
COPY --from=uv /uv /uvx /bin/
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY deploy/hosted/migrations ./deploy/hosted/migrations
RUN uv sync --frozen --no-dev \
    && mkdir -p /var/lib/thesistrace /tmp/thesistrace \
    && chown -R thesistrace:thesistrace /var/lib/thesistrace /tmp/thesistrace

USER 10001:10001
ENTRYPOINT []
CMD ["thesistrace-api"]
