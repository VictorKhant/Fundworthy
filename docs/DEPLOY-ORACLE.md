# Deploying to an Oracle Cloud free-tier VM

Copy-paste, in order. Roughly **60–90 minutes** the first time, most of it waiting.

Do this **after** you've confirmed the app runs locally, not before — several steps can
fail for reasons outside your control (capacity errors, card verification), and none of
them are things you want to discover under pressure.

> **Read this first — the order is forced.**
> Google sign-in has to be told the address it will be used from, so you cannot configure
> it until the VM exists and has a hostname. The sequence is **VM → app running → HTTPS →
> *then* sign-in.** Setting sign-in up against `localhost` first is work you throw away.

---

## Before you start

| | |
|---|---|
| An Oracle Cloud account | Free tier, needs a card for identity verification (not charged) |
| The new shared Gmail | Create it first — the Oracle account, the domain, and the Google OAuth app should all belong to it, so the handoff is one login |
| An Anthropic API key | The one that will pay. Whoever owns it owns the bill. |

Everything below assumes the **Always Free** ARM shape. It is genuinely free forever,
not a trial.

---

## Step 1 · Create the VM

1. Sign up at **cloud.oracle.com** with the new Gmail. Pick a **home region close to
   San Diego** — `us-sanjose-1` or `us-phoenix-1`. This cannot be changed later.
2. Console → **Compute** → **Instances** → **Create instance**.
3. Set:
   - **Image:** Canonical **Ubuntu 22.04**
   - **Shape:** Change shape → **Ampere** → `VM.Standard.A1.Flex` → **2 OCPU, 12 GB RAM**
   - **Networking:** keep the default VCN, and make sure **Assign a public IPv4 address**
     is on
   - **SSH keys:** *Generate a key pair for me*, then **download the private key**. You
     cannot download it again.
4. **Create**, and wait for the state to go green.

> **If you get "Out of host capacity"** — extremely common on ARM free tier — it is not
> your mistake. Either retry every few hours, try a different availability domain in the
> same region, or fall back to the **VM.Standard.E2.1.Micro** x86 shape, which is also
> Always Free and perfectly adequate here.

Note the **public IP address** shown on the instance page. Everything below calls it
`$VM_IP`.

---

## Step 2 · Open the ports

Oracle blocks everything by default in **two** places, and people usually miss the second.

**a. The cloud firewall.** Instance page → **Subnet** link → **Default Security List** →
**Add Ingress Rules**:

| Source CIDR | Protocol | Destination port |
|---|---|---|
| `0.0.0.0/0` | TCP | `80` |
| `0.0.0.0/0` | TCP | `443` |

**b. The VM's own firewall.** After you SSH in (next step), run:

```bash
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save
```

Ubuntu on Oracle ships with iptables rules that drop everything but SSH. Skipping this
is the single most common reason a correctly-deployed app is unreachable.

---

## Step 3 · Connect and install

```bash
chmod 600 ~/Downloads/ssh-key-*.key
ssh -i ~/Downloads/ssh-key-*.key ubuntu@$VM_IP
```

Then, on the VM:

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3.11 python3.11-venv python3-pip git nginx
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
python3.11 --version && node --version
```

---

## Step 4 · Get the app on the VM

```bash
cd ~
git clone https://github.com/VictorKhant/Rise-Fund-Finder.git
cd Rise-Fund-Finder

python3.11 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

cd dashboard && npm install && npm run build && cd ..
```

Create the environment file:

```bash
cat > .env <<'EOF'
ANTHROPIC_API_KEY=sk-ant-PUT-THE-REAL-KEY-HERE
FUNDWORTHY_STRICT_CONFIG=0
# Sign-in goes here in step 8, once this box has a hostname.
EOF
chmod 600 .env
```

Smoke-test it before wiring anything else up:

```bash
.venv/bin/python -m pytest tests/ -q          # expect 167 passed
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 &
sleep 3 && curl -s localhost:8000/api/health  # expect {"ok":true}
kill %1
```

---

## Step 5 · Run it as a service

So it survives reboots and crashes.

```bash
sudo tee /etc/systemd/system/fundworthy.service > /dev/null <<'EOF'
[Unit]
Description=Fundworthy — nonprofit funding researcher
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/Rise-Fund-Finder
EnvironmentFile=/home/ubuntu/Rise-Fund-Finder/.env
ExecStart=/home/ubuntu/Rise-Fund-Finder/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now fundworthy
sudo systemctl status fundworthy --no-pager
```

It binds to `127.0.0.1`, not `0.0.0.0` — nginx is the only thing that talks to it.

---

## Step 6 · nginx in front

```bash
sudo tee /etc/nginx/sites-available/fundworthy > /dev/null <<'EOF'
server {
    listen 80;
    server_name _;

    # The pipeline runs 5-10 minutes and streams its log. Default nginx timeouts are
    # 60s, which would cut the run off mid-crawl and look like a crash.
    proxy_read_timeout 900s;
    proxy_send_timeout 900s;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;          # so the run log streams instead of arriving at the end
    }
}
EOF

sudo ln -sf /etc/nginx/sites-available/fundworthy /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
```

Now `http://$VM_IP` should load the app. **Stop and confirm that before continuing.**

---

## Step 7 · A hostname and HTTPS

You need a real hostname for Google sign-in — OAuth will not accept a bare IP.

Cheapest options: a **DuckDNS** subdomain (free, 2 minutes) or a real domain from
Namecheap/Cloudflare (~$10/yr, better for a handoff). Point an **A record** at `$VM_IP`.

Then:

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d fundworthy.example.org     # your hostname
```

Certbot edits the nginx config and sets up auto-renewal. Confirm `https://your-host`
loads.

---

## Step 8 · Google sign-in, via Firebase

> ⚠️ **Do not skip this.** The app now stores an Anthropic API key and is reachable from
> the internet. Without a login, anyone who finds the URL can spend the org's money.

**This is built.** Sign-in is Firebase Authentication in the browser, with the ID token
verified server-side against Google's public keys (`app/auth.py`). There is no OAuth
client to create, no client secret, no redirect URI to match character for character, and
no session cookie to get lost behind the proxy. Two console pages and four lines in
`.env`, about **20 minutes**.

Two separate questions, and Firebase only answers the first:

| | |
|---|---|
| **Who is this?** | Firebase. A Google account, an ID token, a verified email. |
| **Are they allowed?** | `ALLOWED_EMAILS`, yours alone. Firebase will authenticate any Google account on earth. |

### 8a. Configure Firebase

1. **console.firebase.google.com** → **Create a project**, e.g. `fundworthy`. Sign in as
   the shared Gmail. Google Analytics: **off**, you don't need it. (A Firebase project
   *is* a Google Cloud project, so this adds nothing to the handoff.)
2. **Build → Authentication → Get started → Google → Enable.** Set the project support
   email to the shared Gmail. **Save.**
3. **Authentication → Settings → Authorized domains → Add domain** → your hostname from
   step 7 (e.g. `fundworthy.duckdns.org`). Hostname only — no `https://`, no path.
4. **⚙ Project settings → General → Your apps → Web (`</>`)**. Nickname it `Fundworthy`,
   skip Firebase Hosting, **Register app**. From the config block it shows you, copy two
   values: `apiKey` and `projectId`.

That `apiKey` is a public project identifier — it ships in the page source of every
Firebase web app by design and grants nothing on its own. It is not the same kind of
thing as the Anthropic key, which still has no endpoint that returns it.

### 8b. Configure the server

Add to `.env`:

```bash
FIREBASE_PROJECT_ID=fundworthy-1a2b3
FIREBASE_WEB_API_KEY=AIzaSy...
ALLOWED_EMAILS=admin@your-org.org,the-shared-gmail@gmail.com
```

Then:

```bash
cd ~/Rise-Fund-Finder
git pull
.venv/bin/pip install -r requirements.txt     # adds pyjwt
sudo systemctl restart fundworthy
```

No rebuild of the dashboard. The browser reads whether sign-in exists from
`GET /api/auth/config` at page load, so one build works with it on or off — changing any
of this is `.env` plus a restart.

**`ALLOWED_EMAILS` is not optional.** With `FIREBASE_PROJECT_ID` set and the allow-list
empty, the app refuses to start and says why in `journalctl`. That is deliberate: the
alternative was an app that boots and lets in every Google account in existence.

### 8c. Check it

```bash
curl -s https://your-host/api/auth/config     # {"enabled":true,...}
curl -s -o /dev/null -w '%{http_code}\n' https://your-host/api/state    # 401
```

A `401` there is the whole point — the API is closed to anyone without a token. Then open
the site in a browser: you should land on the sign-in page, and **Continue with Google**
should get you in. Try it once with a Google account that is *not* in `ALLOWED_EMAILS` and
confirm it is refused with a message naming the allow-list.

| If it says | Then |
|---|---|
| `auth/unauthorized-domain` | The hostname is missing from step 8a.3. It must match exactly. |
| It signs in, then bounces back to the sign-in page saying "not on this install's allow-list" | Working as designed. Add the address to `ALLOWED_EMAILS` and restart. |
| `Failed to load resource: /api/auth/config` | The app is not running — `systemctl status fundworthy`. |
| The service will not start | `journalctl -u fundworthy -n 30` — most likely `ALLOWED_EMAILS` is empty. |

---

## Step 9 · Hand it over

```bash
sudo systemctl status fundworthy --no-pager   # active (running)
sudo certbot renew --dry-run                  # renewal works
```

- Back up **`data/rise.db`** and **`data/.fernet-key`** somewhere private. That is the
  org's settings, funders, findings, and the encrypted key. Losing it loses everything.
- Give the user the URL, and check their address is in `ALLOWED_EMAILS` before you do.
- Put a name against the API key.
- Write down where `.env` lives. Adding a colleague later is one line in it and a
  restart; nobody should have to rediscover that.

### Updating it later

```bash
cd ~/Rise-Fund-Finder
git pull
.venv/bin/pip install -r requirements.txt
cd dashboard && npm install && npm run build && cd ..
sudo systemctl restart fundworthy
```

---

## If something breaks

```bash
sudo journalctl -u fundworthy -n 100 --no-pager   # app logs
sudo tail -50 /var/log/nginx/error.log            # proxy logs
sudo systemctl restart fundworthy
```

| Symptom | Cause |
|---|---|
| Page never loads, no error | The **VM iptables** rules in step 2b. Almost always this. |
| 502 Bad Gateway | The app is not running — `systemctl status fundworthy` |
| The search cuts off after ~1 minute | nginx `proxy_read_timeout` — step 6 |
| The run log arrives all at once at the end | `proxy_buffering off` missing — step 6 |
| Sign-in says `auth/unauthorized-domain` | The hostname is not on Firebase's authorized-domains list — step 8a.3 |
| Signed in, but every page says "not on this install's allow-list" | `ALLOWED_EMAILS` — step 8b. Restart after editing. |
| The service will not start after step 8 | `journalctl -u fundworthy -n 30`. A half-configured sign-in is a refusal to boot, on purpose. |
| "Out of host capacity" | Oracle, not you. Retry or change shape. |

---

## Why this and not Vercel

Worth writing down, because it will be asked again.

Vercel runs **functions**, not servers: a **10-second** execution cap on the free tier
and an **ephemeral filesystem**. This app runs a **5–10 minute** crawl as a subprocess
and keeps everything in **SQLite on disk**. On Vercel the Re-run button would time out
and every setting, funder, and finding would vanish between requests.

A small always-on VM is the honest shape for this app — and Oracle's Always Free tier
means the thing the org inherits has no bill attached to it.
