# syntax=docker/dockerfile:1.7
FROM ghcr.io/astral-sh/uv:0.8.14 AS uv

FROM python:3.12.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/app/.venv/bin:${PATH}

RUN groupadd --gid 11000 thesistrace-cache \
    && groupadd --gid 10001 thesistrace-api \
    && groupadd --gid 10005 thesistrace-storage \
    && groupadd --gid 10006 thesistrace-egress \
    && useradd --uid 10001 --gid thesistrace-api --create-home thesistrace-api \
    && useradd --uid 10005 --gid thesistrace-storage --create-home thesistrace-storage \
    && useradd --uid 10006 --gid thesistrace-egress --create-home thesistrace-egress \
    && usermod --append --groups thesistrace-cache thesistrace-api

WORKDIR /app
COPY --from=uv /uv /uvx /bin/
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY deploy/hosted/migrations ./deploy/hosted/migrations
COPY scripts/hosted/configure_smtp.py ./scripts/hosted/configure_smtp.py
RUN uv sync --frozen --no-dev \
    && mkdir -p /var/lib/thesistrace /tmp/thesistrace \
    && chown -R thesistrace-api:thesistrace-api /var/lib/thesistrace /tmp/thesistrace

USER 10001:10001
ENTRYPOINT []
CMD ["thesistrace-api"]
