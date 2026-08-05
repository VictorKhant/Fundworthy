# Getting access to the running system

Fundworthy is live at **https://$HOST** on an Oracle free-tier VM (`$VM_IP`). One person
set that up, which means one person can currently fix it. This document exists to end
that.

> **`$HOST`, `$VM_IP` and `$FIREBASE_PROJECT` are placeholders**, the same convention
> [DEPLOY-ORACLE.md](DEPLOY-ORACLE.md) uses. This repository is public, and while none of
> those three is a secret, publishing a live box's address invites the scanning you would
> rather not attract. Get the real values from whoever deployed it — `$HOST` is on the
> tin, and the other two come out of `.env` on the VM:
>
> ```bash
> ssh fundworthy 'grep FIREBASE_PROJECT_ID ~/Rise-Fund-Finder/.env'
> curl -s https://$HOST/api/auth/config      # project_id, once you know the host
> ```

> **Read this as a bus-factor problem, not a paperwork problem.** Five separate accounts
> control the running service, and they are not the same account. If the person holding
> them is unreachable — asleep, on a plane, or simply done with the project — nobody can
> restart the service, renew the certificate, add a user, or rotate the API key. That is
> the single largest operational risk in the project right now, and it is larger than any
> bug in the code.

---

## What actually exists, and what each thing controls

| # | Thing | Controls | Losing access means |
|---|---|---|---|
| 1 | **SSH to the VM** | The app, `.env`, the database, systemd, nginx | Cannot deploy, restart, add a user, or read a log |
| 2 | **Oracle Cloud console** | The VM itself, firewall rules, reboot, snapshots | Cannot recover a VM that will not boot |
| 3 | **Firebase project `$FIREBASE_PROJECT`** | Who can sign in at all | Cannot fix a broken login |
| 4 | **DuckDNS account** | The hostname → IP mapping | The domain points nowhere if the IP changes |
| 5 | **Anthropic account** | The API key that pays for every run | Cannot rotate a leaked key or see the bill |

You need all five. Below is each one, in the order that matters.

---

## 1 · SSH to the VM

There are two ways to do this. **Take path A.**

### Path A — your own key (do this)

Your key stays yours; nobody has to send a secret over Slack; and if you ever leave, one
line gets deleted instead of a key being rotated for everybody.

**Step 1 — make a key dedicated to this box.** Run this yourself; it will prompt for a
passphrase, and you should set one.

```bash
ssh-keygen -t ed25519 -f ~/.ssh/fundworthy_vm -C "phyo@fundworthy-vm"
```

That writes two files. `~/.ssh/fundworthy_vm` is **secret and never leaves your machine**.
`~/.ssh/fundworthy_vm.pub` is the one you share — a public key is designed to be public.

**Step 2 — send your friend the public key.**

```bash
cat ~/.ssh/fundworthy_vm.pub | pbcopy    # now in your clipboard
```

Send them the message in [the template below](#the-message-to-send).

**Step 3 — they run this on the VM** (it is one command, and it is safe — it appends,
never overwrites):

```bash
echo 'PASTE-PHYOS-PUBLIC-KEY-HERE' >> ~/.ssh/authorized_keys
```

**Step 4 — add a shortcut so you never type the IP.** Append to `~/.ssh/config`:

```
Host fundworthy
    HostName $VM_IP
    User ubuntu
    IdentityFile ~/.ssh/fundworthy_vm
    IdentitiesOnly yes
```

`IdentitiesOnly yes` matters once you have a few keys in `~/.ssh`: without it SSH offers
them one at a time and can hit the server's `MaxAuthTries` limit before reaching the right
one — which fails as "Too many authentication failures", not as anything informative.

**Step 5 — connect.**

```bash
ssh fundworthy
```

The first connection asks you to confirm a host fingerprint. Say yes.

### Path B — they send you the Oracle private key

Oracle generated a `.key` file at VM-creation time and your friend downloaded it. They
could send you that file. It works immediately and requires nothing from you.

It is worse, and worth knowing why: a private key sent through a chat app now exists in
that app's history and its backups; you and they become indistinguishable in the logs;
and revoking your access means rotating the key for everyone. Use this only if you are
blocked on something urgent, and treat it as temporary — then do path A properly.

If you do take it:

```bash
mv ~/Downloads/ssh-key-*.key ~/.ssh/fundworthy_vm
chmod 600 ~/.ssh/fundworthy_vm        # SSH refuses to use a world-readable key
```

### Once you are in — the five commands worth knowing

```bash
sudo systemctl status fundworthy         # is it alive
sudo journalctl -u fundworthy -n 50      # what did it say
sudo systemctl restart fundworthy        # turn it off and on again
nano ~/Rise-Fund-Finder/.env             # the config, incl. who may sign in
cd ~/Rise-Fund-Finder && git log --oneline -3   # what version is actually deployed
```

> **Careful with the last one.** Check what is deployed before you change anything. The
> box may not be on the same commit as your laptop.

---

## 2 · Oracle Cloud console

SSH gets you into the machine. It does **not** let you reboot a machine that has stopped
responding, change the cloud firewall, or rebuild a VM that will not boot. That is the
console, and it is a separate login.

Oracle's access model is genuinely awkward here: an Oracle Cloud tenancy invites users by
email into the tenancy's Identity Domain, not by simple sharing.

**Ask your friend to:** Oracle Cloud console → **Identity & Security → Domains → Default
domain → Users → Create user**, with your email. Then **Groups → Administrators → Add
user**. You will get an email to set a password and enrol in MFA.

**What to record when they do it** — you cannot log in without all three:

- The **tenancy name** (or the direct console URL, which contains it)
- The **home region** — likely `us-sanjose-1` or `us-phoenix-1`
- Your username, which is usually the email address

> If they would rather not add a second admin to a cloud account with a card attached to
> it, that is a reasonable position — but then get the VM's OCID and region written down
> somewhere you can both reach, and accept that VM-level recovery is a single-person
> dependency until it changes.

---

## 3 · Firebase (project `$FIREBASE_PROJECT`)

This controls **who can sign in**. Note there are two different things here, and people
conflate them:

| | |
|---|---|
| **Firebase console access** | Lets you manage the auth provider and authorized domains. Granted in the console. |
| **`ALLOWED_EMAILS`** | Decides who may actually use the app. Lives in `.env` on the VM, **not** in Firebase. |

Firebase authenticates any Google account on earth; the allow-list is what keeps everyone
else out. So adding yourself to Firebase does **not** get you into the app, and adding
yourself to `ALLOWED_EMAILS` does not get you into Firebase. You want both.

**Ask your friend to:** console.firebase.google.com → project **$FIREBASE_PROJECT** → ⚙
**Project settings → Users and permissions → Add member** → your Google address → role
**Owner**.

Owner, not Editor: Editor cannot manage members, so with Editor you would still have to
ask them every time somebody new joins — which is the dependency you are trying to remove.

You will get an email invitation. Accept it with the **same Google account** you use for
everything else on this project, or you will end up with two identities and confuse
yourself later.

**To add yourself to the app itself** (after you have SSH):

```bash
nano ~/Rise-Fund-Finder/.env      # append your address to ALLOWED_EMAILS, comma-separated
sudo systemctl restart fundworthy # it is only read at startup
```

Then confirm it took:

```bash
sudo journalctl -u fundworthy -n 20 | grep -i "sign-in"
# INFO app.auth: Sign-in is on. Firebase project $FIREBASE_PROJECT, N address(es) allowed.
```

The count going up by one is the confirmation. If the service refuses to start, the
reason is in `journalctl` — an empty `ALLOWED_EMAILS` is a deliberate refusal to boot, not
a crash.

---

## 4 · DuckDNS

`$HOST` is a free dynamic-DNS subdomain, controlled by whichever account
claimed it. It is one token, and it maps the hostname to `$VM_IP`.

**Ask your friend for:** the DuckDNS account (it signs in with Google/GitHub) or, at
minimum, the **DuckDNS token** for that subdomain, stored somewhere you can both reach.

Two things worth knowing now rather than during an outage:

- If the VM's public IP ever changes, **the site goes down until someone updates DuckDNS**
  — and the HTTPS certificate renewal fails along with it, because certbot proves domain
  ownership over HTTP.
- A free DuckDNS subdomain can be lost through inactivity. It is fine for a pilot. It is
  not what you want under a real nonprofit's weekly workflow, and moving to a ~$10/yr
  domain later means a certbot re-run and a Firebase authorized-domain change.

---

## 5 · Anthropic

Whoever owns this key owns the bill, and right now **every org's runs spend it**. Get:

- Access to the Anthropic console account, or at least confirmation of who owns it
- Whether there is a **spend limit** set on the account (if not, set one today — it is the
  only hard ceiling that survives a bug in our budget logic)
- The ability to **rotate the key**, which is what you do the moment you suspect a leak

---

## The message to send

Copy this, fill in the two blanks, send it:

> Hey — I need my own access to the Fundworthy box so you are not the only one who can
> fix it. Four things, ~10 minutes total:
>
> **1. SSH.** Here is my public key (it is public, safe to paste anywhere):
> ```
> <paste the output of: cat ~/.ssh/fundworthy_vm.pub>
> ```
> On the VM, run:
> ```
> echo 'THE-KEY-ABOVE' >> ~/.ssh/authorized_keys
> ```
>
> **2. Firebase.** console.firebase.google.com → $FIREBASE_PROJECT → ⚙ Project settings →
> Users and permissions → Add member → `<your google address>` → **Owner**.
>
> **3. Oracle Cloud console.** Identity & Security → Domains → Default domain → Users →
> Create user with my email, then add me to the Administrators group. Also send me the
> tenancy name and the home region — I cannot log in without those.
>
> **4. DuckDNS + Anthropic.** Which account owns `$HOST`, and which
> account owns the Anthropic API key? If there is no spend limit set on the Anthropic
> account, please set one — right now a bug in our code could spend the whole balance.
>
> Also: is there a spend limit set, and is anything backing up `data/rise.db` and
> `data/.fernet-key`? If the VM dies today I want to know what we lose.

---

## Check you actually have everything

Run these. All five should succeed.

```bash
ssh fundworthy 'systemctl is-active fundworthy'        # active
ssh fundworthy 'grep -c . ~/Rise-Fund-Finder/.env'     # a number, i.e. you can read config
curl -s https://$HOST/api/health      # {"ok":true}
curl -s -o /dev/null -w '%{http_code}\n' \
     https://$HOST/api/state          # 401 — the gate is up
```

Plus, in a browser: sign in at https://$HOST with your Google account and
land on the dashboard rather than an allow-list refusal.

If the last one fails with *"not on this install's allow-list"*, sign-in works and you are
simply not listed yet — see §3.
