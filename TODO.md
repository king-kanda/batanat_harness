# What I need from you

Everything here is something I cannot do myself — an account you own, a credential only you can
issue, a decision only you can make, or a domain judgement only you have. The build continues
around each of these; items marked **BLOCKING** stop a specific capability from being verified
against reality, not from being built.

Tick them off as you go. Paste secrets straight into `.env` — never into chat, never into a file
that gets committed.

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

- [ ] `ANTHROPIC_API_KEY` — <https://console.anthropic.com>
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

## 8. Nice to have

- [ ] The original hand-drawn architecture diagram as an image, dropped at `docs/architecture.png`.
      The README currently carries a Mermaid reproduction of it.
- [ ] A recipient address for the tender report emails, and how it should be sent — Gmail API as
      Martin, or a transactional provider?
