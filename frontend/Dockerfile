# ──────────────────────────────────────────────────────────────
# sdCloud Frontend — Dockerfile
# Multi-stage build for Next.js 15 standalone output
# ──────────────────────────────────────────────────────────────

# syntax=docker.io/docker/dockerfile:1

FROM oven/bun:alpine AS base

# ── Dependencies stage ───────────────────────────────────────
FROM base AS deps

# libc6-compat is required for some native packages on Alpine
RUN apk add --no-cache libc6-compat

WORKDIR /app

# Copy lock files for deterministic install
COPY package.json bun.lock* ./

RUN bun install --frozen-lockfile

# ── Builder stage ────────────────────────────────────────────
FROM base AS builder

WORKDIR /app

COPY --from=deps /app/node_modules ./node_modules
COPY . .

# Ensure public directory exists for the runner stage
RUN mkdir -p /app/public

# API URL is baked into the client bundle at build time
ARG NEXT_PUBLIC_API_URL=http://localhost:54101
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}

# Runtime port (random high-range port to avoid host conflicts)
ARG PORT=56555
ENV PORT=${PORT}

RUN bun run build

# ── Runner stage ─────────────────────────────────────────────
FROM base AS runner

WORKDIR /app

ENV NODE_ENV=production
ENV HOSTNAME=0.0.0.0

# Runtime port (random high-range port to avoid host conflicts)
ARG PORT=56555
ENV PORT=${PORT}

RUN addgroup --system --gid 1001 nodejs && \
    adduser --system --uid 1001 nextjs

COPY --from=builder /app/public ./public

RUN mkdir .next && chown nextjs:nodejs .next

# Use Next.js output file tracing for a minimal production image
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs

EXPOSE ${PORT}

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD node -e "require('http').get('http://localhost:${PORT}', (r) => r.statusCode === 200 ? process.exit(0) : process.exit(1))" || exit 1

CMD ["node", "server.js"]
