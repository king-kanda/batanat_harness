# Batanat Agentic Harness

<img width="1660" height="878" alt="image" src="https://github.com/user-attachments/assets/a972695a-7180-4ac5-be93-c00836fd48a2" />


An operations assistant for energy-sector business development in Kenya. It does three things:

1. **Watches Gmail** and flags business opportunities.
2. **Scrapes government and parastatal procurement sites** for energy tenders, and reports.
3. **Reads Zoho CRM, and writes to it through an approval queue.**

It is one agent with three tool groups, not three agents. **What the agent can do depends on
what woke it up** — and that is enforced by handing the model a different tool schema per
trigger, not by a prompt instruction.

Live: https://batanat.okandasteven.me

---

## Quick start

```bash
make setup     # project-local venv, Python + Bun deps, .env from .env.example
make api       # http://localhost:8000  (docs at /docs when APP_ENV=local)
make web       # http://localhost:3000
```

The API creates its Postgres database at startup and migrates with Alembic, so there is no
manual provisioning step.

To see it working with no credentials at all:

```bash
make demo      # seeds a user, classified emails (one with a prompt injection), tenders,
               # a run with a full audit trail, and a pending approval. No external calls.
```

Other commands:

```bash
make sources   # probe every tender source live and print which ones work
make eval      # precision and recall from the 👍/👎 feedback
make types     # regenerate shared TS types + JSON Schema from the Pydantic contracts
make check     # lint → test → typecheck (everything CI runs)
make reset-db  # drop, re-migrate, re-seed
```

Dev credentials are `martin@batanat.com` / `batanat-dev`, shown on the login page in
development. The API refuses to start outside `APP_ENV=local` while that password is still set.

---

## Stack

| Layer | Choice |
|---|---|
| Frontend | TanStack Start + Router/Query, Bun, TypeScript, Tailwind v4, shadcn/ui |
| Backend | Python 3.12, FastAPI, LangGraph, Pydantic v2, uv |
| Model | Groq or OpenRouter (open weights, default); Anthropic also supported |
| Relational | PostgreSQL 16 — users, connections, runs, approvals, tenders, feedback, audit |
| Vectors | Qdrant — semantic memory and document vectors |
| Raw archive | MongoDB — raw email JSON, scraped HTML, raw tool responses |
| Queue / cache | Redis — sessions, scheduler broker, debounce windows, rate limits |

In development, Postgres, Mongo and Redis run on the host; Qdrant runs in a container.
`docker-compose.yml` is the alternative for a clean machine — it publishes non-default ports
(55432 / 57017 / 56379) so it cannot collide with host services.

**This project must never resolve GPU packages.** Embeddings come from
`qdrant-client[fastembed]` (ONNX, CPU) or an API provider — never `torch`,
`sentence-transformers`, `transformers` or `unstructured`. CI fails the build if either image
exceeds 1200MB, which is what CUDA arriving transitively looks like.

---

## The security model

| Trigger | Trust | Tools |
|---|---|---|
| Gmail push, tender cron | Untrusted | Read tools + `propose_crm_entry` |
| Web chat, paired WhatsApp | Trusted | The above + `commit_crm_write` |

Six invariants. If a change seems to require breaking one, stop and ask.

1. A trigger's trust level determines its tool set. The schema handed to the model genuinely differs.
2. Untrusted content never enters the system-prompt position — email bodies and scraped HTML are
   always rendered as delimited quoted data.
3. Every Zoho write passes through the approval queue, unless it comes from a trusted turn with
   explicit confirmation.
4. Every memory row carries a trust tag (`user_asserted`, `system_derived`, `untrusted_external`).
   Untrusted-derived memory is never injected as instruction.
5. Everything is idempotent, deduped with database-level unique constraints.
6. Every tool call is audit-logged with inputs, outputs, duration, cost and the active
   `skill_version_id`.

Age does not confer trust: a stored reply that quoted a scraped page is replayed still quoted.
Otherwise a thread becomes a laundering route — inject once, and later turns treat it as the
assistant's own words.

---

## Screens

| Route | What it is for |
|---|---|
| `/` | **Chat** — the front door. Opens with a summary of what is waiting |
| `/approvals` | The queue. Field-level diff, approve / reject / edit-then-approve |
| `/opportunities` | Opportunities from email and tenders, with 👍/👎 that feed `make eval` |
| `/rules` | Skill.MD editor — live validation, version history, rollback |
| `/audit` | Every run, expandable to each tool call, its cost and the Skill.MD version |
| `/memory` | View, search and delete memories; trust tag on every row |
| `/onboarding` | Five-step checklist derived from what is actually configured |
| `/settings/connections` | Gmail, Zoho, WhatsApp pairing, and a "send test" per channel |
| `/settings/sources` | Source health, the schedule, and adding your own sites |
| `/settings/reports` | Report recipients — one row per address, To or Cc, with a test send |
| `/settings/knowledge` | Upload PDFs and text into semantic memory |
| `/settings/rules-assistant` | Talk through your criteria; it drafts, you publish |

Chat is threaded and persisted. The thread lives in `?c=<id>`, so switching conversations is
navigation — Back works, and a thread can be pasted to someone. WhatsApp and the web app share
threads within 12 hours.

---

## How relevance works

**Tenders — two layers, cheap first.** The national portal covers every procuring entity in
Kenya, so most of what we ingest is classrooms and fencing. Keyword triage scores everything at
ingest; the model only sees the ambiguous band, batched 40 titles per call, with your Skill.MD
attached. A confident keyword verdict is never overturned.

The store keeps everything and the report filters — a scoring rule that wrongly drops a real lead
is invisible if the row was never saved. Off-sector tenders are one toggle away on
`/opportunities`, and the report email says how many were withheld.

**Email — entirely Skill.MD's call.** `classify_email` validates the verdict against the enum and
stores it; the judgement is the model's, against your written criteria. Write "brand deals are
opportunities" and that is what gets marked, with no code change. Tender relevance is the rigid
one on purpose; email relevance is meant to move.

---

## WhatsApp

A chat interface, not just an alert channel. A paired handset can ask anything the web app can.
Two things it deliberately cannot do:

- **Commit a CRM write by talking.** `approve_pending` and `commit_crm_write` are absent from its
  schema. `APPROVE 2` still works — it is parsed before the model runs.
- **Act unattributed.** An unpaired number gets a generic reply and nothing else. Senders map to
  users by pairing code, never by trusting the phone number.

**The 24-hour window is the operational catch.** Free-form messages only send within 24 hours of
the user's last inbound message; outside it Meta rejects the send and an alert silently does not
arrive. The UI says so on the WhatsApp tab. Approved templates are the real fix and need Meta
approval before launch.

---

## Configuration

**Model provider** — `LLM_PROVIDER` selects one; switching is an env change. Set `AGENT_MODEL` to
override the default.

| Value | Default model | Key |
|---|---|---|
| `groq` *(default)* | `llama-3.3-70b-versatile` | `GROQ_API_KEY` |
| `openrouter` | `meta-llama/llama-3.3-70b-instruct` | `OPENROUTER_API_KEY` |
| `anthropic` | `claude-opus-5` | `ANTHROPIC_API_KEY` |

Tool schemas differ between Anthropic and OpenAI formats; `agent/providers.py` translates them and
tests assert the translation is one-to-one, since a tool that changed shape in translation would
change what a run can do. Smaller open models emit malformed tool-call JSON more often — the
runner records a validation error and retries, so expect more iterations per run.

**Scheduler** — `ENABLE_SCHEDULER=true` registers three APScheduler jobs in `SCHEDULER_TIMEZONE`.
Off by default so a one-off script never starts cron jobs.

| Job | When | What |
|---|---|---|
| `tender_daily` | 11:00, 17:00 | Scrape → filter → report → notify |
| `tender_weekly` | 08:00 Monday | Same, 72-hour lookback |
| `maintenance` | 02:00 | Token refresh, Gmail watch renewal, expiring stale approvals |

The 02:00 job matters more than it sounds: it renews the Gmail watch, which Google expires every
7 days. Without it, email quietly stops arriving after a week.

**Sessions** — an opaque token in Redis behind an HttpOnly cookie, so signing out actually ends
the session. Passwords use `hashlib.scrypt` from the standard library, with parameters stored
alongside the hash so the cost can be raised later.

`SESSION_COOKIE_SAMESITE` defaults to `lax`, which requires the API and web app to share a
registrable domain. Split them and the browser silently stops sending the cookie — every request
arrives unauthenticated with nothing in the logs to say why. Set it to `none` when they genuinely
cannot (two ngrok tunnels are the common case, since `ngrok-free.app` is on the Public Suffix
List). `none` re-opens CSRF and the mutating endpoints have no token protection, so prefer
sharing a domain in production.

---

## Repository layout

```
apps/
  api/                    FastAPI app, agent runtime, tools
    src/batanat_api/
      contracts/          Pydantic models — source of truth for shared types
      core/               logging, run-id correlation, middleware, db bootstrap
  web/                    TanStack Start app (file-based routes in src/routes/)
packages/
  schema/                 generated TS types + JSON Schema, consumed by the web app
```

The generated schema files are committed so a fresh clone typechecks without running Python.
CI fails if they are stale — run `make types` after changing a contract.

Every unit of work carries a `run_id` that flows into every log line, is echoed in the
`x-run-id` response header, and is what the audit screen keys on. Logs are one JSON object per
line on stdout. Secrets are redacted in the logging processor, not at the call site.

---

## Deployment

`.github/workflows/deploy.yml` builds both images, pushes to Docker Hub, then deploys over SSH by
pulling the new tags on the server. It depends on `ci.yml`, so nothing publishes from a commit
that did not pass. Needs `DOCKER_HUB_TOKEN` and the SSH key in repo secrets.

- Every image gets an immutable `:api-<sha>` alongside the moving `:api` — a pipeline that only
  pushes the moving tag has nothing to roll back *to*.
- `VITE_API_URL` is compiled into the browser bundle, so one image is tied to one API origin.
  A staging image cannot be promoted to production.
- `docker-compose.prod.yml` runs `web`, `api`, `scheduler` and `qdrant`. Postgres, Mongo, Redis
  and nginx belong on the host. The scheduler is a **separate service** with
  `ENABLE_SCHEDULER=true` while the API has it false — the cron jobs are not distributed-safe,
  and two schedulers means two sweeps and two sets of model calls.

---

## Known constraints

- **Gmail runs in OAuth "Testing" mode**, so refresh tokens expire after ~7 days. The UI surfaces
  `access_expires_at` and a "reconnect needed" state. The fix is OAuth verification plus a
  security assessment.
- **Reports go out via SendGrid, not Gmail.** The Gmail scope is `gmail.readonly` by design, so
  the agent can never send from the inbox it reads. Recipients are per-user under Settings, with
  no environment fallback, and that endpoint sits outside the capability table — nothing a run
  reads can change where a report lands.
- **Zoho data-centre mismatch is the most common integration failure.** `api_domain` and
  `accounts_url` come from the token response and are persisted per connection; `zohoapis.com`
  is never hardcoded.
- **Two of five scrapers are down.** As of 2026-08-24: PPIP works through its public JSON API
  (~310 tenders, and as the national portal it makes the others largely redundant), REREC serves
  a plain table (~157), KETRACO works via a fallback URL. KPLC and KenGen render client-side and
  yield nothing — marked degraded, covered by PPIP and the Tavily fallback. Run `make sources`
  for today's truth rather than trusting this paragraph.
- **KPLC's robots.txt disallows named AI crawlers** while allowing `User-agent: *` with
  `Content-Signal: use=reference`. Our scraper declares its own identity, is not one of the named
  crawlers, does not train on the content, and fetches public procurement notices for reference.
  Disable that source row if you would rather not fetch it.
- **Use weekday names in cron expressions, not numbers.** APScheduler counts from Monday=0 while
  crontab counts from Sunday=0, and `CronTrigger.from_crontab` does not remap — `0 8 * * 1` fires
  on Tuesday. A test rejects numeric weekdays in the configured expressions.

---

## Roadmap

In the order I would spend on it.

- **The two remaining scrapers.** Look for JSON endpoints first — that is how PPIP was solved.
  Headless browser only as a fallback; it costs ~400MB and a new class of flakiness.
- **Multi-user.** Every table is keyed by `user_id`, but there is no invite flow. The shape is
  right; the surface is missing.
- **A real queue.** Runs happen inline in the request or cron tick — fine at this volume, wrong at
  ten times it. Celery or arq on the existing Redis.
- **Classification cost.** Every new email goes to the model. A sender allowlist, keyword
  prefilter and thread deduplication would cut that substantially.
- **The Skill.MD validator.** Regex heuristics guarding something no security decision reads.
  Make it a warning, or replace it with a structured editor.
- **Observability beyond logs.** No place to see cost-per-run trending up, or a source quietly
  degraded for a week.
- **Test isolation for the network.** `make sources` hits live sites. Recorded cassettes would
  catch source regressions in CI.
