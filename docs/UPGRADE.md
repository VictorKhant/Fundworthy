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

One variable decides it, and open is what you get by leaving it out.

```bash
nano ~/Rise-Fund-Finder/.env
```

**Open sign-up — anyone can create an account.** This is the default: just make sure
`ALLOWED_EMAILS` is absent or commented out.

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

## 5c · Two settings that are easy to miss

Both go in the same `~/Rise-Fund-Finder/.env`, and both need a restart.

```bash
nano ~/Rise-Fund-Finder/.env
```

### `VITE_SITE_URL` — so Google can index you

**The host is your public address**, the one you type in a browser to reach Fundworthy:
whatever hostname you pointed at the VM in step 7 of DEPLOY-ORACLE (a DuckDNS subdomain,
or a real domain if you bought one). Not the IP, and not `localhost` — it goes into the
`<link rel="canonical">` and the sitemap, and both must be a URL a search engine can
actually fetch.

```bash
VITE_SITE_URL=https://your-host.duckdns.org
```

No trailing slash. `https`, not `http` — a canonical pointing at the plain-HTTP version
of a site that redirects to HTTPS is a redirect loop as far as a crawler is concerned.

It is read at **build** time, not at run time, so it only takes effect on the next
`npm run build`. `scripts/deploy.sh` pulls it out of this file automatically, so a normal
deploy is enough. To apply it without waiting for one:

```bash
cd ~/Rise-Fund-Finder/dashboard
VITE_SITE_URL=https://your-host.duckdns.org npm run build
sudo systemctl restart fundworthy
```

Check it took:

```bash
curl -s https://your-host.duckdns.org/robots.txt          # names your host, not SITE_URL
curl -s https://your-host.duckdns.org/ | grep canonical
```

> Setting this does not put you on Google. It makes you *indexable*. Then: add the site
> at [search.google.com/search-console](https://search.google.com/search-console), verify
> ownership (the DNS TXT method works with DuckDNS), and submit
> `https://your-host.duckdns.org/sitemap.xml`. Expect days to weeks, not hours.

### `FUNDWORTHY_ADMIN_EMAILS` — who may read the platform numbers

```bash
FUNDWORTHY_ADMIN_EMAILS=you@gmail.com,your.friend@gmail.com
```

Comma-separated, and **unset means nobody**. It is deliberately its own list rather than
reusing `ALLOWED_EMAILS`: with open sign-up that one is empty, so hanging admin off "are
you signed in" would publish your numbers to anyone who made an account.

```bash
sudo systemctl restart fundworthy
```

---

## 5d · Reading the platform stats

Two ways, and the first is the one you will actually use.

### On the VM — no token needed

```bash
cd ~/Rise-Fund-Finder
.venv/bin/python -m app.stats
```

```
  Organizations               2
  People                      2
  Active in last 7 days       2   ████████████████████████

  With their own API key      1   ████████████············

  Searches (30 days)          3
    done                      2
    failed                    1
  Spent (30 days)      $    2.14   (their credit, not ours)
```

`--json` for anything scripted. Its authentication is the SSH session: anyone who can run
it can already read `data/rise.db`, so a token here would guard nothing.

**The line that matters is "with their own API key".** Everything above it is somebody
looking; that one is somebody committing their own money. And if "needing a human check"
climbs as a share of findings, the accuracy gate is nulling more fields than it used to —
which usually means a funder site changed shape, and which no single org's dashboard
would ever show you.

### Over HTTP — same numbers, needs a token

`GET /api/admin/stats` is authenticated like every other route, so it needs a Firebase ID
token. Getting one means opening dev tools on the dashboard, finding any `/api/` request,
and copying the `Authorization` header:

```bash
curl -s https://your-host.duckdns.org/api/admin/stats \
     -H "Authorization: Bearer <paste the token>" | python3 -m json.tool
```

Tokens expire after an hour, which is why the CLI exists. A non-admin gets **404**, not
403 — saying "you are not an admin" would confirm the endpoint exists and that being one
is a thing to become.

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
