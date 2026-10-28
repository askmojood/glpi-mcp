#!/usr/bin/env bash
# Start the local GLPI (it installs itself on first start), then the first time: give GLPI's default accounts
# (glpi, tech, normal, post-only) generated passwords, make the demo's API user "Claude Connector", and switch the
# REST API on for this machine (it signs in with that user's login: GLPI keeps API tokens encrypted with its own key). Every secret is generated here and stays in the git-ignored
# files docker/.env and .env; none is printed.
set -euo pipefail
cd "$(dirname "$0")/.."
dc() { docker compose -f docker/compose.yml --env-file docker/.env "$@"; }
rnd() { openssl rand -hex 16; }

if [ ! -f docker/.env ]; then
  cat > docker/.env <<ENV
GLPI_DB_HOST=db
GLPI_DB_PORT=3306
GLPI_DB_NAME=glpi
GLPI_DB_USER=glpi
GLPI_DB_PASSWORD=$(rnd)
ADMIN_PASSWORD=$(rnd)
TZ=UTC
ENV
fi

dc up -d
echo "waiting for GLPI (the first start installs it)…"
for _ in $(seq 1 120); do
  curl -fsS -o /dev/null http://127.0.0.1:8095/ 2>/dev/null && break
  sleep 5
done

if ! grep -q '^GLPI_PASSWORD=' .env 2>/dev/null; then
  console() { dc exec -T glpi php bin/console --no-interaction "$@" >/dev/null; }
  sql() { dc exec -T db sh -c 'mysql -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE"' 2>/dev/null <<<"$1"; }
  pw=$(grep '^ADMIN_PASSWORD=' docker/.env | cut -d= -f2)
  # The web page answers before the first-run install is done: wait until GLPI's own console works.
  for _ in $(seq 1 60); do console user:reset_password glpi --password="$(rnd)" 2>/dev/null && break; sleep 5; done
  for u in tech normal post-only; do console user:reset_password "$u" --password="$(rnd)"; done
  console user:create claude --password="$pw" 2>/dev/null || console user:reset_password claude --password="$pw"
  console user:grant claude --profile=4 --entity=0 --recursive  # 4 = Super-Admin
  console config:set names_format 1  # "First Last", not GLPI's default "Last First"
  console config:set enable_api 1
  console config:set enable_api_login_credentials 1
  console config:set url_base_api "http://localhost:8095/apirest.php"
  sql "UPDATE glpi_users SET firstname='Claude', realname='Connector', profiles_id=4 WHERE name='claude';
       UPDATE glpi_apiclients SET ipv4_range_start=NULL, ipv4_range_end=NULL, ipv6=NULL, is_active=1 WHERE id=1;"
  { echo "GLPI_URL=http://127.0.0.1:8095"; echo "GLPI_LOGIN=claude"; echo "GLPI_PASSWORD=$pw"; } >> .env
  echo "API user created (in docker/.env and .env)"
fi
echo "GLPI is up at http://localhost:8095"
