"""Fixed-origin adapter for Revamp's existing authenticated project tools."""

import hashlib
import json
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import UUID

import requests
from pydantic import BaseModel, ConfigDict, StrictStr, field_validator

BASE_URL = "https://app.revamp.dev"
TOOLS = frozenset({"start_new_website", "start_website_redesign", "start_web_app",
                   "check_project", "refine_project", "list_projects", "list_clients"})


class RevampError(Exception):
    """A bounded, customer-safe error; never includes HTTP headers or tokens."""


def request(method: str, path: str, token: str | None = None, **kwargs: Any) -> dict:
    headers = {"Accept": "application/json, text/event-stream" if path == "/api/make/mcp" else "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        response = requests.request(method, BASE_URL + path, headers=headers,
                                    timeout=(10, 90), allow_redirects=False, **kwargs)
    except requests.RequestException:
        raise RevampError("Revamp could not be reached. Please try again.") from None
    if response.status_code in (401, 403):
        raise RevampError("Please reconnect your Revamp account and try again.")
    if response.status_code == 429:
        raise RevampError("Revamp is receiving too many requests. Please try again shortly.")
    if response.status_code != 200:
        raise RevampError("Revamp could not complete this request. Please try again.")
    try:
        value = response.json()
    except ValueError:
        raise RevampError("Revamp returned an unexpected response.") from None
    if not isinstance(value, dict):
        raise RevampError("Revamp returned an unexpected response.")
    return value


def account_id(token: str) -> str:
    data = request("GET", "/api/auth/mcp/userinfo", token)
    if not isinstance(data.get("sub"), str) or not data["sub"]:
        raise RevampError("Please reconnect your Revamp account.")
    return data["sub"]


def stable_request_id(account: str, operation: str, reference: str, project: str = "") -> str:
    namespace = json.dumps(["revamp:dify:v1", account, operation, project, reference],
                           ensure_ascii=False, separators=(",", ":"))
    # Python 3.12 cannot construct UUIDv8 via the version argument yet.
    digest = bytearray(hashlib.sha256(namespace.encode()).digest()[:16])
    digest[6] = (digest[6] & 0x0F) | 0x80
    digest[8] = (digest[8] & 0x3F) | 0x80
    return str(UUID(bytes=bytes(digest)))


class Output(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Project(Output):
    projectId: UUID
    studioUrl: StrictStr

    @field_validator("studioUrl")
    @classmethod
    def studio_url(cls, value: str) -> str:
        url = urlsplit(value)
        if (url.scheme != "https" or url.netloc != "app.revamp.dev" or
                not url.path.startswith("/studio/") or url.username or url.password):
            raise ValueError("Unexpected Studio URL")
        return value


class Submitted(Project):
    projectName: StrictStr
    submissionId: StrictStr
    status: StrictStr


class Refined(Project):
    submissionId: StrictStr
    status: StrictStr


class Checked(Project):
    projectName: StrictStr
    status: StrictStr | None
    reply: StrictStr | None
    previewUrl: StrictStr | None

    @field_validator("previewUrl")
    @classmethod
    def preview_url(cls, value: str | None) -> str | None:
        if value is not None:
            url = urlsplit(value)
            if url.scheme != "https" or not url.hostname or url.username or url.password:
                raise ValueError("Unexpected preview URL")
        return value


class ListedProject(Project):
    name: StrictStr
    kind: Literal["redesign", "new_project"]
    originalUrl: StrictStr | None = None
    updatedAt: StrictStr | None = None


class Projects(Output):
    projects: list[ListedProject]


class Client(Output):
    clientId: UUID
    name: StrictStr
    status: Literal["pitching", "won", "live", "maintained"]


class Clients(Output):
    clients: list[Client]


OUTPUTS = {"start_new_website": Submitted, "start_website_redesign": Submitted,
           "start_web_app": Submitted, "refine_project": Refined,
           "check_project": Checked, "list_projects": Projects, "list_clients": Clients}


def call_tool(token: str, name: str, arguments: dict) -> dict:
    if name not in TOOLS:
        raise RevampError("This Revamp action is not supported.")
    envelope = request("POST", "/api/make/mcp", token, json={
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    })
    if envelope.get("jsonrpc") != "2.0" or type(envelope.get("id")) is not int or envelope.get("id") != 1:
        raise RevampError("Revamp returned an unexpected response.")
    if envelope.get("error"):
        raise RevampError("Revamp could not accept this action. Please check its inputs.")
    result = envelope.get("result")
    if not isinstance(result, dict):
        raise RevampError("Revamp returned an unexpected response.")
    if result.get("isError"):
        # Only the MCP tool's bounded customer-facing message, never the raw HTTP body.
        content = result.get("content")
        for part in content if isinstance(content, list) else []:
            if isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str):
                raise RevampError(part["text"][:1000])
        raise RevampError("Revamp could not complete this action.")
    try:
        return OUTPUTS[name].model_validate(result.get("structuredContent")).model_dump(mode="json")
    except (ValueError, TypeError):
        raise RevampError("Revamp returned an unexpected project response.") from None
