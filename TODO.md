# What I need from you

Everything here is something I cannot do myself — an account you own, a credential only you can
issue, a decision only you can make, or a domain judgement only you have. The build continues
around each of these; items marked **BLOCKING** stop a specific capability from being verified
against reality, not from being built.

Tick them off as you go. Paste secrets straight into `.env` — never into chat, never into a file
that gets committed.

---

> **Status:** phases 0–9 are built. Everything below is what I cannot do for you.
> The build works today without any of it — run `make demo` for a full working
> system with zero credentials. These items turn the demo into the real thing.

---

## 0. Quick wins — do these first

- [ ] A model API key in `.env`. **Nothing classifies or chats without one.**
      This is the single highest-impact item on the page.
      Ships defaulted to `LLM_PROVIDER=groq` → set `GROQ_API_KEY`
      (<https://console.groq.com>). For OpenRouter set `LLM_PROVIDER=openrouter`
      and `OPENROUTER_API_KEY`. Anthropic still works if you want it.
- [ ] `TAVILY_API_KEY` in `.env`. Turns on the search fallback that covers the
      four scrapers that cannot be scraped (see section 9).
- [ ] Set `CRM_DRY_RUN=false` when you want approved writes to actually reach
      Zoho. It ships `true`, so today an approval is logged and not sent.
- [ ] Set `ENABLE_SCHEDULER=true` to turn on the 11:00/17:00 EAT tender sweeps
      and the nightly maintenance job. Off by default so a one-off script never
      starts cron.

---

## 1. Decisions I need from you

- [ ] **Single user or multi-tenant?** The schema supports many users. If this is only ever Martin,
      I will keep one seeded user and skip login. If others will use it, I need to add
      authentication — there is no auth phase anywhere in the PRD.
      *Currently assuming: single user, seeded, no login.*

- [ ] **Can the chat commit CRM writes directly?** Invariant 3 allows a trusted turn with "explicit
      confirmation" to bypass the approval queue, but does not define what confirmation means.
      *Currently assuming: no. Chat proposes, you click approve, the same as everything else. One
      write path is far easier to defend than two.*

- [ ] **Tenders that closed before we saw them.** The validator rejects any tender with a closing
      date in the past, which fights the Monday 72-hour lookback.
      *Currently assuming: store it, flag it closed, exclude it from the report — the archive stays
      honest and the report stays useful.*

- [ ] **Skill.MD scope.** I am keeping every security rule in code, and Skill.MD holds only
      *criteria* — what counts as an opportunity, priority thresholds, tone. This means the Rules
      editor cannot break the security model no matter what is typed into it. Say if you want it
      to carry more.

---

## 2. Credentials — Google / Gmail  **BLOCKING Phase 2 + 5 verification**

Create at <https://console.cloud.google.com>.

- [ ] A GCP project (any name).
- [ ] **Gmail API** enabled on it.
- [ ] **OAuth consent screen** configured — External, publishing status **Testing**, with Martin's
      Gmail address added as a test user.
- [ ] Scopes added to the consent screen: `gmail.readonly`, `userinfo.email`.
- [ ] An **OAuth client ID of type "Web application"**, with these authorised redirect URIs:
      - `http://localhost:8000/api/connections/gmail/callback`
      - your ngrok/production HTTPS equivalent, once we have one
- [ ] → `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` into `.env`

For Gmail push (Phase 5):

- [ ] **Pub/Sub API** enabled.
- [ ] A Pub/Sub **topic**, with `gmail-api-push@system.gserviceaccount.com` granted the
      **Pub/Sub Publisher** role on it.
- [ ] A **push subscription** on that topic pointing at
      `https://<your-ngrok-domain>/api/webhooks/gmail`.
- [ ] → `GMAIL_PUBSUB_TOPIC` (full `projects/<id>/topics/<name>` form) into `.env`

> Known constraint, no action needed: in Testing mode Google expires refresh tokens after ~7 days.
> The UI shows a reconnect prompt. Escaping it means OAuth verification plus a security assessment,
> which is a weeks-long process and a separate decision.

---

## 3. Credentials — Zoho CRM  **BLOCKING Phase 2 + 4 verification**

Create at <https://api-console.zoho.com>.

- [ ] A **Server-based Application** (this is Zoho's name for a web client — *not* a Self Client).
- [ ] Authorised redirect URI: `http://localhost:8000/api/connections/zoho/callback`
- [ ] → `ZOHO_CLIENT_ID`, `ZOHO_CLIENT_SECRET` into `.env`
- [ ] **Which data centre is the org in?** `.com`, `.eu`, `.in`, `.com.au`, `.jp`? It is the domain
      you see when logged into Zoho CRM. Set `ZOHO_ACCOUNTS_URL` accordingly.
- [ ] Confirm the CRM user connecting has permission on Leads, Contacts, Deals and Notes.

Scopes I will request, least privilege — tell me if any is unavailable on your plan:
`ZohoCRM.modules.leads.ALL`, `ZohoCRM.modules.contacts.READ`, `ZohoCRM.modules.deals.READ`,
`ZohoCRM.modules.notes.CREATE`, `ZohoCRM.settings.modules.READ`.

---

## 4. Credentials — WhatsApp Cloud API  **BLOCKING Phase 2 + 6 verification**

Create at <https://developers.facebook.com>.

- [ ] A Meta app with **WhatsApp** added, and a **business phone number** registered.
- [ ] → `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_BUSINESS_NUMBER` (E.164, e.g. `+2547…`),
      `WHATSAPP_ACCESS_TOKEN` (permanent system-user token, not the 24h test token),
      `WHATSAPP_APP_SECRET` into `.env`
- [ ] Webhook configured at `https://<your-ngrok-domain>/api/webhooks/whatsapp`, with a verify
      token you choose → `WHATSAPP_VERIFY_TOKEN`, subscribed to the `messages` field.

### Templates to submit for approval — do this early, Meta's queue is slow

I need three utility templates. Exact copy is in `docs/whatsapp-templates.md` once Phase 6 lands;
submit these names so they are approved by the time we need them:

- [ ] `tender_report_ready` — "N new tenders found. Closing soonest: {{1}}. Full report: {{2}}"
- [ ] `opportunity_alert` — high-priority email opportunity, sender + subject + link
- [ ] `approval_request` — numbered pending CRM writes, replied to with `APPROVE n` / `REJECT n`

---

## 5. Credentials — model and search  **BLOCKING Phase 3 + 4**

- [ ] One of `GROQ_API_KEY` / `OPENROUTER_API_KEY` / `ANTHROPIC_API_KEY`, matching `LLM_PROVIDER`.
- [ ] `TAVILY_API_KEY` — <https://tavily.com>, free tier is fine. This powers the tender search
      fallback for sites whose HTML fights us.

---

## 6. Webhook tunnel  **BLOCKING Phase 5**

- [ ] ngrok account and a **reserved domain** (the free random one changes on every restart, which
      means reconfiguring Google and Meta each time). → note the domain here so I can wire it in.

---

## 7. Domain input — the highest-leverage thing on this list

This is the part no credential can substitute for. It is the difference between a system that
finds tenders and a system that finds *your* tenders.

- [ ] **What counts as an opportunity?** In your words. Which procuring entities matter, which
      categories (solar, transmission, distribution, metering, EPC, consultancy…), what contract
      sizes are worth Martin's attention, which counties.
- [ ] **What should be ignored?** Categories or entities that reliably waste time.
- [ ] **What makes an email high priority** — the kind that should buzz his phone immediately
      rather than wait for the digest?
- [ ] **Any past won/lost deals** you are willing to share. These become semantic memory in
      Phase 8 and materially improve relevance scoring.
- [ ] **Confirm the tender source list:** PPIP (tenders.go.ke), KPLC, KenGen, KETRACO, REREC.
      Anything missing? EPRA, county portals, Rural Electrification, ERC?
- [ ] Do any of those sites need a **login** to see tenders?

---

## 9. Scrapers — a decision, not just a credential

Verified live: only **REREC** serves server-rendered HTML (157 tenders parsed).
**KPLC, KenGen, KETRACO and PPIP** render their tender listings client-side, so
what we receive is page chrome and JavaScript with no tenders in it. Run
`make sources` any time for the current truth.

- [ ] **Accept the search fallback** (cheapest): set `TAVILY_API_KEY` and those
      four are covered by search. Worse signal — results lag, and reference
      numbers and closing dates usually are not exposed.
- [ ] **Or approve a headless browser** (Playwright, ~400MB) so they can be
      scraped properly. Real cost in fragility and image size; I did not add it
      unilaterally.
- [ ] **Or find their JSON endpoints** — each of those sites fetches its own
      tenders over XHR. Undocumented and changes without notice, but cheap while
      it works. I can investigate if you want.
- [ ] **KPLC robots.txt:** it disallows named AI crawlers (ClaudeBot, GPTBot)
      while allowing `User-agent: *` with `Content-Signal: use=reference`. Our
      scraper declares itself, is not one of those, and does not train on the
      content. Confirm you are comfortable, or say the word and I will disable
      that source.

---

## 10. Two dependencies added beyond the agreed stack

Both need a yes or a no from you.

- [ ] **`segno`** — pure Python, zero dependencies. Renders the WhatsApp pairing
      QR code server-side. The PRD asked for a QR; nothing in the stack could
      make one.
- [ ] **`beautifulsoup4` + `lxml`** — HTML parsing for the scrapers. The stack
      list named no parser, and scraping is a core requirement.

Say the word on either and I will remove it.

---

## 11. Email delivery — SendGrid  **BLOCKING the tender report**

Resolved: reports go out on SendGrid, keeping the Gmail connection `gmail.readonly`
by design. A leaked SendGrid key can send mail but cannot read Martin's inbox —
widening the Gmail scope would have collapsed both into one token.

- [ ] SendGrid account and an API key with **Mail Send** permission →
      `SENDGRID_API_KEY`
- [ ] **Verify the sender.** SendGrid → Settings → Sender Authentication. Either
      verify a single sender address or authenticate the whole domain (better:
      it also fixes deliverability). An unverified sender is refused with a 403,
      and the UI will say exactly that.
      → `REPORT_FROM_EMAIL`, optionally `REPORT_FROM_NAME` and `REPORT_REPLY_TO`
- [ ] **Who gets the reports** → `REPORT_TO` (comma-separated)
- [ ] **Who is CC'd** → `REPORT_CC` (comma-separated, optional)

Recipients are configuration, deliberately: nothing the agent reads or produces can
change where a report lands. An agent that could pick its own recipients could
exfiltrate.

A typo in either list is skipped and named in the delivery record rather than
blocking the whole send — but it *is* skipped, so check the Activity screen after
the first run.

---

## 8. Nice to have

- [ ] The original hand-drawn architecture diagram as an image, dropped at `docs/architecture.png`.
      The README currently carries a Mermaid reproduction of it.
- [ ] A recipient address for the tender report emails, and how it should be sent — Gmail API as
      Martin, or a transactional provider?
