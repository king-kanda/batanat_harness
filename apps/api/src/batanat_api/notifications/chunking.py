"""Splitting a reply into WhatsApp-sized messages.

WhatsApp's hard limit is 4096 characters, but that is not the number worth
designing to. A wall of text on a phone is unreadable regardless of whether it
was accepted, so this targets something closer to what a person would actually
type, and breaks where meaning breaks: paragraphs first, then sentences, and
only mid-sentence when a single sentence is itself too long.

Fenced code and long URLs are never split across messages — half a link is
useless, and WhatsApp will linkify the fragments into two broken ones.
"""

from __future__ import annotations

import re

#: Comfortable on a phone. Well under WhatsApp's 4096 hard cap.
SOFT_LIMIT = 900

#: Never exceeded. Meta rejects the send outright above 4096.
HARD_LIMIT = 4000

#: More than this and we are spamming; the tail is trimmed with a marker.
MAX_MESSAGES = 5

PARAGRAPH = re.compile(r"\n{2,}")
SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")
FENCE = re.compile(r"```.*?```", re.DOTALL)


def split_for_whatsapp(
    text: str, *, soft_limit: int = SOFT_LIMIT, max_messages: int = MAX_MESSAGES
) -> list[str]:
    """One reply, as the messages to actually send. Never returns empty."""
    cleaned = (text or "").strip()
    if not cleaned:
        return []

    if len(cleaned) <= soft_limit:
        return [cleaned]

    chunks: list[str] = []
    for block in _atomic_blocks(cleaned):
        if not block.strip():
            continue
        _append(chunks, block.strip(), soft_limit)

    if not chunks:
        chunks = [cleaned[:soft_limit]]

    if len(chunks) > max_messages:
        kept = chunks[:max_messages]
        kept[-1] = _truncate(
            kept[-1] + "\n\n…the rest is on the web app.",
            HARD_LIMIT,
        )
        return kept

    return [_truncate(chunk, HARD_LIMIT) for chunk in chunks]


def _atomic_blocks(text: str) -> list[str]:
    """Paragraphs, with fenced code kept whole however long it is."""
    blocks: list[str] = []
    cursor = 0
    for fence in FENCE.finditer(text):
        before = text[cursor : fence.start()]
        blocks.extend(PARAGRAPH.split(before))
        blocks.append(fence.group(0))
        cursor = fence.end()
    blocks.extend(PARAGRAPH.split(text[cursor:]))
    return blocks


def _append(chunks: list[str], block: str, limit: int) -> None:
    """Add a block, packing it onto the previous message when it fits.

    Deliberately not recursive. `_split_block` can return a piece still over the
    limit — a URL or token with nothing to break on — and re-splitting that
    piece returns it unchanged, which recurses until the stack gives out. Such a
    piece is placed as-is and capped later by `HARD_LIMIT`.
    """
    pieces = (
        _split_block(block, limit)
        if len(block) > limit and not block.startswith("```")
        else [block]
    )
    for piece in pieces:
        if chunks and len(chunks[-1]) + 2 + len(piece) <= limit:
            chunks[-1] = f"{chunks[-1]}\n\n{piece}"
        else:
            chunks.append(piece)


def _split_block(block: str, limit: int) -> list[str]:
    """Sentences, then words. Only ever called on an oversized paragraph."""
    pieces: list[str] = []
    current = ""

    for sentence in SENTENCE.split(block):
        if len(sentence) > limit:
            if current:
                pieces.append(current)
                current = ""
            pieces.extend(_split_words(sentence, limit))
            continue

        candidate = f"{current} {sentence}".strip()
        if len(candidate) <= limit:
            current = candidate
        else:
            if current:
                pieces.append(current)
            current = sentence

    if current:
        pieces.append(current)
    return pieces


def _split_words(sentence: str, limit: int) -> list[str]:
    """Last resort. Keeps whole words — a split URL is worse than a long one."""
    pieces: list[str] = []
    current = ""
    for word in sentence.split():
        candidate = f"{current} {word}".strip()
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            pieces.append(current)
        # A single word longer than the limit is a URL or a token; send it
        # whole and let it be the one over-length message rather than two
        # halves of a dead link.
        current = word
    if current:
        pieces.append(current)
    return pieces


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"
