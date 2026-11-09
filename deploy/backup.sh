#!/usr/bin/env bash
set -euo pipefail
umask 077

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$root"
compose=(docker compose -f docker-compose.yml -f docker-compose.production.yml)
running=$("${compose[@]}" ps --status running --services)
for service in back-db gen-db; do
  found=0
  while IFS= read -r item; do
    if [[ "$item" == "$service" ]]; then
      found=1
    fi
  done <<< "$running"
  if (( !found )); then
    echo "$service is not running; start the production databases before backup" >&2
    exit 1
  fi
done

stamp=$(date -u +%Y%m%dT%H%M%SZ)
destination=${1:-$root/backups}/$stamp
mkdir -p "$destination"
"${compose[@]}" exec -T back-db sh -c \
  'pg_dump --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" --format=custom' \
  > "$destination/back.dump"
"${compose[@]}" exec -T gen-db sh -c \
  'pg_dump --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" --format=custom' \
  > "$destination/gen.dump"
gzip -9 "$destination/back.dump" "$destination/gen.dump"
(
  cd "$destination"
  sha256sum back.dump.gz gen.dump.gz > SHA256SUMS
)
printf '%s\n' "$destination"
