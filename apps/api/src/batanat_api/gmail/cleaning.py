"""Reducing an email to the part worth reading.

A forwarded thread can be forty kilobytes of quoted history, three signatures
and a legal disclaimer wrapped around two new sentences. Sending that to the
model costs money, buries the actual content, and — since every quoted line is
attacker-controlled text — widens the injection surface for no benefit.

So: strip quoted history, drop signatures and disclaimers, then truncate. The
raw original is already in Mongo, so nothing is lost by being aggressive here.
"""

from __future__ import annotations

import re

#: Lines that begin a quoted reply. Everything from here down is history.
QUOTE_MARKERS = (
    re.compile(r"^\s*On .{5,120}\bwrote:\s*$", re.IGNORECASE),
    re.compile(r"^\s*-{2,}\s*Original Message\s*-{2,}\s*$", re.IGNORECASE),
    re.compile(r"^\s*-{2,}\s*Forwarded message\s*-{2,}\s*$", re.IGNORECASE),
    re.compile(r"^\s*From:\s*.+<.+@.+>\s*$", re.IGNORECASE),
    re.compile(r"^\s*_{5,}\s*$"),
)

#: Lines that begin a signature block.
SIGNATURE_MARKERS = (
    re.compile(r"^\s*--\s*$"),
    re.compile(r"^\s*(kind|best|warm)\s+regards[,.]?\s*$", re.IGNORECASE),
    re.compile(r"^\s*(sent from my|get outlook for)\b", re.IGNORECASE),
    re.compile(r"^\s*(disclaimer|confidentiality notice)\b", re.IGNORECASE),
    re.compile(
        r"^\s*this (e-?mail|message).{0,60}(confidential|intended (only|solely))",
        re.IGNORECASE,
    ),
)

DEFAULT_MAX_CHARS = 4000


def strip_quoted(body: str) -> str:
    """Drop everything from the first quote marker onward."""
    lines = body.splitlines()
    kept: list[str] = []

    for index, line in enumerate(lines):
        if any(marker.match(line) for marker in QUOTE_MARKERS):
            break
        # A run of ">" quoting that reaches the end is history too.
        if line.lstrip().startswith(">") and all(
            rest.lstrip().startswith(">") or not rest.strip() for rest in lines[index:]
        ):
            break
        kept.append(line)

    return "\n".join(kept)


def strip_signature(body: str) -> str:
    lines = body.splitlines()
    for index, line in enumerate(lines):
        if any(marker.match(line) for marker in SIGNATURE_MARKERS):
            return "\n".join(lines[:index])
    return body


def collapse_blank_lines(body: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", body).strip()


def truncate(body: str, max_chars: int = DEFAULT_MAX_CHARS) -> tuple[str, bool]:
    """Cut to length, saying so, rather than silently dropping the tail."""
    if len(body) <= max_chars:
        return body, False
    cut = body[:max_chars].rsplit(" ", 1)[0]
    return f"{cut}\n\n[truncated — {len(body) - len(cut)} more characters in the archive]", True


def clean_body(body: str, *, max_chars: int = DEFAULT_MAX_CHARS) -> tuple[str, bool]:
    """Quoted history and signatures out, then truncate. Returns (text, truncated)."""
    stripped = collapse_blank_lines(strip_signature(strip_quoted(body or "")))
    return truncate(stripped, max_chars)


# --- threads -----------------------------------------------------------------

#: A whole thread gets a bigger budget than one message, but not an unbounded one.
DEFAULT_THREAD_MAX_CHARS = 12_000
#: Per message inside a thread. Tighter, so one long message cannot crowd out the rest.
DEFAULT_MESSAGE_IN_THREAD_MAX_CHARS = 1_500


def render_thread(messages, *, max_chars: int = DEFAULT_THREAD_MAX_CHARS) -> tuple[str, bool]:
    """Render a Gmail thread as a compact transcript.

    Quoted history is stripped from each message, which matters more here than
    anywhere else: in a ten-message thread every reply re-quotes everything
    above it, so the same text arrives ten times. Reading the real thread and
    dropping the quotes gives the model the whole conversation for a fraction of
    the tokens — and shrinks how much attacker-controlled text is in play.

    Returns `(transcript, truncated)`.
    """
    if not messages:
        return "", False

    parts: list[str] = []
    for index, message in enumerate(messages, start=1):
        body, _ = clean_body(message.body, max_chars=DEFAULT_MESSAGE_IN_THREAD_MAX_CHARS)
        sender = message.from_name or message.from_address or "unknown sender"
        when = message.received_at.strftime("%d %b %Y %H:%M") if message.received_at else "undated"
        parts.append(f"[{index}] {sender} — {when}\n{body or '(no text)'}")

    transcript = "\n\n".join(parts)
    if len(transcript) <= max_chars:
        return transcript, False

    # Keep the newest messages: the ask is usually at the end.
    kept: list[str] = []
    total = 0
    for part in reversed(parts):
        if total + len(part) > max_chars:
            break
        kept.insert(0, part)
        total += len(part)

    dropped = len(parts) - len(kept)
    header = f"[{dropped} earlier message(s) omitted — the full thread is in the archive]\n\n"
    return header + "\n\n".join(kept), True
