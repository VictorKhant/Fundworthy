# Deploying this update

The live box is running the code from before tenancy existed. This upgrade changes the
database schema, so it is not the usual `git pull`.

Roughly **30 minutes**, most of it verification. Do it when nobody is mid-search.

> ### Read this first
>
> **The v7 migration rewrites four tables in place.** It has been tested against a copy
> of the live database and it is idempotent, but it is still the pilot org's only copy of
> their funders, findings, and encrypted API key. **Step 1 is not optional.**
>
> **You also need `data/.fernet-key`, not just the database.** It is the key that
> decrypts every stored API key. Backing up `rise.db` alone gets you a database full of
> ciphertext nobody can read.

---

## What this update changes, in one paragraph

Every row now belongs to an organization. Each org has its own Anthropic API key, its own
funders, program cards, findings and archive — so a second nonprofit signing in gets
their own empty dashboard instead of the pilot's data and the pilot's key. Runs happen
concurrently across orgs rather than one at a time. There is a monthly spend cap per org.
The fetcher refuses to fetch private addresses. And pushing to `main` now deploys.

---

## 1 · Back up. Actually do this.

```bash
ssh fundworthy          # or: ssh -i ~/.ssh/fundworthy_vm ubuntu@$VM_IP
cd ~/Rise-Fund-Finder

mkdir -p ~/fundworthy-backups
STAMP=$(date -u +%Y%m%dT%H%M%SZ)

# `.backup`, not `cp`. SQLite in WAL mode keeps recent writes in a side file, so copying
# rise.db alone can capture a torn database that looks fine until the day you need it.
sqlite3 data/rise.db ".backup '$HOME/fundworthy-backups/rise-$STAMP.db'"
cp data/.fernet-key ~/fundworthy-backups/fernet-key-$STAMP

ls -la ~/fundworthy-backups/
```

Confirm both files are there and the `.db` is not zero bytes. If `sqlite3` is missing:
`sudo apt install -y sqlite3`.

**Record the commit you are on**, so you can get back to it:

```bash
git rev-parse --short HEAD    # write this down
```

---

## 2 · Check nobody is mid-search

```bash
sqlite3 data/rise.db "SELECT COUNT(*) FROM runs WHERE status='running';"
```

`0` means go. Anything else: wait, or stop it from the dashboard. A restart mid-run used
to destroy the run and the money spent on it — this update fixes that, but the fix is not
running yet.

---

## 3 · Deploy

```bash
cd ~/Rise-Fund-Finder
git fetch origin main
git reset --hard origin/main

.venv/bin/pip install -r requirements.txt
cd dashboard && npm install && npm run build && cd ..

# The suite is offline — no key, no network, nothing spent. Run it BEFORE restarting, so
# a problem is something you read about rather than something your users discover.
.venv/bin/python -m pytest tests/ -q      # expect 256 passed, 1 skipped

sudo systemctl restart fundworthy
```

---

## 4 · Verify the migration

```bash
sqlite3 data/rise.db "SELECT value FROM meta WHERE key='schema_version';"   # 7
sqlite3 data/rise.db "SELECT COUNT(*) FROM funders WHERE org_id='default';" # your funder count
sqlite3 data/rise.db "SELECT COUNT(*) FROM opportunities;"                  # unchanged
sqlite3 data/rise.db "SELECT name FROM sqlite_master WHERE name LIKE '%pre_org%';"  # empty
```

That last one matters: `*__pre_org` tables left behind mean the migration stopped
halfway. If you see any, restore from step 1 and stop.

Then the app itself:

```bash
sudo systemctl status fundworthy --no-pager
sudo journalctl -u fundworthy -n 30 --no-pager | grep -i "sign-in\|migrated\|interrupted"
curl -s -o /dev/null -w '%{http_code}\n' https://$HOST/api/state    # 401
curl -sI https://$HOST/ | grep -i "content-security-policy"          # present
```

And in a browser: sign in, and confirm your funders and this month's findings are still
there. **The first person to sign in inherits the pilot org's data** — so whoever has
been using Fundworthy should sign in first, before anyone else does.

### If something is wrong

```bash
cd ~/Rise-Fund-Finder
git reset --hard <the commit you wrote down>
cp ~/fundworthy-backups/rise-$STAMP.db data/rise.db
cp ~/fundworthy-backups/fernet-key-$STAMP data/.fernet-key
cd dashboard && npm run build && cd ..
sudo systemctl restart fundworthy
```

---

## 5 · Adding a colleague — it is **two** steps, not one

This is the part that will confuse you if nobody says it out loud.

| | |
|---|---|
| **Firebase / `ALLOWED_EMAILS`** | Decides whether someone can sign in **at all**. Lives in `.env` on the VM. |
| **An invitation code** | Decides which **organization** they land in once they are through the door. Generated in the app. |

They are different gates and you need both. Add someone to `ALLOWED_EMAILS` without a
code and they sign in to their own empty organization. Send a code to someone not on
`ALLOWED_EMAILS` and they cannot sign in to redeem it.

**To add a colleague to your organization:**

```bash
# 1. Let them in the front door
nano ~/Rise-Fund-Finder/.env          # append their address to ALLOWED_EMAILS
sudo systemctl restart fundworthy     # only read at startup

sudo journalctl -u fundworthy -n 20 | grep -i "sign-in"
# INFO app.auth: Sign-in is on. Firebase project <id>, N address(es) allowed.  ← N went up
```

2. In the dashboard: **Settings → Your organization → Create an invitation code**, and
   send them the code. They paste it the first time they sign in.

Codes are single-use and expire in two weeks. Fundworthy does not send email on anyone's
behalf, so send it however you normally talk to them.

> Yes, the `.env` half should live in the database so this is one step in the UI. It is
> written up in FUTURE.md §2. Until then, it is two.

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
