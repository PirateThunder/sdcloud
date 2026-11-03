FROM oven/bun:1-slim AS deps
WORKDIR /app
COPY package.json bun.lock ./
RUN bun install --frozen-lockfile

FROM node:22-slim AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ARG BACKEND_URL=http://back-api:61230
ARG NEXT_PUBLIC_LLM_PROVIDER=fixture
ENV BACKEND_URL=$BACKEND_URL
ENV NEXT_PUBLIC_LLM_PROVIDER=$NEXT_PUBLIC_LLM_PROVIDER
RUN npm run build

FROM node:22-slim AS runner
WORKDIR /app
ENV NODE_ENV=production \
    PORT=54733
COPY --from=builder --chown=node:node /app/dist ./dist
COPY --from=builder --chown=node:node /app/node_modules ./node_modules
COPY --from=builder --chown=node:node /app/package.json ./package.json
COPY --from=builder --chown=node:node /app/next.config.ts ./next.config.ts
COPY --from=builder --chown=node:node /app/public ./public
USER node
EXPOSE 54733
CMD ["node", "node_modules/next/dist/bin/next", "start"]
