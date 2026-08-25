"""Every conversational run gets the same criteria and the same knowledge.

`AgentRunner.run` takes `skill_content` and `memories` as arguments and does not
load either itself, so a call site that forgets them produces an agent with no
criteria and no knowledge base — and nothing fails. The WhatsApp path did
exactly that: the same question asked from a handset and from the web app went
to two different agents, which reads as the model being unreliable rather than
as missing context.

Email classification had half of it: Skill.MD but no semantic memory, so a
capability statement uploaded specifically to sharpen that decision had no
effect on it.

These tests assert what each call site hands the runner, because that is the
only place the omission was ever visible.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from batanat_api.agent import conversations
from batanat_api.db import enums
from batanat_api.db.models import Email, SkillVersion


@pytest.fixture
def recorded(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Capture the kwargs the call site passes to the runner."""
    seen: dict = {}

    class FakeResult:
        run_id = uuid.uuid4()
        output = "ok"
        iterations = 1

    class FakeRunner:
        def __init__(self, *args, **kwargs):
            pass

        async def run(self, session, **kwargs):
            seen.update(kwargs)
            return FakeResult()

    class FakeModel:
        def is_configured(self):
            return True

    import batanat_api.agent.providers as providers
    import batanat_api.agent.runner as runner_module

    monkeypatch.setattr(runner_module, "AgentRunner", FakeRunner)
    monkeypatch.setattr(providers, "get_model", lambda: FakeModel())
    return seen


async def _active_skill(session, user_id, content: str = "Flag energy tenders.") -> SkillVersion:
    skill = SkillVersion(
        user_id=user_id,
        version=1,
        content=content,
        checksum=uuid.uuid4().hex,
        is_active=True,
        created_by="test",
    )
    session.add(skill)
    await session.flush()
    return skill


async def test_whatsapp_runs_with_the_active_skill(session, user, recorded, monkeypatch) -> None:
    from batanat_api.webhooks import whatsapp as webhook

    skill = await _active_skill(session, user.id)

    async def no_send(*args, **kwargs):
        return True

    async def no_record(*args, **kwargs):
        return None

    monkeypatch.setattr(webhook, "send_reply", no_send)
    monkeypatch.setattr(conversations, "record_turn", no_record)
    await webhook._chat(session, user.id, "+254700000099", "What is closing this week?")

    assert recorded["skill_content"] == skill.content
    assert recorded["skill_version_id"] == skill.id


async def test_whatsapp_runs_with_semantic_memory(session, user, recorded, monkeypatch) -> None:
    """Uploaded documents have to reach the handset, not only the web app."""
    from batanat_api.webhooks import whatsapp as webhook

    await _active_skill(session, user.id)

    async def no_send(*args, **kwargs):
        return True

    async def no_record(*args, **kwargs):
        return None

    monkeypatch.setattr(webhook, "send_reply", no_send)
    monkeypatch.setattr(conversations, "record_turn", no_record)
    await webhook._chat(session, user.id, "+254700000098", "What do we do?")

    # Both halves of the trust split are handed over, even when empty: the
    # keys being absent is what the bug looked like.
    assert "memories" in recorded
    assert "quoted_context" in recorded


async def test_email_classification_runs_with_semantic_memory(
    session, user, recorded, monkeypatch
) -> None:
    from batanat_api.gmail import client as gmail_client
    from batanat_api.triggers import gmail_trigger

    skill = await _active_skill(session, user.id)

    email = Email(
        user_id=user.id,
        gmail_message_id=f"msg-{uuid.uuid4().hex[:10]}",
        gmail_thread_id="thread-1",
        from_address="tenders@example.com",
        subject="Invitation to tender: solar mini-grid",
        snippet="Bids close Friday.",
        received_at=datetime.now(UTC),
    )
    session.add(email)
    await session.flush()

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def get_message(self, message_id):
            raise RuntimeError("fall back to the stored snippet")

    monkeypatch.setattr(gmail_trigger, "GmailClient", FakeClient)
    monkeypatch.setattr(gmail_client, "GmailClient", FakeClient)

    await gmail_trigger._classify_batch(session, user.id, [email.id])

    assert recorded["skill_content"] == skill.content
    assert "memories" in recorded
    assert "quoted_context" in recorded
    # Still an untrusted trigger — the change adds context, not permission.
    assert recorded["trigger"] is enums.TriggerType.gmail_push
