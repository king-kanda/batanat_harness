"""Gmail REST client.

Only the five calls this system needs: list, get, history, watch, stop. Written
against `httpx` directly rather than `google-api-python-client`, which pulls a
large dependency tree to build the same requests.

Every access token comes from the token vault, which refreshes transparently.
Nothing here touches a credential directly.
"""

from __future__ import annotations

import base64
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

from batanat_api.core.logging import get_logger
from batanat_api.db import enums
from batanat_api.security.token_vault import ReauthorizationRequiredError, get_valid_access_token

log = get_logger(__name__)

API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"


class GmailError(RuntimeError):
    pass


class HistoryExpiredError(GmailError):
    """The stored historyId is too old. Fall back to a full re-sync window."""


@dataclass(slots=True)
class GmailMessage:
    """A message, flattened to what we actually use."""

    id: str
    thread_id: str
    history_id: int | None
    from_address: str | None
    from_name: str | None
    subject: str | None
    snippet: str | None
    received_at: datetime | None
    body: str
    raw: dict[str, Any] = field(default_factory=dict)


class GmailClient:
    def __init__(self, session, user_id: uuid.UUID):
        self._session = session
        self._user_id = user_id

    async def _token(self) -> str:
        return await get_valid_access_token(self._session, self._user_id, enums.Provider.gmail)

    async def _request(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        token = await self._token()
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request(
                method,
                f"{API_BASE}{path}",
                headers={"Authorization": f"Bearer {token}"},
                **kwargs,
            )

        if response.status_code in (404, 410):
            # Gmail returns these when a historyId has aged out of the window.
            raise HistoryExpiredError(f"Gmail returned {response.status_code} for {path}")
        if response.status_code == 401:
            raise ReauthorizationRequiredError("Gmail rejected the access token.")
        if not response.is_success:
            raise GmailError(f"Gmail {method} {path} returned {response.status_code}")

        return response.json()

    async def list_messages(
        self, *, query: str | None = None, limit: int = 25, page_token: str | None = None
    ) -> tuple[list[str], str | None]:
        params: dict[str, Any] = {"maxResults": min(limit, 100)}
        if query:
            params["q"] = query
        if page_token:
            params["pageToken"] = page_token

        data = await self._request("GET", "/messages", params=params)
        ids = [m["id"] for m in data.get("messages", [])]
        return ids, data.get("nextPageToken")

    async def get_message(self, message_id: str) -> GmailMessage:
        data = await self._request("GET", f"/messages/{message_id}", params={"format": "full"})
        return parse_message(data)

    async def list_history(self, start_history_id: int) -> tuple[list[str], int | None]:
        """Message ids added since `start_history_id`, and the new cursor.

        Raises `HistoryExpiredError` when the id is too old — the caller falls
        back to a windowed re-sync, which is the same code path as setup
        backfill.
        """
        message_ids: list[str] = []
        page_token: str | None = None
        latest: int | None = None

        while True:
            params: dict[str, Any] = {
                "startHistoryId": start_history_id,
                "historyTypes": "messageAdded",
            }
            if page_token:
                params["pageToken"] = page_token

            data = await self._request("GET", "/history", params=params)
            latest = int(data["historyId"]) if data.get("historyId") else latest

            for record in data.get("history", []):
                for added in record.get("messagesAdded", []):
                    message = added.get("message", {})
                    if message.get("id"):
                        message_ids.append(message["id"])

            page_token = data.get("nextPageToken")
            if not page_token:
                break

        # Gmail can list the same message more than once across history records.
        return list(dict.fromkeys(message_ids)), latest

    async def watch(self, topic: str) -> tuple[int, datetime]:
        """Register push notifications. Expires after 7 days; renewed nightly."""
        data = await self._request(
            "POST", "/watch", json={"topicName": topic, "labelIds": ["INBOX"]}
        )
        expiration = datetime.fromtimestamp(int(data["expiration"]) / 1000, tz=UTC)
        log.info("gmail.watch.registered", expiration=expiration.isoformat())
        return int(data["historyId"]), expiration

    async def stop_watch(self) -> None:
        await self._request("POST", "/stop")


# --- parsing -----------------------------------------------------------------


def _header(payload: dict[str, Any], name: str) -> str | None:
    for header in payload.get("headers", []):
        if header.get("name", "").lower() == name.lower():
            return header.get("value")
    return None


def _decode(data: str | None) -> str:
    if not data:
        return ""
    padded = data + "=" * (-len(data) % 4)
    try:
        return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return ""


def extract_body(payload: dict[str, Any]) -> str:
    """Prefer text/plain; fall back to stripping tags from text/html."""
    mime = payload.get("mimeType", "")

    if mime == "text/plain":
        return _decode(payload.get("body", {}).get("data"))

    if mime == "text/html":
        from bs4 import BeautifulSoup

        html = _decode(payload.get("body", {}).get("data"))
        return BeautifulSoup(html, "lxml").get_text(" ") if html else ""

    plain_parts: list[str] = []
    html_parts: list[str] = []
    for part in payload.get("parts", []) or []:
        text = extract_body(part)
        if not text:
            continue
        (plain_parts if part.get("mimeType") == "text/plain" else html_parts).append(text)

    return "\n".join(plain_parts or html_parts)


def parse_address(value: str | None) -> tuple[str | None, str | None]:
    """`"Jane Doe" <jane@x.com>` → ("jane@x.com", "Jane Doe")."""
    if not value:
        return None, None
    if "<" in value and ">" in value:
        name = value.split("<")[0].strip().strip('"').strip()
        address = value.split("<")[1].split(">")[0].strip()
        return address or None, name or None
    return value.strip(), None


def parse_message(data: dict[str, Any]) -> GmailMessage:
    payload = data.get("payload", {})
    address, name = parse_address(_header(payload, "From"))

    received_at = None
    if data.get("internalDate"):
        received_at = datetime.fromtimestamp(int(data["internalDate"]) / 1000, tz=UTC)

    return GmailMessage(
        id=data["id"],
        thread_id=data.get("threadId", ""),
        history_id=int(data["historyId"]) if data.get("historyId") else None,
        from_address=address,
        from_name=name,
        subject=_header(payload, "Subject"),
        snippet=data.get("snippet"),
        received_at=received_at,
        body=extract_body(payload),
        raw=data,
    )
