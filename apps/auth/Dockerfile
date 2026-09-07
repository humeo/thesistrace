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

COPY apps/auth ./apps/auth
RUN pnpm --dir apps/auth build
RUN --mount=type=cache,target=/root/.local/share/pnpm/store \
    pnpm --filter thesistrace-auth deploy --prod /auth-runtime

FROM node:24.14.0-bookworm-slim@sha256:d8e448a56fc63242f70026718378bd4b00f8c82e78d20eefb199224a4d8e33d8

ENV NODE_ENV=production
WORKDIR /app/auth

COPY --from=build --chown=node:node /auth-runtime/package.json ./package.json
COPY --from=build --chown=node:node /auth-runtime/node_modules ./node_modules
COPY --from=build --chown=node:node /app/apps/auth/dist ./dist
COPY --from=build --chown=node:node /app/apps/auth/schema ./schema

USER node
EXPOSE 8200
CMD ["node", "dist/server.js"]
