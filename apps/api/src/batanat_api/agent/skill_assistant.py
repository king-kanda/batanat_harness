"""The rules assistant.

Helps the user articulate their operating criteria, then hands back a complete
Skill.MD they can review and publish.

**It does not use the agent loop, and that is the point.** The agent has tools;
this has none. Drafting rules is a conversation about what matters to the
business, and giving it the ability to read email or touch the CRM would be
capability nobody asked for. It calls the model directly with a system prompt
and gets text back.

The draft is never published automatically. It goes into the editor, the same
validation runs, and the human presses the button — the Rules screen is the one
place where what the model wrote becomes what the system believes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from batanat_api.agent.providers import get_model
from batanat_api.core.logging import get_logger

log = get_logger(__name__)

DRAFT_FENCE = re.compile(r"```(?:markdown|md)?\s*\n(.*?)```", re.DOTALL)

SYSTEM_PROMPT = """\
You are helping the owner of a Kenyan energy company write the operating criteria \
for an assistant that watches their email and public tender sites.

Your job is to ask about their business and turn the answers into criteria. Be \
concrete and brief. Ask at most two questions per reply, and prefer specifics: \
which procuring entities matter, which categories of work, what contract sizes \
are worth interrupting them for, which counties, what reliably wastes their time.

What the criteria may contain:
- what counts as an opportunity in an email, and what does not
- how to categorise email: opportunity, client, supplier, administrative, spam
- what makes something high priority (these interrupt by WhatsApp) versus a digest item
- what makes a tender relevant
- tone for notifications

What the criteria may NOT contain, and you must refuse to add:
- anything about which tools the assistant may use
- anything about skipping, bypassing or automating approval
- instructions to write to the CRM directly

Those are decided in code, not in this document. If the user asks for one, say \
plainly that capabilities are not configurable from here and carry on.

When you have enough to be useful, output the complete document in a single \
```markdown fenced block. Always output the whole document, never a fragment — \
it replaces the current version wholesale. Keep it under 300 lines. Outside the \
block, write one or two sentences about what you changed and what is still \
missing.
"""


@dataclass(slots=True)
class DraftResult:
    reply: str
    proposed_content: str | None


def extract_draft(text: str) -> tuple[str, str | None]:
    """Split a reply into prose and the fenced document, if there is one."""
    match = DRAFT_FENCE.search(text or "")
    if not match:
        return text.strip(), None

    draft = match.group(1).strip()
    prose = DRAFT_FENCE.sub("", text).strip()
    # A fence containing a couple of words is a formatting accident, not a draft.
    if len(draft) < 80:
        return text.strip(), None
    return prose or "Here is an updated draft.", draft


async def draft_rules(
    messages: list[dict[str, Any]], current_content: str | None = None
) -> DraftResult:
    """One turn of the drafting conversation."""
    model = get_model()
    if not model.is_configured():
        raise RuntimeError("No model API key is set for the selected LLM_PROVIDER — see TODO.md.")

    system = SYSTEM_PROMPT
    if current_content and current_content.strip():
        system += (
            "\n\nThe criteria currently in force are below. Build on them rather than "
            "starting over, and preserve anything the user has not asked to change.\n\n"
            f"---\n{current_content.strip()}\n---"
        )

    response = await model.complete(
        system=system,
        messages=[{"role": m["role"], "content": m["content"]} for m in messages],
        tools=[],  # deliberately none
        timeout_s=90.0,
    )

    reply, draft = extract_draft(response.text or "")
    log.info("skill.draft", produced_draft=draft is not None, tokens=response.total_tokens)
    return DraftResult(reply=reply, proposed_content=draft)
