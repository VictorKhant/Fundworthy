# Deploying to an Oracle Cloud free-tier VM

Copy-paste, in order. Roughly **60–90 minutes** the first time, most of it waiting.

Do this **after** the demo, not before — several steps can fail for reasons outside your
control (capacity errors, card verification), and none of them are things you want to
discover with an audience.

> **Read this first — the order is forced.**
> Google sign-in needs a redirect URI that exactly matches your deployed address. So you
> cannot configure OAuth until the VM exists and has a hostname. The sequence is
> **VM → app running → HTTPS → *then* Google sign-in.** Doing OAuth against `localhost`
> first is work you throw away.

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
RISE_STRICT_CONFIG=0
EOF
chmod 600 .env
```

Smoke-test it before wiring anything else up:

```bash
.venv/bin/python -m pytest tests/ -q          # expect 136 passed
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
Description=Fundworthy — RISE funding researcher
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

## Step 8 · Google sign-in

> ⚠️ **Do not skip this.** The app now stores an Anthropic API key and is reachable from
> the internet. Without a login, anyone who finds the URL can spend RISE's money. This is
> prerequisite #1 in `HANDOFF.md`.

### 8a. Configure the Google side

1. **console.cloud.google.com** → new project, e.g. `fundworthy`.
2. **APIs & Services → OAuth consent screen**:
   - User type **External**
   - App name `Fundworthy`, support email = the shared Gmail
   - Scopes: just `openid`, `email`, `profile` — you need nothing else
   - **Test users:** add the shared Gmail **and Mauri's email**
   - Leave it in **Testing**. Publishing triggers Google verification, which takes days
     to weeks. Testing mode allows up to 100 named users, which is the right size here.
3. **Credentials → Create credentials → OAuth client ID**:
   - Type **Web application**
   - **Authorized redirect URI:** `https://your-host/auth/callback` — exactly, including
     `https` and no trailing slash
4. Copy the **Client ID** and **Client secret**.

### 8b. The server side

This is **not built yet** — `dashboard/src/auth.js` is deliberately a stub, and
`AUTH_ENABLED` is a build flag with no backend behind it. What has to be added:

```bash
.venv/bin/pip install authlib itsdangerous
```

- a session middleware with a random `SESSION_SECRET`
- `GET /auth/login` → redirect to Google
- `GET /auth/callback` → exchange the code, check the email is on an allow-list, set the
  session cookie
- a dependency on every `/api/*` route that returns **401** without a session
- an `ALLOWED_EMAILS` env var — Google authenticates *who* someone is; it does not decide
  whether they are allowed in. Without an allow-list, any Google account can sign in.

Add to `.env`:

```bash
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
SESSION_SECRET=$(openssl rand -hex 32)
ALLOWED_EMAILS=mauri@risesandiego.org,the-shared-gmail@gmail.com
```

Then rebuild the front end with auth on:

```bash
cd dashboard && VITE_SHOW_AUTH=1 npm run build && cd ..
sudo systemctl restart fundworthy
```

**Budget 2–3 hours for 8b**, not 30 minutes. It is the piece with the most ways to fail
quietly — a redirect URI that differs by a trailing slash, a cookie that will not set
without `secure`, a session that vanishes behind the proxy.

---

## Step 9 · Hand it over

```bash
sudo systemctl status fundworthy --no-pager   # active (running)
sudo certbot renew --dry-run                  # renewal works
```

- Back up **`data/rise.db`** and **`data/.fernet-key`** somewhere private. That is her
  settings, funders, findings, and the encrypted key. Losing it loses everything.
- Give Mauri the URL and `docs/handoff/Fundworthy-guide-for-RISE.pdf`.
- Put a name against the API key.

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
| Google sign-in says `redirect_uri_mismatch` | The URI in the console differs from what the app sends. They must match character for character. |
| "Out of host capacity" | Oracle, not you. Retry or change shape. |

---

## Why this and not Vercel

Worth writing down, because it will be asked again.

Vercel runs **functions**, not servers: a **10-second** execution cap on the free tier
and an **ephemeral filesystem**. This app runs a **5–10 minute** crawl as a subprocess
and keeps everything in **SQLite on disk**. On Vercel the Re-run button would time out
and every setting, funder, and finding would vanish between requests.

A small always-on VM is the honest shape for this app — and Oracle's Always Free tier
means the thing RISE inherits has no bill attached to it.
