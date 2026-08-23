"""Zoho CRM client, and the constraints that live in code rather than in a prompt.

Four guards, none of which the model can talk its way past:

* **Module allowlist** — a write may only touch Leads or Notes.
* **Field whitelist** — per module. Anything else is dropped before the request
  is built, and the drop is reported.
* **No delete** — there is no delete method on this client. Not disabled: absent.
* **Per-run write cap and global dry run** — enforced by the caller.

Every request goes to the `api_domain` stored on the connection at
authorisation. A token minted in one Zoho data centre is worthless against
another, and guessing is the most common way this integration breaks.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx

from batanat_api.core.logging import get_logger
from batanat_api.db import enums
from batanat_api.security.token_vault import get_connection, get_valid_access_token

log = get_logger(__name__)

#: Modules the agent may read.
READABLE_MODULES = frozenset({"Leads", "Contacts", "Deals", "Notes"})
#: Modules the agent may propose writes to. Deliberately smaller.
WRITABLE_MODULES = frozenset({"Leads", "Notes"})

#: Exactly which fields a write may set. Anything else is dropped.
FIELD_WHITELIST: dict[str, frozenset[str]] = {
    "Leads": frozenset(
        {
            "Company",
            "Last_Name",
            "First_Name",
            "Email",
            "Phone",
            "Website",
            "Lead_Source",
            "Industry",
            "Description",
            "City",
            "Country",
        }
    ),
    "Notes": frozenset({"Note_Title", "Note_Content", "Parent_Id", "se_module"}),
}


class CrmError(RuntimeError):
    pass


class ModuleNotAllowedError(CrmError):
    pass


def filter_payload(module: str, payload: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Keep only whitelisted fields. Returns (kept, dropped_field_names)."""
    allowed = FIELD_WHITELIST.get(module, frozenset())
    kept = {k: v for k, v in payload.items() if k in allowed}
    dropped = sorted(set(payload) - set(kept))
    return kept, dropped


def compute_diff(
    current: dict[str, Any] | None, proposed: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    """Field-level diff for the approval screen: what is there now, what would change.

    Only fields that actually differ appear — an approval screen listing twenty
    unchanged fields is one nobody reads.
    """
    current = current or {}
    diff: dict[str, dict[str, Any]] = {}
    for field, proposed_value in proposed.items():
        current_value = current.get(field)
        if current_value != proposed_value:
            diff[field] = {"current": current_value, "proposed": proposed_value}
    return diff


class ZohoClient:
    def __init__(self, session, user_id: uuid.UUID):
        self._session = session
        self._user_id = user_id

    async def _auth(self) -> tuple[str, str]:
        connection = await get_connection(self._session, self._user_id, enums.Provider.zoho)
        if not connection.api_domain:
            raise CrmError(
                "This Zoho connection has no api_domain recorded. Reconnect it — the data "
                "centre must come from the token response, never a guess."
            )
        token = await get_valid_access_token(self._session, self._user_id, enums.Provider.zoho)
        return connection.api_domain.rstrip("/"), token

    async def _request(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        api_domain, token = await self._auth()
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request(
                method,
                f"{api_domain}/crm/v6{path}",
                headers={"Authorization": f"Zoho-oauthtoken {token}"},
                **kwargs,
            )

        if response.status_code == 204:
            return {"data": []}
        if not response.is_success:
            raise CrmError(f"Zoho {method} {path} returned {response.status_code}")
        return response.json()

    async def search(self, module: str, criteria: str | None = None, limit: int = 20) -> list[dict]:
        """COQL search. Read-only, and only against allowed modules."""
        if module not in READABLE_MODULES:
            raise ModuleNotAllowedError(
                f"{module} is not readable. Allowed: {sorted(READABLE_MODULES)}."
            )

        select_fields = ", ".join(sorted(FIELD_WHITELIST.get(module, {"id"})) or ["id"])
        query = f"select {select_fields} from {module}"
        if criteria:
            query += f" where {criteria}"
        query += f" limit {min(limit, 200)}"

        data = await self._request("POST", "/coql", json={"select_query": query})
        return data.get("data", [])

    async def get(self, module: str, record_id: str) -> dict[str, Any] | None:
        if module not in READABLE_MODULES:
            raise ModuleNotAllowedError(f"{module} is not readable.")
        data = await self._request("GET", f"/{module}/{record_id}")
        records = data.get("data", [])
        return records[0] if records else None

    async def create(self, module: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Create a record. Called only by approval execution, never by the model."""
        if module not in WRITABLE_MODULES:
            raise ModuleNotAllowedError(
                f"{module} is not writable. Allowed: {sorted(WRITABLE_MODULES)}."
            )
        kept, dropped = filter_payload(module, payload)
        if dropped:
            log.warning("crm.fields_dropped", module=module, dropped=dropped)
        if not kept:
            raise CrmError(f"Nothing to write: no whitelisted fields in the payload for {module}.")

        data = await self._request("POST", f"/{module}", json={"data": [kept]})
        return (data.get("data") or [{}])[0]

    async def update(self, module: str, record_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        if module not in WRITABLE_MODULES:
            raise ModuleNotAllowedError(f"{module} is not writable.")
        kept, dropped = filter_payload(module, payload)
        if dropped:
            log.warning("crm.fields_dropped", module=module, dropped=dropped)
        if not kept:
            raise CrmError("Nothing to write after field filtering.")

        data = await self._request("PUT", f"/{module}/{record_id}", json={"data": [kept]})
        return (data.get("data") or [{}])[0]

    # There is deliberately no delete method. See the module docstring.
