# Deploying this update

The live box may still be running code from before organizations existed. That change
altered the database schema, so there are two ways in and they are genuinely different.

**Pick the one that describes you.** Most of this document is the careful path; if you
are still building, take the first one and skip nine tenths of it.

---

## Path A — no real users yet (probably you)

If the only accounts are yours and your teammate's, there is nothing on that box worth
migrating. Starting clean is faster, less to go wrong, and leaves no half-migrated state
to debug later.

```bash
ssh fundworthy
cd ~/Rise-Fund-Finder

sudo systemctl stop fundworthy
rm -f data/rise.db data/rise.db-wal data/rise.db-shm
# Keep data/.fernet-key or delete it — deleting it just means re-pasting the API key,
# since it is what decrypts the stored one.

git fetch origin main && git reset --hard origin/main
.venv/bin/pip install -r requirements.txt
(cd dashboard && npm install && npm run build)
sudo systemctl start fundworthy
```

Then set sign-up mode in `.env` (§5), restart, and sign in. **You do not need
`FUNDWORTHY_PILOT_EMAILS`** — on a fresh database the first person to sign in gets the
default organization, including the 44 researched San Diego funders that ship with it.
That variable only exists to stop a stranger inheriting *accumulated* work: real findings
or a saved API key. A fresh install has neither.

Jump to §5.

---

## Path B — there is data somebody would miss

Real findings, a saved API key, funders someone curated. Then the migration matters and
so does the backup.

> **The v7 migration rewrites four tables in place.** It has been tested against a copy of
> a real database and it is idempotent, but it is still somebody's only copy. **Back up
> first, and back up two files:** `data/rise.db` **and** `data/.fernet-key`. Without the
> key you have a database full of ciphertext nobody can read.

---

## What this update changes, in one paragraph

Every row now belongs to an organization. Each org has its own Anthropic API key, its own
funders, program cards, findings and archive — so a second nonprofit signing in gets
their own empty dashboard instead of somebody else's data and somebody else's key. Runs
happen concurrently across orgs rather than one at a time. There is a monthly spend cap
per org. The fetcher refuses to fetch private addresses. And pushing to `main` deploys.

---

## 1 · Back up (Path B only)

`sqlite3` is a separate apt package and is not on a stock Ubuntu image. The venv's Python
has it built in, so use that rather than installing anything:

```bash
cd ~/Rise-Fund-Finder
mkdir -p ~/fundworthy-backups
STAMP=$(date -u +%Y%m%dT%H%M%SZ)

# .backup, not cp: WAL keeps recent writes in a side file, so copying rise.db alone can
# capture a torn database that looks fine until the day you need it.
.venv/bin/python - <<EOF
import sqlite3
with sqlite3.connect("data/rise.db") as s, \
     sqlite3.connect("$HOME/fundworthy-backups/rise-$STAMP.db") as d:
    s.backup(d)
EOF
cp data/.fernet-key ~/fundworthy-backups/fernet-key-$STAMP
ls -la ~/fundworthy-backups/

git rev-parse --short HEAD    # write this down, it is your way back
```

---

## 2 · Check nobody is mid-search

```bash
.venv/bin/python -c "import sqlite3;print(sqlite3.connect('data/rise.db').execute(\
  \"SELECT COUNT(*) FROM runs WHERE status='running'\").fetchone()[0])"
```

`0` means go.

---

## 3 · Deploy

```bash
cd ~/Rise-Fund-Finder
git fetch origin main
git reset --hard origin/main

.venv/bin/pip install -r requirements.txt
(cd dashboard && npm install && npm run build)

# Offline — no key, no network, nothing spent. Run it BEFORE restarting, so a problem is
# something you read about rather than something your users discover.
.venv/bin/python -m pytest tests/ -q      # expect 255 passed, 1 skipped

sudo systemctl restart fundworthy
```

---

## 4 · Verify

```bash
P=.venv/bin/python
$P -c "import sqlite3;print(sqlite3.connect('data/rise.db').execute(\
  \"SELECT value FROM meta WHERE key='schema_version'\").fetchone())"          # 7
$P -c "import sqlite3;print(sqlite3.connect('data/rise.db').execute(\
  \"SELECT name FROM sqlite_master WHERE name LIKE '%pre_org%'\").fetchall())"  # []

sudo systemctl status fundworthy --no-pager
sudo journalctl -u fundworthy -n 30 --no-pager | grep -i "sign-in\|migrated"
curl -s -o /dev/null -w '%{http_code}\n' https://$HOST/api/state    # 401
```

An empty second result matters: leftover `*__pre_org` tables mean the migration stopped
halfway. On Path B, restore and stop. On Path A, just wipe and start over.

### If something is wrong (Path B)

```bash
git reset --hard <the commit you wrote down>
cp ~/fundworthy-backups/rise-$STAMP.db data/rise.db
cp ~/fundworthy-backups/fernet-key-$STAMP data/.fernet-key
(cd dashboard && npm run build)
sudo systemctl restart fundworthy
```

---

## 5 · Choosing private or open sign-up

The app now refuses to start unless you pick one. They are opposite products.

```bash
nano ~/Rise-Fund-Finder/.env
```

**Open sign-up — anyone can create an account:**

```bash
FUNDWORTHY_OPEN_SIGNUP=1
# and remove or comment out ALLOWED_EMAILS
FUNDWORTHY_PILOT_EMAILS=whoever@has-been-using-it.org
```

**Private — only listed people:**

```bash
ALLOWED_EMAILS=admin@your-org.org,someone@else.org
```

> **`FUNDWORTHY_PILOT_EMAILS` is only for Path B**, and only once the default
> organization has accumulated something: real findings, or a saved API key. Whoever
> lands in that org can spend that key, so with open sign-up it must not go to whoever
> happens to sign in first.
>
> **On a fresh database, leave it out.** Shipped seed content — the 44 researched
> funders, the program cards — does not count as somebody's work, so the first person to
> sign in simply gets the default org and everything in it. That is what you want.

```bash
sudo systemctl restart fundworthy
sudo journalctl -u fundworthy -n 20 | grep -i "sign-in"
# Sign-in is on (open sign-up). Firebase project <id> — any Google account ...
#   ...or...
# Sign-in is on (private). Firebase project <id>, N address(es) allowed.
```

Abuse control with sign-up open: a new org has no API key, so it cannot spend anyone's
money — but it can still make the server crawl on the free tier.
`FUNDWORTHY_MAX_RUNS_PER_DAY` (default 12) bounds that per org.

---

## 5b · Adding a colleague

This is the part that will confuse you if nobody says it out loud.

| | |
|---|---|
| **Signing in** | Open sign-up: nothing to do, they just sign in with Google. Private install: their address has to be in `ALLOWED_EMAILS`, then a restart. |
| **An invitation code** | Which **organization** they land in. Generated in the app: **Settings → Your organization → Create an invitation code**. |

Without a code, a new person signs in to their **own empty organization** — which is
correct for a different nonprofit and wrong for a colleague. Send them a code and they
join yours instead, with its funders, program cards and findings.

Codes are single-use and expire in two weeks. Fundworthy does not send email on anyone's
behalf, so send it however you normally talk to them.

> On a private install this is still two steps, because the allow-list lives in `.env`
> rather than the database. With open sign-up it is one — which is the main practical
> reason to prefer it.

---

## 6 · Firebase — nothing to change, two things to check

This update does not change how sign-in works, so there is no Firebase migration. Confirm
these are still true:

1. **Authentication → Settings → Authorized domains** contains your hostname. If sign-in
   fails with `auth/unauthorized-domain`, this is why.
2. **Project settings → General → Your apps** — `apiKey` and `projectId` still match
   `FIREBASE_WEB_API_KEY` and `FIREBASE_PROJECT_ID` in `.env`.

```bash
curl -s https://$HOST/api/auth/config     # {"enabled":true,"project_id":...}
```

While you are in a console: **set a spend limit on the Anthropic account** that owns the
key in `.env` (console.claude.com → Settings → Limits). The app has its own monthly cap
now, but that one is our code checking our code. The Anthropic-side limit holds even when
ours is wrong.

---

## 7 · HSTS on nginx

The app sends CSP and the other security headers itself. HSTS is deliberately **not**
among them: it would also be sent to a local `http://127.0.0.1:8000` install and pin that
hostname to HTTPS in a developer's browser for a year. It belongs here instead.

```bash
sudo nano /etc/nginx/sites-available/fundworthy
```

Inside the `server { listen 443 ...}` block certbot created:

```nginx
    add_header Strict-Transport-Security "max-age=31536000" always;
    client_max_body_size 2m;
```

```bash
sudo nginx -t && sudo systemctl reload nginx
```

> `max-age=31536000` is a year, and it is a **commitment**: browsers that have seen it
> will refuse plain HTTP to this hostname until it expires. That is what you want for a
> box with a real certificate. Do not add `includeSubDomains` unless every subdomain has
> one too.

---

## 8 · Turn on push-to-deploy

After this, merging to `main` updates the VM by itself — draining searches first, backing
up, running the tests, and rolling back if they fail.

**On the VM**, make a key that belongs to the deploy and not to a person:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/github_deploy -N "" -C "github-actions@fundworthy"
cat ~/.ssh/github_deploy.pub >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys

cat ~/.ssh/github_deploy       # the PRIVATE half — copy all of it, BEGIN/END lines too
```

The deploy script runs `sudo systemctl restart`, so let it do that one thing without a
password:

```bash
echo "$USER ALL=(ALL) NOPASSWD: /bin/systemctl restart fundworthy" \
  | sudo tee /etc/sudoers.d/fundworthy-deploy
sudo chmod 440 /etc/sudoers.d/fundworthy-deploy
```

**On your laptop**, get the host's fingerprint so the Action does not have to trust
whatever answers:

```bash
ssh-keyscan $VM_IP
```

**On GitHub** → repo → Settings → Secrets and variables → Actions → New repository secret:

| Name | Value |
|---|---|
| `VM_HOST` | the IP or hostname |
| `VM_USER` | `ubuntu` |
| `VM_SSH_KEY` | the whole private key from above |
| `VM_KNOWN_HOSTS` | the whole `ssh-keyscan` output |

Then run it once by hand — **Actions → Deploy → Run workflow** — rather than discovering
it is broken on a push you cared about.

### While you are on GitHub

**Settings → Branches → Add rule** for `main`: require a pull request, block force-push.
Everything above deploys straight from `main`, so `main` becomes production.

---

## What to watch for in the first week

| Symptom | Cause |
|---|---|
| Dashboard is empty after signing in | Somebody else signed in first and adopted the pilot org. Check `sqlite3 data/rise.db "SELECT email, org_id FROM users;"` |
| "not on this install's allow-list" | `ALLOWED_EMAILS` — §5. Restart after editing. |
| A colleague has their own empty dashboard | They signed in before redeeming a code. Generate another; redeeming moves them. |
| "being updated right now" and it is not | An aborted deploy left the drain file. `rm ~/Rise-Fund-Finder/data/draining` |
| Searches say "no API key saved" | Correct, and deliberate: an org now gets its own key or none. The `.env` key only serves the pilot org. |
| A search returns fewer results than before | Check **Settings → Where you work**. That setting now actually filters; blank means no geographic filtering at all. |
