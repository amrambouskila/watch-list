# syntax=docker/dockerfile:1

# React 18 + TypeScript strict, built by Vite and served by nginx.
#
# nginx is also the reverse proxy: /api and /heroes go to the backend container, so the browser
# only ever talks to one origin and the app's CORS configuration never comes into it.

FROM node:26-alpine AS build

ENV PNPM_HOME=/pnpm \
    PATH=/pnpm:$PATH \
    COREPACK_ENABLE_DOWNLOAD_PROMPT=0
# Pinned to the version the lockfile (lockfileVersion 9.0) was written by.
RUN corepack enable && corepack prepare pnpm@9.15.9 --activate

WORKDIR /srv/app/frontend

COPY package.json pnpm-lock.yaml ./
# Dev dependencies are needed: `pnpm build` runs `tsc -b` first, and tsconfig.json includes
# tests/ and layout/, which import vitest and @playwright/test.
RUN pnpm install --frozen-lockfile

COPY . .
RUN pnpm build

# nginx-unprivileged rather than plain nginx:alpine. The stock image's master process runs as
# root so it can bind port 80 and write /var/run/nginx.pid; this one is the same nginx configured
# to run as uid 101 and listen on 8080, which is what lets the container drop root without
# rewriting the image's main nginx.conf. Nothing here needs a privileged port - compose publishes
# the host port onto 8080.
FROM nginxinc/nginx-unprivileged:alpine

# The base image already runs as uid 101, so root is borrowed back only long enough to take
# alpine's current security updates - `trivy --ignore-unfixed` in CI fails on exactly the
# findings this clears.
USER root
RUN apk upgrade --no-cache

COPY --from=build /srv/app/frontend/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

USER nginx

EXPOSE 8080

CMD ["nginx", "-g", "daemon off;"]
