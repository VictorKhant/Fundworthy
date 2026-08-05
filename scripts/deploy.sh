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
touch "$DRAIN"

say "Waiting for searches already running to finish"
waited=0
while :; do
    running=$(sqlite3 "$DB" "SELECT COUNT(*) FROM runs WHERE status='running';" 2>/dev/null || echo 0)
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

say "Backing up the database and the encryption key"
mkdir -p "$BACKUP_DIR"
stamp=$(date -u +%Y%m%dT%H%M%SZ)
# .backup, not cp: SQLite in WAL mode has writes sitting in a side file, so copying
# rise.db alone can capture a torn database that looks fine until it does not.
sqlite3 "$DB" ".backup '$BACKUP_DIR/rise-$stamp.db'"
cp "$APP_DIR/data/.fernet-key" "$BACKUP_DIR/fernet-key-$stamp"
# Losing the Fernet key makes every stored API key permanently unrecoverable, so it is
# backed up beside the database and never separately from it.
ls -t "$BACKUP_DIR"/rise-*.db | tail -n +15 | xargs -r rm --
ls -t "$BACKUP_DIR"/fernet-key-* | tail -n +15 | xargs -r rm --
echo "    $BACKUP_DIR/rise-$stamp.db"

say "Pulling"
before=$(git rev-parse --short HEAD)
git fetch origin main
git reset --hard origin/main
after=$(git rev-parse --short HEAD)
echo "    $before -> $after"

say "Installing"
.venv/bin/pip install -q -r requirements.txt
(cd dashboard && npm ci --silent && npm run build --silent)

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
