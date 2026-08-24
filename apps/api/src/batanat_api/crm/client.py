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

#: Which fields a *read* returns. Separate from the write whitelist above,
#: which only covers Leads and Notes because those are the only writable
#: modules — reusing it for reads meant Contacts and Deals came back as bare
#: ids, technically a successful call and useless to answer a question with.
#:
#: Still a whitelist rather than "everything": a CRM holds more about a person
#: than the agent needs, and anything named here can end up quoted in a reply.
READ_FIELDS: dict[str, frozenset[str]] = {
    "Leads": FIELD_WHITELIST["Leads"] | frozenset({"Lead_Status", "Created_Time"}),
    "Contacts": frozenset(
        {
            "First_Name",
            "Last_Name",
            "Email",
            "Phone",
            "Account_Name",
            "Title",
            "Mailing_City",
            "Created_Time",
        }
    ),
    "Deals": frozenset(
        {
            "Deal_Name",
            "Stage",
            "Amount",
            "Closing_Date",
            "Account_Name",
            "Probability",
            "Created_Time",
        }
    ),
    "Notes": frozenset({"Note_Title", "Note_Content", "Created_Time"}),
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

    async def _auth(self, *, force: bool = False) -> tuple[str, str]:
        connection = await get_connection(self._session, self._user_id, enums.Provider.zoho)
        if not connection.api_domain:
            raise CrmError(
                "This Zoho connection has no api_domain recorded. Reconnect it — the data "
                "centre must come from the token response, never a guess."
            )
        token = await get_valid_access_token(
            self._session, self._user_id, enums.Provider.zoho, force=force
        )
        return connection.api_domain.rstrip("/"), token

    async def _send(self, method: str, path: str, api_domain: str, token: str, **kwargs):
        async with httpx.AsyncClient(timeout=30.0) as client:
            return await client.request(
                method,
                f"{api_domain}/crm/v6{path}",
                headers={"Authorization": f"Zoho-oauthtoken {token}"},
                **kwargs,
            )

    async def _request(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        api_domain, token = await self._auth()
        response = await self._send(method, path, api_domain, token, **kwargs)

        # Same reasoning as the Gmail client: a 401 is evidence the stored token
        # is dead, not that the grant is. Refresh once and retry before failing,
        # or a token Zoho invalidated early strands every CRM read behind an
        # error that tells the user to reconnect something that is fine.
        if response.status_code == 401:
            log.info("crm.token_rejected", detail="forcing a refresh and retrying once")
            api_domain, token = await self._auth(force=True)
            response = await self._send(method, path, api_domain, token, **kwargs)

        if response.status_code == 204:
            return {"data": []}
        if response.status_code == 401:
            raise CrmError(
                "Zoho rejected the access token even after refreshing it. "
                "Reconnect Zoho under Settings → Connections."
            )
        if not response.is_success:
            raise CrmError(
                f"Zoho {method} {path} returned {response.status_code}: {response.text[:200]}"
            )
        return response.json()

    async def search(self, module: str, criteria: str | None = None, limit: int = 20) -> list[dict]:
        """Records from one module, read-only.

        Uses the module endpoints rather than COQL. COQL is the nicer query
        language, but it sits behind `ZohoCRM.coql.READ` — a scope this app
        deliberately does not request, because it grants read across every
        module including ones outside `READABLE_MODULES`. Asking for it to make
        one query tidier would widen the grant well past what the agent needs.

        So: a plain list when there is no filter, and Zoho's `/search` endpoint
        when there is. Both are covered by the per-module read scopes already
        held, which is why this works without reconnecting.
        """
        if module not in READABLE_MODULES:
            raise ModuleNotAllowedError(
                f"{module} is not readable. Allowed: {sorted(READABLE_MODULES)}."
            )

        # `fields` is required by Zoho and doubles as a read whitelist: anything
        # not named here never leaves the CRM.
        fields = ",".join(sorted(READ_FIELDS.get(module, {"id"})) or ["id"])
        params: dict[str, Any] = {"fields": fields, "per_page": min(limit, 200)}

        if criteria:
            params["criteria"] = criteria
            data = await self._request("GET", f"/{module}/search", params=params)
        else:
            data = await self._request("GET", f"/{module}", params=params)

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
