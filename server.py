"""
Planning Center Services MCP Server
===================================
MCP server that exposes full CRUD access to the Planning Center Services API.

Hosted on Render.com (Streamable HTTP). Users pass their own Personal Access Token
(client_id + secret) as tool parameters — credentials never live on the server.

Docs: https://developer.planning.center/docs/#/apps/services
Base: https://api.planningcenteronline.com/services/v2
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional

import httpx
from mcp.server.fastmcp import FastMCP

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

BASE_URL = "https://api.planningcenteronline.com/services/v2"
DEFAULT_TIMEOUT = 30.0
MAX_PER_PAGE = 100

mcp = FastMCP(
    "Planning Center Services",
    instructions=(
        "This server gives full read/write access to the Planning Center Services API "
        "(service types, plans, items, songs, arrangements, keys, teams, people, etc.). "
        "Every tool requires the user's Personal Access Token pair: client_id and secret. "
        "Create a PAT at https://api.planningcenteronline.com/personal_access_tokens "
        "(or use an OAuth access_token if you prefer — pass it as client_id and leave secret empty)."
    ),
)

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def _auth_header(client_id: str, secret: str = "") -> dict[str, str]:
    """Build Authorization header. Supports Basic (PAT) or Bearer (OAuth token)."""
    if secret:
        # Personal Access Token → HTTP Basic
        import base64

        token = base64.b64encode(f"{client_id}:{secret}".encode()).decode()
        return {"Authorization": f"Basic {token}"}
    # Assume client_id is already a Bearer access_token
    return {"Authorization": f"Bearer {client_id}"}


async def _request(
    method: str,
    path: str,
    client_id: str,
    secret: str = "",
    params: Optional[dict[str, Any]] = None,
    json_body: Optional[dict[str, Any]] = None,
    include: Optional[str] = None,
    per_page: Optional[int] = None,
    offset: Optional[int] = None,
    order: Optional[str] = None,
    where: Optional[dict[str, str]] = None,
    filter_: Optional[str] = None,
) -> dict[str, Any]:
    """Low-level authenticated request against the Services API."""
    if not path.startswith("/"):
        path = "/" + path
    url = f"{BASE_URL}{path}"

    query: dict[str, Any] = {}
    if params:
        query.update(params)
    if include:
        query["include"] = include
    if per_page is not None:
        query["per_page"] = min(max(1, per_page), MAX_PER_PAGE)
    if offset is not None:
        query["offset"] = max(0, offset)
    if order:
        query["order"] = order
    if filter_:
        query["filter"] = filter_
    if where:
        for k, v in where.items():
            query[f"where[{k}]"] = v

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        **_auth_header(client_id, secret),
    }

    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        resp = await client.request(
            method.upper(),
            url,
            headers=headers,
            params=query or None,
            json=json_body,
        )

    try:
        data = resp.json() if resp.content else {}
    except Exception:
        data = {"raw": resp.text}

    if resp.status_code >= 400:
        return {
            "error": True,
            "status_code": resp.status_code,
            "message": data.get("errors") or data.get("message") or resp.text,
            "body": data,
        }

    return data


def _json_api_create(type_: str, attributes: dict[str, Any], relationships: Optional[dict] = None) -> dict:
    """Build a JSON:API create/update payload."""
    payload: dict[str, Any] = {
        "data": {
            "type": type_,
            "attributes": attributes,
        }
    }
    if relationships:
        payload["data"]["relationships"] = relationships
    return payload


def _ok(result: Any) -> str:
    """Serialize tool result as pretty JSON string (MCP tools return text)."""
    return json.dumps(result, indent=2, ensure_ascii=False, default=str)


# -----------------------------------------------------------------------------
# GENERIC CRUD TOOL (covers every endpoint)
# -----------------------------------------------------------------------------


@mcp.tool()
async def pco_services_request(
    client_id: str,
    secret: str,
    method: str,
    path: str,
    query: Optional[dict[str, Any]] = None,
    body: Optional[dict[str, Any]] = None,
    include: Optional[str] = None,
    per_page: Optional[int] = None,
    offset: Optional[int] = None,
    order: Optional[str] = None,
    where: Optional[dict[str, str]] = None,
    filter: Optional[str] = None,
) -> str:
    """
    Generic authenticated request to any Planning Center Services API endpoint.
    Use this for full access to every resource (service_types, plans, items, songs,
    arrangements, keys, teams, team_positions, people, plan_people, etc.).

    Args:
        client_id: Personal Access Token application ID (or OAuth access_token).
        secret: Personal Access Token secret (leave empty if using OAuth Bearer token).
        method: HTTP method – GET, POST, PATCH, DELETE.
        path: Path relative to /services/v2 (e.g. "/service_types", "/songs/123",
              "/service_types/1/plans/2/items").
        query: Extra query parameters as a dict.
        body: JSON body for POST/PATCH (must already be JSON:API shape if needed,
              or use the convenience tools below).
        include: Comma-separated relationships to include (e.g. "items,plan_people").
        per_page: Page size (1-100, default 25).
        offset: Pagination offset.
        order: Sort order (e.g. "created_at", "-updated_at").
        where: Filter by attributes, e.g. {"title": "Sunday Service"}.
        filter: Named filter provided by the endpoint (e.g. "future", "past").
    """
    result = await _request(
        method=method,
        path=path,
        client_id=client_id,
        secret=secret,
        params=query,
        json_body=body,
        include=include,
        per_page=per_page,
        offset=offset,
        order=order,
        where=where,
        filter_=filter,
    )
    return _ok(result)


# -----------------------------------------------------------------------------
# CONVENIENCE TOOLS – Service Types
# -----------------------------------------------------------------------------


@mcp.tool()
async def list_service_types(
    client_id: str,
    secret: str,
    per_page: int = 25,
    offset: int = 0,
    include: Optional[str] = None,
    order: Optional[str] = None,
) -> str:
    """List all Service Types."""
    return _ok(
        await _request(
            "GET",
            "/service_types",
            client_id,
            secret,
            per_page=per_page,
            offset=offset,
            include=include,
            order=order,
        )
    )


@mcp.tool()
async def get_service_type(
    client_id: str,
    secret: str,
    service_type_id: str,
    include: Optional[str] = None,
) -> str:
    """Get a single Service Type by ID."""
    return _ok(
        await _request(
            "GET",
            f"/service_types/{service_type_id}",
            client_id,
            secret,
            include=include,
        )
    )


@mcp.tool()
async def create_service_type(
    client_id: str,
    secret: str,
    name: str,
    frequency: Optional[str] = None,
    sequence: Optional[int] = None,
    parent_id: Optional[str] = None,
    extra_attributes: Optional[dict[str, Any]] = None,
) -> str:
    """Create a new Service Type."""
    attrs: dict[str, Any] = {"name": name}
    if frequency:
        attrs["frequency"] = frequency
    if sequence is not None:
        attrs["sequence"] = sequence
    if extra_attributes:
        attrs.update(extra_attributes)

    relationships = None
    if parent_id:
        relationships = {"parent": {"data": {"type": "Folder", "id": parent_id}}}

    body = _json_api_create("ServiceType", attrs, relationships)
    return _ok(await _request("POST", "/service_types", client_id, secret, json_body=body))


@mcp.tool()
async def update_service_type(
    client_id: str,
    secret: str,
    service_type_id: str,
    attributes: dict[str, Any],
) -> str:
    """Update a Service Type (pass only the attributes you want to change)."""
    body = {
        "data": {
            "type": "ServiceType",
            "id": service_type_id,
            "attributes": attributes,
        }
    }
    return _ok(
        await _request(
            "PATCH",
            f"/service_types/{service_type_id}",
            client_id,
            secret,
            json_body=body,
        )
    )


@mcp.tool()
async def delete_service_type(
    client_id: str,
    secret: str,
    service_type_id: str,
) -> str:
    """Delete a Service Type."""
    return _ok(
        await _request("DELETE", f"/service_types/{service_type_id}", client_id, secret)
    )


# -----------------------------------------------------------------------------
# Plans
# -----------------------------------------------------------------------------


@mcp.tool()
async def list_plans(
    client_id: str,
    secret: str,
    service_type_id: str,
    per_page: int = 25,
    offset: int = 0,
    include: Optional[str] = None,
    filter: Optional[str] = None,
    order: Optional[str] = None,
) -> str:
    """List plans belonging to a Service Type. filter can be 'future', 'past', 'no_dates'."""
    return _ok(
        await _request(
            "GET",
            f"/service_types/{service_type_id}/plans",
            client_id,
            secret,
            per_page=per_page,
            offset=offset,
            include=include,
            filter_=filter,
            order=order,
        )
    )


@mcp.tool()
async def get_plan(
    client_id: str,
    secret: str,
    service_type_id: str,
    plan_id: str,
    include: Optional[str] = None,
) -> str:
    """Get a single Plan."""
    return _ok(
        await _request(
            "GET",
            f"/service_types/{service_type_id}/plans/{plan_id}",
            client_id,
            secret,
            include=include,
        )
    )


@mcp.tool()
async def create_plan(
    client_id: str,
    secret: str,
    service_type_id: str,
    attributes: dict[str, Any],
) -> str:
    """
    Create a Plan under a Service Type.
    Common attributes: title, series_title, notes, public, etc.
    See API docs for full list.
    """
    body = _json_api_create("Plan", attributes)
    return _ok(
        await _request(
            "POST",
            f"/service_types/{service_type_id}/plans",
            client_id,
            secret,
            json_body=body,
        )
    )


@mcp.tool()
async def update_plan(
    client_id: str,
    secret: str,
    service_type_id: str,
    plan_id: str,
    attributes: dict[str, Any],
) -> str:
    """Update a Plan."""
    body = {
        "data": {
            "type": "Plan",
            "id": plan_id,
            "attributes": attributes,
        }
    }
    return _ok(
        await _request(
            "PATCH",
            f"/service_types/{service_type_id}/plans/{plan_id}",
            client_id,
            secret,
            json_body=body,
        )
    )


@mcp.tool()
async def delete_plan(
    client_id: str,
    secret: str,
    service_type_id: str,
    plan_id: str,
) -> str:
    """Delete a Plan."""
    return _ok(
        await _request(
            "DELETE",
            f"/service_types/{service_type_id}/plans/{plan_id}",
            client_id,
            secret,
        )
    )


# -----------------------------------------------------------------------------
# Items (order of service)
# -----------------------------------------------------------------------------


@mcp.tool()
async def list_items(
    client_id: str,
    secret: str,
    service_type_id: str,
    plan_id: str,
    per_page: int = 100,
    include: Optional[str] = None,
) -> str:
    """List items (songs, headers, media, etc.) of a Plan."""
    return _ok(
        await _request(
            "GET",
            f"/service_types/{service_type_id}/plans/{plan_id}/items",
            client_id,
            secret,
            per_page=per_page,
            include=include,
        )
    )


@mcp.tool()
async def get_item(
    client_id: str,
    secret: str,
    service_type_id: str,
    plan_id: str,
    item_id: str,
    include: Optional[str] = None,
) -> str:
    """Get a single Item."""
    return _ok(
        await _request(
            "GET",
            f"/service_types/{service_type_id}/plans/{plan_id}/items/{item_id}",
            client_id,
            secret,
            include=include,
        )
    )


@mcp.tool()
async def create_item(
    client_id: str,
    secret: str,
    service_type_id: str,
    plan_id: str,
    title: str,
    item_type: str = "song",
    song_id: Optional[str] = None,
    arrangement_id: Optional[str] = None,
    key_id: Optional[str] = None,
    sequence: Optional[int] = None,
    length: Optional[int] = None,
    description: Optional[str] = None,
    extra_attributes: Optional[dict[str, Any]] = None,
) -> str:
    """
    Create an Item in a Plan.
    item_type: "song" | "header" | "media" | "item"
    """
    attrs: dict[str, Any] = {
        "title": title,
        "item_type": item_type,
    }
    if sequence is not None:
        attrs["sequence"] = sequence
    if length is not None:
        attrs["length"] = length
    if description:
        attrs["description"] = description
    if extra_attributes:
        attrs.update(extra_attributes)

    relationships: dict[str, Any] = {}
    if song_id:
        relationships["song"] = {"data": {"type": "Song", "id": song_id}}
    if arrangement_id:
        relationships["arrangement"] = {"data": {"type": "Arrangement", "id": arrangement_id}}
    if key_id:
        relationships["key"] = {"data": {"type": "Key", "id": key_id}}

    body = _json_api_create("Item", attrs, relationships or None)
    return _ok(
        await _request(
            "POST",
            f"/service_types/{service_type_id}/plans/{plan_id}/items",
            client_id,
            secret,
            json_body=body,
        )
    )


@mcp.tool()
async def update_item(
    client_id: str,
    secret: str,
    service_type_id: str,
    plan_id: str,
    item_id: str,
    attributes: dict[str, Any],
) -> str:
    """Update an Item."""
    body = {
        "data": {
            "type": "Item",
            "id": item_id,
            "attributes": attributes,
        }
    }
    return _ok(
        await _request(
            "PATCH",
            f"/service_types/{service_type_id}/plans/{plan_id}/items/{item_id}",
            client_id,
            secret,
            json_body=body,
        )
    )


@mcp.tool()
async def delete_item(
    client_id: str,
    secret: str,
    service_type_id: str,
    plan_id: str,
    item_id: str,
) -> str:
    """Delete an Item from a Plan."""
    return _ok(
        await _request(
            "DELETE",
            f"/service_types/{service_type_id}/plans/{plan_id}/items/{item_id}",
            client_id,
            secret,
        )
    )


# -----------------------------------------------------------------------------
# Songs
# -----------------------------------------------------------------------------


@mcp.tool()
async def list_songs(
    client_id: str,
    secret: str,
    per_page: int = 25,
    offset: int = 0,
    include: Optional[str] = None,
    order: Optional[str] = None,
    where: Optional[dict[str, str]] = None,
) -> str:
    """List songs in the organization library."""
    return _ok(
        await _request(
            "GET",
            "/songs",
            client_id,
            secret,
            per_page=per_page,
            offset=offset,
            include=include,
            order=order,
            where=where,
        )
    )


@mcp.tool()
async def get_song(
    client_id: str,
    secret: str,
    song_id: str,
    include: Optional[str] = None,
) -> str:
    """Get a single Song."""
    return _ok(
        await _request(
            "GET",
            f"/songs/{song_id}",
            client_id,
            secret,
            include=include,
        )
    )


@mcp.tool()
async def create_song(
    client_id: str,
    secret: str,
    title: str,
    author: Optional[str] = None,
    ccli_number: Optional[int] = None,
    copyright: Optional[str] = None,
    themes: Optional[str] = None,
    hidden: bool = False,
    extra_attributes: Optional[dict[str, Any]] = None,
) -> str:
    """Create a new Song in the library."""
    attrs: dict[str, Any] = {"title": title, "hidden": hidden}
    if author:
        attrs["author"] = author
    if ccli_number is not None:
        attrs["ccli_number"] = ccli_number
    if copyright:
        attrs["copyright"] = copyright
    if themes:
        attrs["themes"] = themes
    if extra_attributes:
        attrs.update(extra_attributes)

    body = _json_api_create("Song", attrs)
    return _ok(await _request("POST", "/songs", client_id, secret, json_body=body))


@mcp.tool()
async def update_song(
    client_id: str,
    secret: str,
    song_id: str,
    attributes: dict[str, Any],
) -> str:
    """Update a Song."""
    body = {
        "data": {
            "type": "Song",
            "id": song_id,
            "attributes": attributes,
        }
    }
    return _ok(
        await _request("PATCH", f"/songs/{song_id}", client_id, secret, json_body=body)
    )


@mcp.tool()
async def delete_song(
    client_id: str,
    secret: str,
    song_id: str,
) -> str:
    """Delete a Song."""
    return _ok(await _request("DELETE", f"/songs/{song_id}", client_id, secret))


# -----------------------------------------------------------------------------
# Arrangements & Keys
# -----------------------------------------------------------------------------


@mcp.tool()
async def list_arrangements(
    client_id: str,
    secret: str,
    song_id: str,
    per_page: int = 25,
    include: Optional[str] = None,
) -> str:
    """List arrangements of a Song."""
    return _ok(
        await _request(
            "GET",
            f"/songs/{song_id}/arrangements",
            client_id,
            secret,
            per_page=per_page,
            include=include,
        )
    )


@mcp.tool()
async def create_arrangement(
    client_id: str,
    secret: str,
    song_id: str,
    name: str,
    bpm: Optional[float] = None,
    meter: Optional[str] = None,
    length: Optional[int] = None,
    lyrics: Optional[str] = None,
    chord_chart: Optional[str] = None,
    extra_attributes: Optional[dict[str, Any]] = None,
) -> str:
    """Create an Arrangement for a Song."""
    attrs: dict[str, Any] = {"name": name}
    if bpm is not None:
        attrs["bpm"] = bpm
    if meter:
        attrs["meter"] = meter
    if length is not None:
        attrs["length"] = length
    if lyrics:
        attrs["lyrics"] = lyrics
    if chord_chart:
        attrs["chord_chart"] = chord_chart
    if extra_attributes:
        attrs.update(extra_attributes)

    body = _json_api_create("Arrangement", attrs)
    return _ok(
        await _request(
            "POST",
            f"/songs/{song_id}/arrangements",
            client_id,
            secret,
            json_body=body,
        )
    )


@mcp.tool()
async def list_keys(
    client_id: str,
    secret: str,
    song_id: str,
    arrangement_id: str,
) -> str:
    """List keys of an Arrangement."""
    return _ok(
        await _request(
            "GET",
            f"/songs/{song_id}/arrangements/{arrangement_id}/keys",
            client_id,
            secret,
        )
    )


@mcp.tool()
async def create_key(
    client_id: str,
    secret: str,
    song_id: str,
    arrangement_id: str,
    name: str,
    starting_key: Optional[str] = None,
    ending_key: Optional[str] = None,
) -> str:
    """Create a Key for an Arrangement."""
    attrs: dict[str, Any] = {"name": name}
    if starting_key:
        attrs["starting_key"] = starting_key
    if ending_key:
        attrs["ending_key"] = ending_key

    body = _json_api_create("Key", attrs)
    return _ok(
        await _request(
            "POST",
            f"/songs/{song_id}/arrangements/{arrangement_id}/keys",
            client_id,
            secret,
            json_body=body,
        )
    )


# -----------------------------------------------------------------------------
# Teams
# -----------------------------------------------------------------------------


@mcp.tool()
async def list_teams(
    client_id: str,
    secret: str,
    service_type_id: Optional[str] = None,
    per_page: int = 25,
    include: Optional[str] = None,
) -> str:
    """List teams. If service_type_id is given, list teams of that Service Type."""
    path = (
        f"/service_types/{service_type_id}/teams"
        if service_type_id
        else "/teams"
    )
    return _ok(
        await _request(
            "GET",
            path,
            client_id,
            secret,
            per_page=per_page,
            include=include,
        )
    )


@mcp.tool()
async def create_team(
    client_id: str,
    secret: str,
    service_type_id: str,
    name: str,
    schedule_to: Optional[str] = None,
    extra_attributes: Optional[dict[str, Any]] = None,
) -> str:
    """Create a Team under a Service Type."""
    attrs: dict[str, Any] = {"name": name}
    if schedule_to:
        attrs["schedule_to"] = schedule_to
    if extra_attributes:
        attrs.update(extra_attributes)

    body = _json_api_create("Team", attrs)
    return _ok(
        await _request(
            "POST",
            f"/service_types/{service_type_id}/teams",
            client_id,
            secret,
            json_body=body,
        )
    )


# -----------------------------------------------------------------------------
# Health / utility
# -----------------------------------------------------------------------------


@mcp.tool()
async def health_check() -> str:
    """Simple health check – does not call Planning Center."""
    return _ok({"status": "ok", "service": "Planning Center Services MCP"})


# Custom HTTP route for Render health checks (not an MCP tool)
from starlette.requests import Request
from starlette.responses import JSONResponse


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "service": "pco-services-mcp"})


# -----------------------------------------------------------------------------
# Entrypoint (Render / local)
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 10000))

    # streamable_http_app() already exposes the MCP endpoint at /mcp
    # and also includes any @mcp.custom_route (e.g. /health)
    app = mcp.streamable_http_app()

    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
