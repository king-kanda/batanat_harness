# WhatsApp templates to submit

Meta requires an approved **utility** template for any message sent outside the
24-hour customer-service window. Every proactive alert this system sends is
outside that window, so all three need approval before launch. Submission is in
Meta Business Manager → WhatsApp Manager → Message Templates.

Submit these early: approval regularly takes several days, and the code already
falls back to plain text (which only works inside the window) until they exist.

Category for all three: **Utility**. Language: **English**.

---

## 1. `tender_report_ready`

Sent after each tender sweep, when there is something to report.

```
{{1}} new tenders found. Closing soonest: {{2}}.

Full report: {{3}}
```

| Variable | Example |
|---|---|
| `{{1}}` | `7` |
| `{{2}}` | `15 September 2026` |
| `{{3}}` | `https://app.batanat.co.ke/reports/tenders/2026-08-23-1100` |

---

## 2. `opportunity_alert`

Fires immediately for a high-priority email opportunity. Everything below that
threshold waits for the digest — the threshold is set in Skill.MD.

```
New opportunity from {{1}}.

{{2}}

Open: {{3}}
```

| Variable | Example |
|---|---|
| `{{1}}` | `KPLC Procurement` |
| `{{2}}` | `Invitation to Tender — 33kV Switchgear` |
| `{{3}}` | `https://app.batanat.co.ke/results` |

---

## 3. `approval_request`

Sent when CRM writes are queued. The reply format is parsed by the webhook:
`APPROVE 2`, `REJECT 1`, or a bare `YES` / `NO` when there is only one.

```
{{1}} CRM update(s) awaiting your approval:

{{2}}

Reply APPROVE <number> or REJECT <number>. Review: {{3}}
```

| Variable | Example |
|---|---|
| `{{1}}` | `2` |
| `{{2}}` | `1. Add lead: Kenya Power\n2. Add note to: KETRACO deal` |
| `{{3}}` | `https://app.batanat.co.ke/approvals` |

---

## Note on what WhatsApp can and cannot do

WhatsApp can **approve or reject something already queued**. It cannot originate
a CRM write — the `whatsapp_inbound` trigger is not given `commit_crm_write` at
all, so there is no tool for it to reach even if a message asked. This is
enforced in `agent/capabilities.py`, not by prompt wording.
