import base64
import hashlib
import hmac
import secrets
import time
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlencode, urlsplit

from dify_plugin import ToolProvider
from dify_plugin.entities.oauth import ToolOAuthCredentials
from dify_plugin.errors.tool import ToolProviderCredentialValidationError, ToolProviderOAuthError
from itsdangerous import BadData, URLSafeTimedSerializer
from werkzeug import Request

from revamp import client


def configuration(values: Mapping[str, Any]) -> tuple[str, str]:
    identifier, secret = values.get("client_id"), values.get("client_secret")
    if not isinstance(identifier, str) or not identifier or not isinstance(secret, str) or len(secret) < 32:
        raise ToolProviderOAuthError("Configure the Revamp connection's client ID and secret first.")
    return identifier, secret


def serializer(secret: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret, salt="revamp-dify-state-v1",
                                 signer_kwargs={"digest_method": hashlib.sha256})


def verifier(secret: str, state: str) -> str:
    # ToolProvider has no Dify storage session. Derive a per-attempt verifier from
    # the authenticated random state and a server-only secret. The verifier is
    # never placed in the browser URL, source, or returned account credentials.
    digest = hmac.digest(secret.encode(), b"revamp-dify-pkce-v1\0" + state.encode(), "sha256")
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def validate_redirect(value: str) -> None:
    url = urlsplit(value)
    if (url.scheme not in ("https", "http") or not url.hostname or url.username or
            url.password or url.query or url.fragment or
            (url.scheme == "http" and url.hostname not in ("localhost", "127.0.0.1", "::1"))):
        raise ToolProviderOAuthError("A valid Dify callback URL is required.")


def token_result(data: dict, previous_refresh: str | None = None) -> ToolOAuthCredentials:
    access, refresh, expires = data.get("access_token"), data.get("refresh_token", previous_refresh), data.get("expires_in")
    if (not isinstance(access, str) or not access or not isinstance(refresh, str) or not refresh or
            not isinstance(expires, (int, float)) or isinstance(expires, bool) or not 0 < expires <= 31536000 or
            str(data.get("token_type", "Bearer")).lower() != "bearer"):
        raise ToolProviderOAuthError("Revamp returned an invalid account connection. Please reconnect.")
    return ToolOAuthCredentials(credentials={"access_token": access, "refresh_token": refresh},
                                expires_at=int(time.time() + expires))


class RevampProvider(ToolProvider):
    def _validate_credentials(self, credentials: dict) -> None:
        try:
            token = credentials.get("access_token")
            if not isinstance(token, str) or not token:
                raise client.RevampError("Please connect your Revamp account.")
            client.account_id(token)
        except client.RevampError as error:
            raise ToolProviderCredentialValidationError(str(error)) from None

    def _oauth_get_authorization_url(self, redirect_uri: str, system_credentials: Mapping[str, Any]) -> str:
        identifier, secret = configuration(system_credentials)
        validate_redirect(redirect_uri)
        state = serializer(secret).dumps({"nonce": secrets.token_urlsafe(32),
                                          "client": identifier, "redirect": redirect_uri})
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier(secret, state).encode()).digest()).rstrip(b"=").decode()
        return client.BASE_URL + "/api/auth/mcp/authorize?" + urlencode({
            "client_id": identifier, "redirect_uri": redirect_uri, "response_type": "code",
            "scope": "openid email offline_access", "resource": client.BASE_URL + "/mcp",
            "state": state, "code_challenge": challenge, "code_challenge_method": "S256",
        })

    def _oauth_get_credentials(self, redirect_uri: str, system_credentials: Mapping[str, Any], request: Request) -> ToolOAuthCredentials:
        identifier, secret = configuration(system_credentials)
        validate_redirect(redirect_uri)
        if request.args.get("error"):
            raise ToolProviderOAuthError("The Revamp connection was not approved. Please connect again.")
        state, code = request.args.get("state"), request.args.get("code")
        if not state or len(state) > 4096 or not code or len(code) > 4096:
            raise ToolProviderOAuthError("The Revamp connection is incomplete. Please connect again.")
        try:
            data = serializer(secret).loads(state, max_age=600)
            if (not isinstance(data, dict) or data.get("client") != identifier or
                    data.get("redirect") != redirect_uri or not isinstance(data.get("nonce"), str)):
                raise ValueError("Invalid connection context")
        except (BadData, ValueError):
            raise ToolProviderOAuthError("The Revamp connection expired or is invalid. Please connect again.") from None
        try:
            result = client.request("POST", "/api/auth/mcp/token", auth=(identifier, secret), data={
                "grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
                "code_verifier": verifier(secret, state),
            })
            return token_result(result)
        except client.RevampError as error:
            raise ToolProviderOAuthError(str(error)) from None

    def _oauth_refresh_credentials(self, redirect_uri: str, system_credentials: Mapping[str, Any], credentials: Mapping[str, Any]) -> ToolOAuthCredentials:
        identifier, secret = configuration(system_credentials)
        refresh = credentials.get("refresh_token")
        if not isinstance(refresh, str) or not refresh:
            raise ToolProviderOAuthError("Please reconnect your Revamp account.")
        try:
            result = client.request("POST", "/api/auth/mcp/token", auth=(identifier, secret), data={
                "grant_type": "refresh_token", "refresh_token": refresh,
            })
            return token_result(result, refresh)
        except client.RevampError as error:
            raise ToolProviderOAuthError(str(error)) from None
