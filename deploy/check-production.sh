#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$root"

missing=0
required=(
  GEN_DB_PASSWORD
  BACK_DB_PASSWORD
  SERV_API_KEY
  BACK_JWT_SECRET
  BACK_OTP_SECRET
  SDCLOUD_DOMAIN
  SDCLOUD_TLS_EMAIL
  BACK_CORS_ORIGINS
  BACK_SMTP_HOST
)
for name in "${required[@]}"; do
  if [[ -z "${!name-}" ]]; then
    echo "missing required variable: $name" >&2
    missing=1
  fi
done
if [[ -z "${BACK_SMTP_FROM:-}" && -z "${BACK_SMTP_USER:-}" ]]; then
  echo "set BACK_SMTP_FROM or BACK_SMTP_USER" >&2
  missing=1
fi
if [[ "${BACK_ENV:-production}" != "production" ]]; then
  echo "BACK_ENV must be production" >&2
  missing=1
fi
if [[ "${BACK_EMAIL_DEV_CODE:-0}" != "0" ]]; then
  echo "BACK_EMAIL_DEV_CODE must be 0 in production" >&2
  missing=1
fi
for name in BACK_JWT_SECRET BACK_OTP_SECRET; do
  if [[ "${!name-}" == sdcloud-local-* ]]; then
    echo "$name uses an insecure local default" >&2
    missing=1
  fi
done
if [[ "${BACK_CORS_ORIGINS:-}" != https://* ]]; then
  echo "BACK_CORS_ORIGINS must use HTTPS" >&2
  missing=1
fi
if [[ "${SDCLOUD_DOMAIN:-}" == *"://"* || "${SDCLOUD_DOMAIN:-}" == *"/"* ]]; then
  echo "SDCLOUD_DOMAIN must be a hostname without scheme or path" >&2
  missing=1
elif [[ "${BACK_CORS_ORIGINS:-}" != *"${SDCLOUD_DOMAIN}"* ]]; then
  echo "BACK_CORS_ORIGINS must contain SDCLOUD_DOMAIN" >&2
  missing=1
fi
smtp_port=${BACK_SMTP_PORT:-465}
if [[ ! "$smtp_port" =~ ^[0-9]+$ ]] || ((smtp_port < 1 || smtp_port > 65535)); then
  echo "BACK_SMTP_PORT must be a valid TCP port" >&2
  missing=1
fi
provider=${LLM_PROVIDER:-openrouter}
if [[ "$provider" == "openrouter" && -z "${OPENROUTER_API_KEY:-}" ]]; then
  echo "OPENROUTER_API_KEY is required when LLM_PROVIDER=openrouter" >&2
  missing=1
fi
if [[ "$provider" =~ ^(local|vllm|openai_compatible)$ && "${LLM_DYNAMIC_ROUTING:-0}" != "1" ]]; then
  if [[ -z "${LOCAL_LLM_BASE_URL:-}" || -z "${LOCAL_LLM_MODEL:-}" ]]; then
    echo "local provider requires LOCAL_LLM_BASE_URL and LOCAL_LLM_MODEL" >&2
    missing=1
  fi
fi
if ((missing)); then
  exit 1
fi

docker compose -f docker-compose.yml -f docker-compose.production.yml config --quiet
image=${CADDY_IMAGE:-caddy:2.10.2-alpine@sha256:4c6e91c6ed0e2fa03efd5b44747b625fec79bc9cd06ac5235a779726618e530d}
docker run --rm --network none \
  -e SDCLOUD_DOMAIN \
  -e SDCLOUD_TLS_EMAIL \
  -v "$root/deploy/Caddyfile:/etc/caddy/Caddyfile:ro" \
  "$image" caddy validate --config /etc/caddy/Caddyfile
bash -n deploy/backup.sh
printf '%s\n' "production preflight passed; no services were started"
