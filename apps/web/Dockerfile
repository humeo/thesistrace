FROM node:24.14.0-bookworm-slim@sha256:d8e448a56fc63242f70026718378bd4b00f8c82e78d20eefb199224a4d8e33d8 AS build

WORKDIR /app
RUN corepack enable && corepack prepare pnpm@11.9.0 --activate

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY tooling/patches ./tooling/patches
COPY apps/auth/package.json ./apps/auth/package.json
COPY apps/agent/package.json ./apps/agent/package.json
COPY apps/web/package.json ./apps/web/package.json
COPY packages/contracts ./packages/contracts
RUN --mount=type=cache,target=/root/.local/share/pnpm/store \
    pnpm install --frozen-lockfile

COPY apps/web ./apps/web
RUN pnpm --dir apps/web build

FROM caddy:2.11.4-alpine@sha256:5f5c8640aae01df9654968d946d8f1a56c497f1dd5c5cda4cf95ab7c14d58648

COPY deploy/caddy/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /app/apps/web/dist /srv

RUN THESISTRACE_PUBLIC_ORIGIN=http://127.0.0.1:5173 \
    caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile

EXPOSE 80 443 5173
