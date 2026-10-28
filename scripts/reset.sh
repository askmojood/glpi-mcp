#!/usr/bin/env bash
# Start over: delete the local GLPI and its data, set it up again, and fill it with the SAMPLE helpdesk.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f docker/.env ] && docker compose -f docker/compose.yml --env-file docker/.env down -v
rm -f .env docker/.env docker/backdate.sql
./scripts/up.sh
set -a; . ./.env; set +a
uv run glpi-seed
docker compose -f docker/compose.yml --env-file docker/.env exec -T db sh -c 'mysql -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE"' \
  2>/dev/null < docker/backdate.sql
