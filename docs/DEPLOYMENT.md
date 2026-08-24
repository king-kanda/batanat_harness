# Deploying to a VM

The split this targets:

| Runs in Docker | Runs on the host |
|---|---|
| `web` (Nitro server) | PostgreSQL 16 |
| `api` (FastAPI) | MongoDB |
| `scheduler` (cron jobs) | Redis |
| `qdrant` | nginx |

Two things are worth understanding before you start, because both cause failures
that look like something else.

**`ENABLE_SCHEDULER` belongs to exactly one container.** The cron jobs are not
distributed-safe. Two schedulers means two tender sweeps and two report emails —
the notification dedupe key stops the second *send*, but not the second scrape or
the second set of model calls. `docker-compose.yml` sets it `false` on `api` and
`true` on `scheduler` for this reason. If you scale the API, scale only the API.

**`VITE_API_URL` is compiled into the browser bundle.** It is not read at runtime.
Setting it as a container environment variable does nothing at all — the JavaScript
already contains whatever value was present when the image was built. One image is
tied to one API origin, and a staging image cannot be promoted to production unless
both point at the same API.

---

## 1. Host packages

Ubuntu 22.04 or 24.04.

```bash
sudo apt update
sudo apt install -y \
  postgresql postgresql-contrib \
  redis-server \
  nginx \
  ca-certificates curl gnupg
```

MongoDB is not in Ubuntu's default repositories:

```bash
curl -fsSL https://www.mongodb.org/static/pgp/server-7.0.asc \
  | sudo gpg -o /usr/share/keyrings/mongodb-server-7.0.gpg --dearmor
echo "deb [ signed-by=/usr/share/keyrings/mongodb-server-7.0.gpg ] https://repo.mongodb.org/apt/ubuntu jammy/mongodb-org/7.0 multiverse" \
  | sudo tee /etc/apt/sources.list.d/mongodb-org-7.0.list
sudo apt update && sudo apt install -y mongodb-org
sudo systemctl enable --now mongod
```

Docker:

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"   # log out and back in for this to take effect
```

---

## 2. Host datastores

### PostgreSQL

The API creates its own database at startup, so the role only needs `CREATEDB`.

```bash
sudo -u postgres psql -c "CREATE ROLE batanat LOGIN PASSWORD 'CHANGE_ME' CREATEDB;"
```

Containers reach the host through the Docker bridge, so Postgres has to listen on
more than loopback — and the moment it does, it must not be reachable from the
internet:

```bash
# /etc/postgresql/16/main/postgresql.conf
listen_addresses = 'localhost,172.17.0.1'
```

```bash
# /etc/postgresql/16/main/pg_hba.conf — the Docker bridge only, never 0.0.0.0/0
host    all    batanat    172.16.0.0/12    scram-sha-256
```

```bash
sudo systemctl restart postgresql
```

### Redis and MongoDB

Same shape: bind to loopback plus the bridge, and firewall the rest.

```bash
# /etc/redis/redis.conf
bind 127.0.0.1 172.17.0.1
requirepass CHANGE_ME
```

```yaml
# /etc/mongod.conf
net:
  bindIp: 127.0.0.1,172.17.0.1
security:
  authorization: enabled
```

```bash
mongosh --eval 'db.getSiblingDB("admin").createUser({user:"batanat",pwd:"CHANGE_ME",roles:["root"]})'
sudo systemctl restart redis-server mongod
```

### Close the ports from outside

Binding to the bridge is not a firewall. Do both.

```bash
sudo ufw default deny incoming
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw enable
```

Ports 5432, 6379, 27017 and 6333 are never exposed publicly. Nothing outside the
VM should reach them.

---

## 3. Application

```bash
sudo mkdir -p /srv/batanat && sudo chown "$USER" /srv/batanat
cd /srv/batanat
git clone <your-repo> .
cp .env.example .env
```

Fill in `.env`. Every value is documented there; these are the ones that must be
right for a VM rather than a laptop:

```bash
APP_ENV=production
API_PUBLIC_URL=https://api.batanat.okandasteven.me
WEB_PUBLIC_URL=https://batanat.okandasteven.me
CORS_ORIGINS=https://batanat.okandasteven.me
VITE_API_URL=https://api.batanat.okandasteven.me

# Both subdomains of one registrable domain, so the session cookie works.
SESSION_COOKIE_SAMESITE=lax

# Containers reach host services through the bridge, not localhost.
DATABASE_URL=postgresql://batanat:CHANGE_ME@172.17.0.1:5432/batanat
REDIS_URL=redis://:CHANGE_ME@172.17.0.1:6379/0
MONGO_URL=mongodb://batanat:CHANGE_ME@172.17.0.1:27017
QDRANT_URL=http://qdrant:6333    # the one datastore in Docker

ENABLE_SCHEDULER=true            # read by the scheduler container only
CRM_DRY_RUN=true                 # leave on until you have watched one approval
```

Generate the two secrets rather than inventing them:

```bash
python3 -c "from cryptography.fernet import Fernet; print('TOKEN_ENCRYPTION_KEY=' + Fernet.generate_key().decode())"
python3 -c "import secrets; print('SESSION_SECRET=' + secrets.token_urlsafe(48))"
```

`APP_ENV=production` makes the API **refuse to start** if `DEFAULT_USER_PASSWORD`
is still `batanat-dev`, or if either secret is empty. That is deliberate: a default
password that ships is not a default, it is a backdoor.

### Start it

```bash
docker compose --profile app pull       # or: build, if not using Docker Hub
docker compose --profile app up -d
```

Order is handled for you — `migrate` runs once to completion before `api` and
`scheduler` start. It is a separate one-shot service rather than an API entrypoint
because migrating on boot with more than one replica means racing migrations.

Verify the split is right:

```bash
docker compose --profile app ps
docker compose logs scheduler | grep scheduler.started   # exactly one
docker compose logs api       | grep scheduler.started   # must be empty
```

---

## 4. Seeding

```bash
# Creates the account, the five tender sources, and the starter Skill.MD.
docker compose --profile app run --rm api python -m batanat_api.db.seed
```

Then change the password immediately — the seeded one is a development default
and the login screen will tell you so:

```bash
docker compose --profile app run --rm api python -c "
import asyncio
from sqlalchemy import select
from batanat_api.db.session import session_scope
from batanat_api.db.models import User
from batanat_api.security.passwords import hash_password

async def main():
    async with session_scope() as s:
        user = (await s.execute(select(User))).scalars().first()
        user.password_hash = hash_password('YOUR-REAL-PASSWORD')
        user.must_change_password = False
        await s.commit()
        print('password set for', user.email)

asyncio.run(main())
"
```

Optional, and safe to undo:

```bash
# Worked example — four classified emails (one carrying a prompt injection),
# tenders, a run with a full audit trail, a pending approval.
docker compose --profile app run --rm api python -c "
import asyncio
from sqlalchemy import select
from batanat_api.db.session import session_scope
from batanat_api.db.models import User
from batanat_api.demo.fixtures import load_demo_data

async def main():
    async with session_scope() as s:
        uid = (await s.execute(select(User.id))).scalars().first()
        print(await load_demo_data(s, uid))
        await s.commit()

asyncio.run(main())
"
```

Demo data is also loadable and clearable from Settings → Onboarding, which is the
easier path. Clearing is bounded by a ledger of exactly what the seeder created,
so real scraped tenders cannot be caught by it.

---

## 5. nginx and TLS

Two server blocks: the app and the API. They must be subdomains of one registrable
domain or the session cookie stops being sent — see `SESSION_COOKIE_SAMESITE`.

```nginx
# /etc/nginx/sites-available/batanat
server {
    server_name batanat.okandasteven.me;

    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}

server {
    server_name api.batanat.okandasteven.me;

    # Report emails and scrapes are slow; the default 60s cuts a tender sweep
    # off mid-run and returns a 504 for work that was going to succeed.
    proxy_read_timeout 300s;

    # Meta signs the WhatsApp webhook over the raw body. Anything that rewrites
    # or buffers it differently breaks signature verification, which surfaces as
    # 401s that look like a credential problem.
    client_max_body_size 25m;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/batanat /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
```

`X-Forwarded-For` is not cosmetic: the login rate limiter keys on client address,
and without it every attempt appears to come from the proxy — so one attacker
locks out everybody.

### Certificates

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx \
  -d batanat.okandasteven.me \
  -d api.batanat.okandasteven.me
```

Certbot rewrites both blocks for TLS and installs a renewal timer. Check it:

```bash
sudo certbot renew --dry-run
```

TLS is not optional here. `SESSION_COOKIE_SAMESITE` aside, the session cookie is
issued `Secure` whenever `API_PUBLIC_URL` is not localhost — over plain HTTP the
browser discards it and every request arrives unauthenticated.

---

## 6. External callbacks

Each of these must match `API_PUBLIC_URL` byte for byte.

| Where | Value |
|---|---|
| Google Cloud → Authorized redirect URIs | `https://api.batanat.okandasteven.me/api/connections/gmail/callback` |
| Zoho API console → Authorized Redirect URIs | `https://api.batanat.okandasteven.me/api/connections/zoho/callback` |
| Meta → WhatsApp webhook | `https://api.batanat.okandasteven.me/api/webhooks/whatsapp` |
| Google Pub/Sub → push endpoint | `https://api.batanat.okandasteven.me/api/webhooks/gmail` |

The OAuth redirect URIs are **derived** from `API_PUBLIC_URL`, so moving the API is
one edit. `GOOGLE_REDIRECT_URI` and `ZOHO_REDIRECT_URI` exist only as overrides for
a proxy or vanity host the API cannot infer; leave them blank.

---

## 7. Verify

```bash
curl -fsS https://api.batanat.okandasteven.me/api/health | jq
```

Then sign in and check, in this order:

1. **The login screen build stamp.** `web <sha>` and `api <version>` on two lines.
   A mismatch means one of them did not roll.
2. **Settings → Sources & schedule.** Three jobs with next fire times. If it says
   the scheduler is off, the `scheduler` container is not running.
3. **Settings → Connections.** Connect Gmail and Zoho; both should say "renews
   automatically".
4. **Settings → Report recipients.** Add an address and press *Send test email*.
   SendGrid only fails at send time — an unverified sender looks fine until you try.
5. **WhatsApp → Send test.** Note the 24-hour window: outside it, sends are
   rejected until your templates are approved.

Only then set `CRM_DRY_RUN=false`, and only after watching one approval execute in
dry run and reading the payload it would have written.

---

## Operations

```bash
# What is running
docker compose --profile app ps

# Follow one service
docker compose logs -f scheduler

# Deploy a new build
docker compose --profile app pull
docker compose --profile app run --rm migrate      # migrations first, once
docker compose --profile app up -d api scheduler web

# Roll back — this is why images carry an immutable :api-<sha> tag
API_IMAGE=docker.io/niloticking/batanat:api-1a2b3c4 \
WEB_IMAGE=docker.io/niloticking/batanat:web-1a2b3c4 \
  docker compose --profile app up -d
```

### Backups

Only Postgres holds anything you cannot rebuild. Qdrant vectors regenerate from
the documents, and Mongo is a raw-payload archive.

```bash
sudo -u postgres pg_dump batanat | gzip > "/var/backups/batanat-$(date +%F).sql.gz"
```

### The failure worth watching for

Gmail's `users.watch` expires every 7 days and is renewed by the 02:00 maintenance
job. If the `scheduler` container is down, push notifications stop after a week and
**the only symptom is that email quietly stops arriving** — no error, no alert.
`docker compose logs scheduler | grep maintenance` is the check.
