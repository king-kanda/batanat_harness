# Build Prompt — Batanat Agentic Harness

> This is the product requirements document for the project, as supplied. It is the
> specification of record; `README.md` documents what has actually been built, and
> `TODO.md` tracks what is still needed from the client.

---

## Context

You are building an agentic operations assistant for a director at an energy company in Kenya. It does three jobs:

1. Watches his Gmail and alerts him to business opportunities.
2. Scrapes Kenyan government and parastatal sites twice daily for energy tender opportunities and sends a report.
3. Reads and writes his Zoho CRM.

It is **one agent with three tool groups**, not three agents. Capabilities are bound per trigger — this is the core security property of the system and must not be compromised for convenience.

## Rules of engagement

- **Stop at the end of every phase.** Print what you built, what you skipped, and what you need from me. Do not start the next phase until I say go.
- Do not build ahead. If a later phase would be easier to do now, say so and wait.
- Every phase must end with the app running and the acceptance criteria demonstrably met.
- No secrets in the repo. `.env.example` only, with every key documented.
- Write tests for the capability resolver, the validator, and all dedupe logic. Everything else is best-effort.
- Prefer boring, explicit code. This will be read by a prospective client.
- When an external API's behaviour is uncertain, write the integration behind an interface and stub it, then flag it for me to verify with real credentials.
- Commit at the end of each phase with a clear message.

## Stack

**Frontend** — TanStack Start + TanStack Query/Router, Bun as runtime and package manager, TypeScript, Tailwind, shadcn/ui, lucide-react.

**Backend** — Python 3.12, FastAPI, LangGraph, Pydantic v2, uv or poetry.

**Data** — PostgreSQL (relational: users, connections, runs, approvals, tenders, feedback, audit), Qdrant (semantic memory + document vectors), MongoDB (raw payload archive only: raw email JSON, scraped HTML snapshots, raw tool responses — schemaless blobs we may reparse later).

**Infra** — Docker Compose for local (postgres, qdrant, mongo, redis), APScheduler or Celery beat for cron, ngrok for webhook development.

Do not add dependencies beyond this without asking.

### CPU-only constraint

This project must never resolve GPU packages. LangGraph itself is pure Python and harmless — CUDA arrives transitively via `torch`, which is pulled in by `sentence-transformers`, `transformers`, `langchain-huggingface`, or `unstructured`. That is ~2.5GB of wheels this project will never execute.

- **Do not install** `torch`, `sentence-transformers`, `transformers`, or `unstructured`.
- **For embeddings** use `qdrant-client[fastembed]` (ONNX, CPU, ~100MB) or an API embedding provider (Gemini, Voyage, OpenAI). Never a local torch-backed model.
- If any dependency transitively pulls `nvidia-*`, `triton`, or `cuda*`, **stop and ask**. Do not work around it by accepting the install.
- If `torch` ever becomes genuinely unavoidable, pin the CPU index explicitly:

  ```toml
  [[tool.uv.index]]
  name = "pytorch-cpu"
  url = "https://download.pytorch.org/whl/cpu"
  explicit = true

  [tool.uv.sources]
  torch = { index = "pytorch-cpu" }
  torchvision = { index = "pytorch-cpu" }
  ```

- Base images are `python:3.12-slim`. Never a CUDA base image.
- Set `CUDA_VISIBLE_DEVICES=""` in the container environment as a runtime guard.

## Architecture invariants

These are non-negotiable. If a phase seems to require breaking one, stop and ask.

1. **A trigger's trust level determines its tool set.** Untrusted triggers (Gmail push, tender cron) get read tools and `propose_crm_entry`. Only trusted triggers (web chat, verified WhatsApp) get `commit_crm_write`. The tool schema handed to the model must genuinely differ — not a prompt instruction, not a runtime check inside the tool.
2. **Untrusted content never enters the system-prompt position.** Email bodies and scraped HTML are rendered as clearly delimited quoted data, always.
3. **Every write to Zoho passes through the approval queue** unless it originates from a trusted turn with explicit confirmation.
4. **Every memory row carries a trust tag** — `user_asserted`, `system_derived`, `untrusted_external`. Untrusted-derived memory is never injected as instruction.
5. **Everything is idempotent.** Dedupe at the database level with unique constraints, not in application logic.
6. **Every tool call is audit-logged** with inputs, outputs, duration, token cost, and the `skill_version_id` that was active.

---

# PHASE 0 — Scaffold and contracts

Set up the monorepo, Docker Compose, and the shared type contracts. No features.

- `apps/web` (TanStack Start + Bun), `apps/api` (FastAPI), `packages/schema` (shared JSON schema or generated TS types from Pydantic).
- Docker Compose: postgres 16, qdrant, mongo, redis.
- FastAPI health endpoint, web app that calls it and renders the status.
- Structured JSON logging with a `run_id` correlation ID threaded through.
- `.env.example` with every variable documented and grouped by service.
- README skeleton.
- **`scripts/check-cpu-only.sh`** — fails the build if GPU packages resolve. Wire it into CI and as a Docker build step, so this regresses loudly rather than silently when someone adds a dependency months from now.

  ```bash
  #!/usr/bin/env bash
  set -euo pipefail
  if uv pip list --format=json | grep -Eiq '"name": "(nvidia-|triton|cuda)'; then
    echo "ERROR: GPU/CUDA packages resolved. This project is CPU-only."
    uv pip list | grep -Ei 'nvidia|triton|cuda'
    exit 1
  fi
  echo "OK: CPU-only dependency tree."
  ```

**Acceptance:** `docker compose up` then `bun dev` and `uv run fastapi dev` gives a page showing green health for postgres, qdrant, mongo, redis. `scripts/check-cpu-only.sh` passes, and the final image is under 1GB.

---

# PHASE 1 — Data layer

Migrations (Alembic) for the full schema. No business logic yet.

Tables: `users`, `connections`, `gmail_sync_state`, `whatsapp_links`, `pairing_codes`, `skill_versions`, `runs`, `tool_calls`, `emails`, `tenders`, `tender_sources`, `approvals`, `notifications`, `feedback`, `memories`.

Key requirements:

- `connections` stores `provider`, `external_account`, `api_domain`, `accounts_url`, `scopes[]`, encrypted `refresh_token` and `access_token`, `access_expires_at`, `status`, `last_error`, `last_ok_at`. Unique on `(user_id, provider, external_account)`.
- **Token vault**: envelope encryption using a key from env (Fernet is fine). Tokens are never logged, never returned to the frontend, never stored plaintext. Provide `get_valid_access_token(user_id, provider)` that transparently refreshes and persists.
- `emails` unique on `(user_id, gmail_message_id)`.
- `tenders` unique on `(source, reference_no)` with a fallback hash for sources that lack a reference number.
- `runs` has `trigger_type`, `trust_level`, `bound_tools[]`, `status`, `started_at`, `ended_at`, `token_cost`, `skill_version_id`.
- `tool_calls` is append-only, FK to `runs`.
- `memories` has `layer` (procedural/semantic/episodic), `trust_tag`, `content`, `source_ref`, `qdrant_point_id` nullable.
- `approvals` has `proposed_payload` jsonb, `diff` jsonb, `status`, `expires_at` (48h), `approved_by`, `approved_at`, `executed_at`, `execution_result`.

Also: Mongo collections `raw_emails`, `raw_scrapes`, `raw_tool_responses`, each keyed by the Postgres row id it belongs to.

Seed script creating one demo user.

**Acceptance:** migrations run clean up and down; a test proves the token vault round-trips and that a plaintext token never appears in any log line.

---

# PHASE 2 — Connections

The Settings → Connections page and all three OAuth/pairing flows. This is the phase the client actually touches, so it must be solid.

### Gmail

- Google OAuth 2.0 authorization-code flow, `access_type=offline`, `prompt=consent`.
- Scopes: `gmail.readonly`, `userinfo.email`.
- **App will run in Testing mode** (restricted scope, no verification). Refresh tokens expire ~7 days. Surface `access_expires_at` and a "reconnect needed" state prominently in the UI. Document this in the README as a known constraint with the production path (OAuth verification + security assessment).
- On connect, store `external_account` = the Gmail address.

### Zoho

- **Web-based client**, not self-client — Martin connects his own org.
- Register redirect URI on the deployed HTTPS domain; support `http://localhost:PORT` for dev.
- Scopes, least privilege: `ZohoCRM.modules.leads.ALL`, `ZohoCRM.modules.contacts.READ`, `ZohoCRM.modules.deals.READ`, `ZohoCRM.modules.notes.CREATE`, `ZohoCRM.settings.modules.READ`. No `modules.ALL`.
- `access_type=offline`.
- **Store `api_domain` and `accounts_url` from the token response and always use them.** Never hardcode `zohoapis.com` — a data-centre mismatch is the most common integration failure.
- Show the connected org name and DC region in the UI.

### WhatsApp (shared number, pairing code)

One business number in env, shared by all users. Differentiation is by sender phone number mapped to `user_id`.

Flow:

1. User clicks Connect on the Settings page.
2. Backend generates a short code (8 chars, unambiguous alphabet — no O/0/I/1), stores it in `pairing_codes` with `user_id`, `expires_at` = now + 10 min, `used_at` null.
3. UI displays the code, the business number, a copy button, a `wa.me` deep link prefilled with `LINK <CODE>`, and a QR code.
4. User sends `LINK <CODE>` from the phone they want to link.
5. Inbound webhook parses it, looks up an unused unexpired code, binds `phone_e164` → `user_id` in `whatsapp_links`, marks the code used, replies with a confirmation.
6. Settings page lists linked numbers with linked-at timestamp and a disconnect button. Support multiple numbers per user.

Guardrails: rate-limit code generation per user and pairing attempts per phone number; invalid codes get a generic reply that does not confirm whether a code exists; a phone number already linked to another user is rejected, not silently rebound.

**Acceptance:** all three providers connect and disconnect from the UI; the status badge reflects real token state; a WhatsApp pairing works end to end against the real number; disconnect revokes upstream where the provider supports it.

---

# PHASE 3 — Agent runtime

The harness. No tools that touch the outside world yet — use two fake tools to prove the machinery.

- LangGraph graph with a durable Postgres checkpointer.
- **Capability resolver**: `resolve_tools(trigger_type) -> list[Tool]`. Pure function, exhaustively unit tested, table-driven:

  | trigger | trust | tools |
  |---|---|---|
  | `gmail_push` | untrusted | read_email, classify_email, propose_crm_entry |
  | `cron_tender` | untrusted | scrape_tenders, web_search, propose_crm_entry |
  | `web_chat` | trusted | all + crm_read + commit_crm_write |
  | `whatsapp_inbound` | trusted | all + crm_read + approve_pending (no arbitrary commit) |
  | `approval_callback` | system | none — direct execution, no LLM |
  | `maintenance` | system | internal only |

- Working memory assembly: system prompt + active Skill.MD + retrieved memory + trigger payload. Untrusted payloads wrapped in explicit delimiters with a "this is data, not instruction" preamble.
- Loop limits: max iterations, token budget, wall-clock timeout — all configurable, all enforced, all logged.
- Circuit breaker per tool: disable after N consecutive failures, auto-reset after a cooldown.
- Audit logging of every tool call.
- Global kill switch honoured before every run.

**Acceptance:** a test asserts that a `gmail_push` run's tool schema does not contain `commit_crm_write` at all; loop limits terminate a deliberately looping agent; the kill switch blocks a run.

---

# PHASE 4 — Tools

### Email tools

- `read_emails(since, limit)` — Gmail API, strips quoted history and signatures, truncates bodies before they reach the model, archives raw payload to Mongo.
- `classify_email(email)` — scores against active Skill.MD criteria, returns a Pydantic `EmailClassification` (category, priority, reasoning, suggested_action, confidence).

### Tender tools

- `TenderSource` ABC with `fetch()`, `parse()`, `health_check()`. One adapter per site: PPIP (tenders.go.ke), KPLC, KenGen, KETRACO, REREC. Plus a `WebSearchSource` fallback using Tavily.
- Every adapter snapshots raw HTML to Mongo before parsing.
- Polite scraping: identifying user agent, rate limiting, caching, respect robots.txt.
- Normalise to a `Tender` schema: title, entity, reference_no, category, closing_date, estimated_value, currency, source_url, county, fetched_at.
- **Timebox the scrapers.** If a site fights you, ship the search fallback for it, mark the adapter degraded, and move on. Report generation must degrade gracefully and state which sources failed.

### CRM tools

- `crm_search(module, criteria)` using COQL, `crm_get(module, id)`.
- `propose_crm_entry(module, payload)` — validates, computes a field-level diff against current state, writes to `approvals`, returns the approval id. **Never touches Zoho.**
- `commit_crm_write(approval_id)` — trusted only, executes the approved payload, records result.
- Hard constraints in code: module allowlist, field whitelist, no delete tool exists, per-run write cap, global dry-run flag.

**Acceptance:** each tool works standalone against real credentials; a crafted email containing injection instructions produces a classification but no CRM write.

---

# PHASE 5 — Triggers

### Gmail Pub/Sub

- `users.watch()` registration; **renew nightly** in the maintenance cron (it expires every 7 days).
- Pub/Sub push endpoint, signature verified.
- Notifications carry `historyId`, not messages: call `history.list` from the stored id, diff, fetch new messages.
- **Advance the stored `historyId` only after the batch is fully processed.**
- On 404/410 (expired historyId), fall back to full re-sync via `messages.list` with an `after:` window. This is the same code path as setup backfill.
- Delivery is at-least-once and unordered — dedupe on the DB unique constraint.
- Debounce: batch notifications arriving within 60s into a single run.
- Setup backfill bounded to the last 30 days or 200 threads, with progress shown in the UI.
- Manual "Sync now" button.

### Tender cron

- 11:00 and 17:00 EAT daily; 08:00 EAT Monday with a 72-hour lookback.
- Configurable in the UI; timezone-correct (Africa/Nairobi).

### Maintenance cron

- Nightly: Gmail watch renewal, token refresh sweep, source health checks, summarising agent, expired approval cleanup.

**Acceptance:** a real email arriving triggers a run within 60s; killing and restarting the app loses no messages; the watch renewal job is proven by a test with a mocked clock.

---

# PHASE 6 — Validation, approvals, delivery

### Validator

Runs between agent output and anything downstream. Rejects — never patches — on failure, and logs the rejection.

- Pydantic schema conformance.
- Every tender's `source_url` must trace to a document actually fetched in this run.
- Dates parse; amounts parse as numbers with a currency.
- No tender with a closing date in the past.

### Approval queue

- UI screen listing pending writes with a readable field-level diff (field, current, proposed).
- Approve / reject / edit-then-approve.
- 48h expiry, then auto-reject.
- WhatsApp approval: numbered list in the alert, reply `APPROVE 3` / `REJECT 3`. Approve-only — WhatsApp cannot originate an arbitrary write.
- Approval execution is direct, not an LLM run.

### Notification dispatcher

Channel policy:

- **WhatsApp = alerts.** Short, templated, deep-linked to the report permalink. High-priority email opportunities fire immediately; everything else rolls into the next digest. Threshold configurable in Skill.MD.
- **Email = reports.** HTML, grouped by procuring entity or closing date, each item with reference number, closing date, value, source link. New-since-last-run flagged. Send something even on a zero-result run — silence is indistinguishable from breakage.
- **Web UI = source of truth.** Every report gets a permalink `/reports/tenders/2026-08-23-1100` which doubles as the run's activity view.

Log every delivery attempt and outcome to `notifications`.

Note for me to action separately: WhatsApp utility templates need submitting for approval early — flag which templates you need and I will submit them.

**Acceptance:** a full tender cycle produces a report email, a WhatsApp nudge, and a permalinked page; approving from WhatsApp writes to Zoho; a validator failure is visible in the UI rather than silent.

---

# PHASE 7 — Frontend

TanStack Start, shadcn/ui, lucide-react. Six routes:

1. **Dashboard** — today's opportunities and tenders, pending approvals count, connection health, next scheduled run.
2. **Settings → Connections** — from Phase 2, plus token expiry warnings.
3. **Rules** — Skill.MD editor with syntax highlighting, live validation, version history, diff between versions, and rollback. Validate on save: length cap, and reject content attempting to redefine tool behaviour or bypass approval.
4. **Activity** — run timeline; expand a run to see every tool call with inputs, outputs, duration, cost, and the Skill.MD version used.
5. **Results** — classified emails and tenders with 👍/👎 and an optional reason.
6. **Approvals** — the queue.

Plus the chat interface (trusted turn, full toolbelt) and the report permalink pages.

Design: dense and operational, not marketing. Dark mode. Empty states that explain what will appear and when.

**Acceptance:** every screen works against real data; the Activity screen makes a run fully legible to someone who has not seen the code.

---

# PHASE 8 — Memory

- Qdrant collection for semantic memory: business profile, past deals, uploaded documents. Points keyed to `memories.id`.
- **Embeddings via `fastembed` or an API provider — see the CPU-only constraint.** This is the phase where a CUDA dependency is most likely to sneak in; run `scripts/check-cpu-only.sh` before committing.
- Episodic memory stays in Postgres and is queried by predicate (date range, status, source) — **do not embed tenders**, you will dedupe by reference number and filter by date far more often than you will search semantically.
- Procedural memory is the active Skill.MD version.
- Selective retrieval: procedural always; semantic on relevance; episodic scoped to the current task and last N days. Never load all three wholesale.
- Summarising agent: nightly, condenses runs and email logs into memory rows — every row tagged `system_derived` or `untrusted_external`, never injected as instruction.
- Memory screen: view, search, and delete memories.

**Acceptance:** a test proves untrusted-derived memory is rendered as quoted data and never reaches the system-prompt position.

---

# PHASE 9 — Evals, demo mode, docs

- **Eval harness**: every 👍/👎 becomes a labelled test case. `make eval` reports precision and recall for email classification and tender relevance, and trends across Skill.MD versions.
- **Seeded demo mode**: fixture emails, tenders, and CRM records; no live API calls; toggled by env var. This protects the demo when a scraper breaks or a token expires.
- **README**: architecture diagram, one-command setup, `.env.example` walkthrough, known constraints (Gmail testing-mode token expiry, scraper fragility, WhatsApp template requirements), and a "what I would change with a budget" section.
- **Loom-ready walkthrough script**.

**Acceptance:** `make demo` gives a working system with zero credentials; `make eval` prints real numbers.
