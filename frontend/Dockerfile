# Two stages: build the SPA, then serve the built assets from nginx.
#
# D21 decision 7 replaced the dev server this used to run. Two things follow:
# Playwright exercises the artifact that actually ships rather than Vite's dev
# server with HMR and source maps, and Phase 7 inherits a deployable image
# instead of containerising under deploy pressure.
#
# `npm ci` not `npm install`: the lockfile is the input, so a build is
# reproducible and a drifted lockfile fails here rather than silently
# resolving something newer.

FROM node:22-alpine AS build

WORKDIR /srv/frontend

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# Auth0 config is read at build time by the SPA (see src/auth.ts for why it is
# not served by the API). Empty means the local dev issuer.
ARG VITE_AUTH0_DOMAIN=""
ARG VITE_AUTH0_CLIENT_ID=""
ARG VITE_AUTH0_AUDIENCE=""
ENV VITE_AUTH0_DOMAIN=$VITE_AUTH0_DOMAIN \
    VITE_AUTH0_CLIENT_ID=$VITE_AUTH0_CLIENT_ID \
    VITE_AUTH0_AUDIENCE=$VITE_AUTH0_AUDIENCE

# `npm run build` runs tsc first, so a type error fails the image rather than
# shipping.
RUN npm run build


FROM nginx:1.27-alpine AS runtime

COPY --from=build /srv/frontend/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/templates/default.conf.template

# nginx:alpine substitutes ${VARS} in /etc/nginx/templates at boot, which is
# how the API host stays configurable without rebuilding the image.
ENV API_PROXY_TARGET=http://backend:8000

EXPOSE 5173

# Fail the container's healthcheck if nginx stops serving the SPA shell.
#
# 127.0.0.1, not localhost. nginx listens on IPv4 only, while `localhost`
# inside the container resolves to ::1 first — so the check connected to an
# IPv6 socket nothing was bound to and reported the container unhealthy for
# every one of its three days of uptime, while the site served fine from the
# host the whole time. Checking a service only from outside is how a broken
# healthcheck survives.
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
  CMD wget -qO- http://127.0.0.1:5173/ >/dev/null 2>&1 || exit 1
