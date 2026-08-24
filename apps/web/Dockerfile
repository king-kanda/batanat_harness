# The web image.
#
# Bun builds, Node serves. TanStack Start emits a Nitro server bundle into
# `.output`, which is self-contained — the runtime stage needs neither bun nor
# node_modules.
#
# ---------------------------------------------------------------------------
# READ THIS BEFORE DEPLOYING: VITE_API_URL is baked in at BUILD time.
#
# It is read through `import.meta.env`, so it is compiled into the JavaScript
# the browser downloads. Setting it as a runtime environment variable on the
# container does nothing at all — the bundle already contains whatever value
# was present when it was built. That means one image per API origin, and it
# means a staging image cannot be promoted to production unless both point at
# the same API.
#
# If that becomes annoying, the fix is to serve the API under the same origin
# behind a reverse proxy and drop the variable entirely.
# ---------------------------------------------------------------------------

# --- build -------------------------------------------------------------------

FROM oven/bun:1.3-alpine AS build

WORKDIR /repo

# The workspace root and every member's manifest, so `bun install` can resolve
# the workspace graph before any source is copied.
COPY package.json bun.lock* ./
COPY apps/web/package.json ./apps/web/
COPY packages/schema/package.json ./packages/schema/

RUN bun install --frozen-lockfile

COPY packages/schema ./packages/schema
COPY apps/web ./apps/web

# Must be present at build time — see the note above.
ARG VITE_API_URL=http://localhost:8000
ENV VITE_API_URL=${VITE_API_URL}

# Stamped into the bundle so the login screen can say which commit is serving
# it. Not secrets, and not required — an unstamped build says "dev".
ARG BUILD_SHA=dev
ARG BUILD_TIME=""
ENV BUILD_SHA=${BUILD_SHA} \
    BUILD_TIME=${BUILD_TIME}

RUN cd apps/web && bun run build

# --- runtime -----------------------------------------------------------------

FROM node:22-alpine AS runtime

RUN apk add --no-cache curl \
    && addgroup -g 10001 batanat \
    && adduser -u 10001 -G batanat -D batanat

WORKDIR /app

COPY --from=build --chown=batanat:batanat /repo/apps/web/.output ./.output

ENV NODE_ENV=production \
    PORT=3000 \
    HOST=0.0.0.0

USER batanat

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:3000/login || exit 1

CMD ["node", ".output/server/index.mjs"]
