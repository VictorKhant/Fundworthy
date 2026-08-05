#!/usr/bin/env bash
#
# Deploy the current main branch onto this VM, without robbing anyone mid-search.
#
# Run ON the VM. The GitHub Action just SSHes in and calls this, so the same script is
# what a human runs by hand at 2am when the Action is broken — there is one deploy
# procedure, not two that drift apart.
#
# The careful part is the wait. A search is a 5-10 minute subprocess spending an org's
# own Anthropic credit, and `systemctl restart` kills it. The pipeline now catches
# SIGTERM and salvages what it scored, so an interruption is survivable rather than
# total — but "survivable" is not "free", and a nonprofit on a $2-6/month budget should
# not pay for a partial search because we shipped a CSS change.
#
# So: stop accepting new searches, wait for the ones in flight to finish on their own,
# then deploy. If they take too long, back out and leave the box exactly as it was.

set -euo pipefail

APP_DIR="${FUNDWORTHY_DIR:-$HOME/Rise-Fund-Finder}"
SERVICE="${FUNDWORTHY_SERVICE:-fundworthy}"
DB="$APP_DIR/data/rise.db"
DRAIN="$APP_DIR/data/draining"
BACKUP_DIR="${FUNDWORTHY_BACKUPS:-$HOME/fundworthy-backups}"
MAX_WAIT="${FUNDWORTHY_DEPLOY_MAX_WAIT:-900}"   # 15 min: a run is capped near 10

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

# Whatever happens next, stop refusing searches. Without this an aborted deploy leaves
# the app permanently telling every org it is "being updated".
cleanup() { rm -f "$DRAIN"; }
trap cleanup EXIT

cd "$APP_DIR"

say "Pausing new searches"
mkdir -p "$(dirname "$DRAIN")"
# The contents become the banner every visitor sees, signed in or not. A deploy that
# blinks the page without explaining itself reads as the app breaking.
cat > "$DRAIN" <<'NOTICE'
Fundworthy is being updated right now. Searches already running will finish, and new ones can start again in a few minutes. Nothing is lost.
NOTICE

# Python, not the sqlite3 CLI. The CLI is a separate apt package that is not on a stock
# Ubuntu image — the first real deploy died here with `sqlite3: command not found` — and
# the venv we are about to deploy into has the module built in. One less thing to install
# on a box being rebuilt at 2am.
PY_BIN="$APP_DIR/.venv/bin/python"

count_running() {
    "$PY_BIN" - "$DB" <<'PYEOF' 2>/dev/null || echo 0
import sqlite3, sys
try:
    con = sqlite3.connect(sys.argv[1])
    print(con.execute("SELECT COUNT(*) FROM runs WHERE status='running'").fetchone()[0])
except Exception:
    print(0)          # no database yet, or no runs table — nothing to wait for
PYEOF
}

say "Waiting for searches already running to finish"
waited=0
while :; do
    running=$(count_running)
    [ "$running" -eq 0 ] && break
    if [ "$waited" -ge "$MAX_WAIT" ]; then
        echo "Still $running search(es) running after ${MAX_WAIT}s. Not deploying."
        echo "Nothing has changed. Re-run this later, or stop the search from the"
        echo "dashboard first if it is wedged."
        exit 1
    fi
    printf '    %s search(es) still going (%ss elapsed)\n' "$running" "$waited"
    sleep 15
    waited=$((waited + 15))
done
echo "    none running — safe to deploy"

# Read the DB rather than asking the API on purpose: a public "is anything running"
# endpoint would be an unauthenticated fact about usage, and the API is about to be
# restarted anyway.

# Best effort, and deliberately never fatal. A snapshot before a schema migration costs
# a second and occasionally saves an afternoon, but a deploy should not be blocked by a
# missing directory or a database that does not exist yet on a fresh box.
#
# `.backup` rather than `cp`: WAL keeps recent writes in a side file, so copying rise.db
# alone can capture a torn database that looks fine until the day you need it. The Fernet
# key rides along because without it every stored API key is ciphertext nobody can read.
say "Snapshotting the database (best effort)"
stamp=$(date -u +%Y%m%dT%H%M%SZ)
if [ -f "$DB" ]; then
    mkdir -p "$BACKUP_DIR"
    if "$PY_BIN" - "$DB" "$BACKUP_DIR/rise-$stamp.db" <<'PYEOF'
import sqlite3, sys
src, dst = sys.argv[1], sys.argv[2]
with sqlite3.connect(src) as s, sqlite3.connect(dst) as d:
    s.backup(d)
PYEOF
    then
        [ -f "$APP_DIR/data/.fernet-key" ] &&
            cp "$APP_DIR/data/.fernet-key" "$BACKUP_DIR/fernet-key-$stamp"
        ls -t "$BACKUP_DIR"/rise-*.db 2>/dev/null | tail -n +15 | xargs -r rm --
        ls -t "$BACKUP_DIR"/fernet-key-* 2>/dev/null | tail -n +15 | xargs -r rm --
        echo "    $BACKUP_DIR/rise-$stamp.db"
    else
        echo "    could not snapshot — carrying on"
    fi
else
    echo "    no database yet, nothing to snapshot"
fi

say "Pulling"
before=$(git rev-parse --short HEAD)
git fetch origin main
git reset --hard origin/main
after=$(git rev-parse --short HEAD)
echo "    $before -> $after"

say "Installing"
.venv/bin/pip install -q -r requirements.txt

# The dashboard build needs VITE_SITE_URL for the canonical link and the sitemap, and it
# lives in the same .env the systemd unit reads. That file is an EnvironmentFile, not a
# shell script — no `export`, and `source`ing it would run anything in it — so pull out
# the one line rather than executing the file.
if [ -z "${VITE_SITE_URL:-}" ] && [ -f "$APP_DIR/.env" ]; then
    VITE_SITE_URL=$(sed -n 's/^[[:space:]]*VITE_SITE_URL[[:space:]]*=[[:space:]]*//p' \
                    "$APP_DIR/.env" | tail -n 1 | tr -d '"'"'"'\r')
    export VITE_SITE_URL
fi
if [ -n "${VITE_SITE_URL:-}" ]; then
    echo "    site URL: $VITE_SITE_URL"
else
    echo "    VITE_SITE_URL not set — the canonical link and sitemap will be omitted."
    echo "    Add it to $APP_DIR/.env so search engines can index this deployment."
fi
# `npm ci` is the right call — it installs exactly the lockfile — but it refuses outright
# if package.json and the lockfile have drifted, which would turn a CSS change into a
# failed deploy. Fall back rather than stopping.
(cd dashboard && { npm ci --silent || npm install --silent; } && npm run build --silent)

say "Running the tests before touching the service"
# The suite is offline and takes seconds. A deploy that skips it is a deploy that
# discovers a migration bug on a nonprofit's only copy of their data.
if ! .venv/bin/python -m pytest tests/ -q; then
    echo "Tests failed. Rolling the code back and leaving the running service alone."
    git reset --hard "$before"
    (cd dashboard && npm run build --silent) || true
    exit 1
fi

say "Restarting"
sudo systemctl restart "$SERVICE"

sleep 3
for _ in $(seq 1 10); do
    if curl -fsS localhost:8000/api/health >/dev/null 2>&1; then
        say "Deployed $after — the app is answering"
        exit 0
    fi
    sleep 2
done

echo "The service did not come back. Check: journalctl -u $SERVICE -n 50"
echo "The previous commit was $before, and the backup is $BACKUP_DIR/rise-$stamp.db"
exit 1
