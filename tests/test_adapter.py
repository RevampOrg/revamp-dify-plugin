"""SDK wiring + real loopback HTTP adapter tests; no remote services or LLM."""
import base64
import hashlib
import json
import select
import shutil
import subprocess
import threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from dify_plugin import DifyPluginEnv
from dify_plugin.core.plugin_registration import PluginRegistration
from dify_plugin.errors.tool import ToolProviderOAuthError
from itsdangerous.timed import TimestampSigner
from werkzeug import Request

from provider.revamp import RevampProvider, serializer
from revamp import client

PROJECT = "00000000-0000-4000-8000-000000000001"
FOLDER = "00000000-0000-4000-8000-000000000002"
STUDIO = f"https://app.revamp.dev/studio/{PROJECT}"
CONFIG = {"client_id": "fixture-client", "client_secret": "fixture-secret-" + "x" * 40}
CALLBACK = "https://cloud.dify.ai/console/api/oauth/plugin/revamp/tool/callback"


@pytest.fixture(scope="module")
def registry():
    return PluginRegistration(DifyPluginEnv())


@pytest.fixture
def service(monkeypatch):
    calls = []
    state = {"response": None, "status": 200, "account": "fixture-account"}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def respond(self, data, status=200):
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())

        def do_GET(self):
            calls.append((self.path, dict(self.headers), None))
            assert self.path == "/api/auth/mcp/userinfo"
            assert self.headers["Authorization"] == "Bearer fixture-access"
            self.respond({"sub": state["account"]})

        def do_POST(self):
            raw = self.rfile.read(int(self.headers["Content-Length"])).decode()
            if self.path == "/api/auth/mcp/token":
                data = parse_qs(raw)
                calls.append((self.path, dict(self.headers), data))
                expected = base64.b64encode((CONFIG["client_id"] + ":" + CONFIG["client_secret"]).encode()).decode()
                assert self.headers["Authorization"] == "Basic " + expected
                self.respond({"access_token": "fixture-access", "refresh_token": "fixture-rotated", "expires_in": 3600})
                return
            assert self.path == "/api/make/mcp"
            assert self.headers["Authorization"] == "Bearer fixture-access"
            accepted = {part.strip() for part in self.headers.get("Accept", "").split(",")}
            if not {"application/json", "text/event-stream"} <= accepted:
                self.respond({"jsonrpc": "2.0", "id": 1, "error": {
                    "code": -32000, "message": "Client must accept both application/json and text/event-stream"
                }}, 406)
                return
            data = json.loads(raw)
            calls.append((self.path, dict(self.headers), data))
            assert data["method"] == "tools/call"
            name = data["params"]["name"]
            output = {"projectId": PROJECT, "studioUrl": STUDIO, "projectName": "Fixture",
                      "submissionId": "fixture-turn", "status": "queued"}
            if name == "refine_project":
                output.pop("projectName")
            if name == "check_project":
                output = {"projectId": PROJECT, "studioUrl": STUDIO, "projectName": "Fixture",
                          "status": "completed", "reply": "The build failed.", "previewUrl": None}
            if name == "list_projects":
                output = {"projects": [{"projectId": PROJECT, "studioUrl": STUDIO, "name": "Fixture", "kind": "new_project"}]}
            if name == "list_clients":
                output = {"clients": [{"clientId": FOLDER, "name": "Fixture", "status": "won"}]}
            self.respond(state["response"] or {"jsonrpc": "2.0", "id": 1, "result": {"structuredContent": output}}, state["status"])

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    monkeypatch.setattr(client, "BASE_URL", origin)
    original_request = client.requests.request

    def guarded_request(method, url, **kwargs):
        assert url.startswith(origin + "/"), "Unexpected outbound request"
        assert kwargs["allow_redirects"] is False
        return original_request(method, url, **kwargs)

    monkeypatch.setattr(client.requests, "request", guarded_request)
    yield calls, state
    server.shutdown()
    thread.join()
    server.server_close()


def invoke(registry, name, parameters):
    tool_class = registry.tools_mapping["revamp"][2][name][1]
    tool = tool_class.from_credentials({"access_token": "fixture-access"})
    return list(tool.invoke(parameters))


def test_registered_tool_against_revamp_mcp_transport(registry, monkeypatch):
    sdk = Path(__file__).resolve().parents[3] / "apps/app/node_modules/@modelcontextprotocol/sdk"
    node = shutil.which("node")
    if not node or not sdk.is_dir():
        pytest.skip("Requires the Revamp monorepo's installed Node/MCP dependencies")
    process = subprocess.Popen([node, str(Path(__file__).with_name("mcp_transport_fixture.mjs")), str(sdk)],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert select.select([process.stdout], [], [], 10)[0], "Local MCP transport did not start"
        port = process.stdout.readline().strip()
        assert port.isdigit(), "Local MCP transport did not return a port"
        origin = f"http://127.0.0.1:{port}"
        monkeypatch.setattr(client, "BASE_URL", origin)
        original = client.requests.request

        def guarded(method, url, **kwargs):
            assert url == origin + "/api/make/mcp", "Unexpected outbound request"
            return original(method, url, **kwargs)

        monkeypatch.setattr(client.requests, "request", guarded)
        # Establish that this real transport reproduces the native Dify failure.
        rejected = client.requests.request("POST", origin + "/api/make/mcp",
            headers={"Authorization": "Bearer fixture-access", "Accept": "application/json"},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                  "params": {"name": "list_projects", "arguments": {}}},
            timeout=(5, 5), allow_redirects=False)
        assert rejected.status_code == 406
        messages = invoke(registry, "list_projects", {})
        assert messages[0].message.json_object == {"projects": []}
    finally:
        process.terminate()
        process.wait(timeout=5)
        process.stdout.close()
        process.stderr.close()


def test_sdk_registration_and_output_contracts(registry):
    assert set(registry.tools_mapping["revamp"][2]) == client.TOOLS

    def without_descriptions(value):
        if isinstance(value, dict):
            return {key: without_descriptions(item) for key, item in value.items() if key != "description"}
        if isinstance(value, list):
            return [without_descriptions(item) for item in value]
        return value

    for name, (configuration, _) in registry.tools_mapping["revamp"][2].items():
        assert without_descriptions(configuration.output_schema) == without_descriptions(client.OUTPUTS[name].model_json_schema())
    assert registry.tools_mapping["revamp"][0].oauth_schema


@pytest.mark.parametrize("name", sorted(client.TOOLS))
def test_registered_tools_over_real_http(registry, service, name):
    calls, _ = service
    parameters = {"name": "Fixture", "brief": "A simple website", "url": "https://example.org",
                  "projectId": PROJECT, "submissionId": "fixture-turn", "instruction": "Change the heading",
                  "requestReference": "fixture-record-v1", "clientId": FOLDER}
    messages = invoke(registry, name, parameters)
    assert messages[0].type.value == "json"
    output = messages[0].message.json_object
    assert output
    rpc = calls[-1][2]
    assert rpc["params"]["name"] == name
    arguments = rpc["params"]["arguments"]
    if name.startswith("start_") or name == "refine_project":
        assert calls[0][0] == "/api/auth/mcp/userinfo"
        first_id = arguments["requestId"]
        invoke(registry, name, parameters)
        assert calls[-1][2]["params"]["arguments"]["requestId"] == first_id
        invoke(registry, name, {**parameters, "requestReference": "fixture-record-v2"})
        assert calls[-1][2]["params"]["arguments"]["requestId"] != first_id
    else:
        assert len(calls) == 1  # Read actions do not create a generation request.
    if name == "check_project":
        assert output["status"] == "completed" and output["previewUrl"] is None
        assert output["reply"] == "The build failed."
    if name.startswith("list_"):
        assert arguments == {}


def test_request_identity_account_action_and_project_scoping():
    values = [client.stable_request_id(*args) for args in [
        ("a", "start_new_website", "record"), ("b", "start_new_website", "record"),
        ("a", "start_web_app", "record"), ("a", "refine_project", "record", PROJECT),
        ("a", "refine_project", "record", FOLDER)]]
    assert len(set(values)) == len(values)


@pytest.mark.parametrize("parameters", [
    {"name": "Fixture", "brief": "Short"},
    {"name": "Fixture", "brief": "x" * 2001, "requestReference": "one"},
    {"name": "Fixture", "brief": "Short", "requestReference": "one", "clientId": "invalid"},
])
def test_invalid_creation_inputs_never_reach_service(registry, service, parameters):
    calls, _ = service
    with pytest.raises(client.RevampError):
        invoke(registry, "start_new_website", parameters)
    assert not calls


@pytest.mark.parametrize("response", [
    {"jsonrpc": "2.0", "id": 1, "result": {"structuredContent": {"projectId": "invalid"}}},
    {"jsonrpc": "2.0", "id": True, "result": {}},
    {"jsonrpc": "2.0", "id": 1, "error": {"message": "private-server-detail"}},
    {"jsonrpc": "2.0", "id": 1, "result": {"isError": True, "content": None}},
])
def test_malformed_and_rpc_errors_are_safe(registry, service, response):
    _, state = service
    state["response"] = response
    with pytest.raises(client.RevampError) as error:
        invoke(registry, "check_project", {"projectId": PROJECT})
    assert "private-server-detail" not in str(error.value)


def test_credit_admission_error_is_preserved(registry, service):
    _, state = service
    state["response"] = {"jsonrpc": "2.0", "id": 1, "result": {"isError": True,
                          "content": [{"type": "text", "text": "You need more Revamp credits to continue."}]}}
    with pytest.raises(client.RevampError, match="more Revamp credits"):
        invoke(registry, "start_new_website", {"name": "Fixture", "brief": "Short", "requestReference": "one"})


def test_connection_pkce_callback_and_rotating_refresh(service):
    calls, _ = service
    provider = RevampProvider()
    urls = [parse_qs(urlsplit(provider.oauth_get_authorization_url(CALLBACK, CONFIG)).query) for _ in range(2)]
    assert urls[0]["state"] != urls[1]["state"]
    assert urls[0]["code_challenge"] != urls[1]["code_challenge"]
    for values in urls:
        assert values["code_challenge_method"] == ["S256"]
        assert CONFIG["client_secret"] not in json.dumps(values)
        callback = Request.from_values(query_string=urlencode({"code": "fixture-code", "state": values["state"][0]}))
        credential = provider.oauth_get_credentials(CALLBACK, CONFIG, callback)
        sent = calls[-1][2]
        challenge = base64.urlsafe_b64encode(hashlib.sha256(sent["code_verifier"][0].encode()).digest()).rstrip(b"=").decode()
        assert challenge == values["code_challenge"][0]
        assert set(credential.credentials) == {"access_token", "refresh_token"}
    refreshed = provider.oauth_refresh_credentials(CALLBACK, CONFIG, {"refresh_token": "fixture-old"})
    assert calls[-1][2]["refresh_token"] == ["fixture-old"]
    assert refreshed.credentials["refresh_token"] == "fixture-rotated"
    provider.validate_credentials(dict(refreshed.credentials))


@pytest.mark.parametrize("failure", ["tampered", "wrong-client", "wrong-callback", "expired", "denied"])
def test_bad_oauth_context_never_exchanges_tokens(service, monkeypatch, failure):
    calls, _ = service
    provider = RevampProvider()
    state = parse_qs(urlsplit(provider.oauth_get_authorization_url(CALLBACK, CONFIG)).query)["state"][0]
    config, callback_url = CONFIG, CALLBACK
    if failure == "tampered":
        state += "x"
    if failure == "wrong-client":
        config = {**CONFIG, "client_id": "other-client"}
    if failure == "wrong-callback":
        callback_url += "-other"
    if failure == "expired":
        original = TimestampSigner.get_timestamp
        monkeypatch.setattr(TimestampSigner, "get_timestamp", lambda self: original(self) - 601)
        state = serializer(CONFIG["client_secret"]).dumps({"client": CONFIG["client_id"], "redirect": CALLBACK, "nonce": "fixture"})
        monkeypatch.setattr(TimestampSigner, "get_timestamp", original)
    args = {"code": "fixture-code", "state": state}
    if failure == "denied":
        args["error"] = "access_denied"
    with pytest.raises(ToolProviderOAuthError):
        provider.oauth_get_credentials(callback_url, config, Request.from_values(query_string=urlencode(args)))
    assert not calls


def test_http_redirect_does_not_forward_credentials(registry, service):
    calls, state = service
    state["status"] = 302
    with pytest.raises(client.RevampError):
        invoke(registry, "list_projects", {})
    assert len(calls) == 1


def test_optional_empty_fields_and_foreign_studio_url(registry, service):
    calls, state = service
    invoke(registry, "start_website_redesign", {"name": "Fixture", "url": "https://example.org",
           "brief": None, "clientId": None, "requestReference": "one"})
    assert "clientId" not in calls[-1][2]["params"]["arguments"]
    state["response"] = {"jsonrpc": "2.0", "id": 1, "result": {"structuredContent": {
        "projectId": PROJECT, "projectName": "Fixture", "studioUrl": "https://untrusted.example/studio/" + PROJECT,
        "status": None, "reply": None, "previewUrl": None}}}
    with pytest.raises(client.RevampError, match="unexpected project response"):
        invoke(registry, "check_project", {"projectId": PROJECT})
