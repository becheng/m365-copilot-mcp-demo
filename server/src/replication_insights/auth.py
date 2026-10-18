import logging
import math
import time
from uuid import UUID

from fastmcp.server.auth import AccessToken, RemoteAuthProvider
from fastmcp.server.auth.providers.jwt import JWTVerifier
from pydantic import AnyHttpUrl, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class AuthSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )
    tenant_id: UUID = Field(validation_alias="ENTRA_TENANT_ID")
    api_client_id: UUID = Field(validation_alias="ENTRA_API_CLIENT_ID")
    accepted_audiences: list[str] = Field(validation_alias="ENTRA_ACCEPTED_AUDIENCES", min_length=1)
    identifier_uri: str = Field(validation_alias="ENTRA_IDENTIFIER_URI", min_length=1)
    required_scope: str = Field(
        validation_alias="ENTRA_REQUIRED_SCOPE", pattern=r"^[A-Za-z0-9._-]+$"
    )
    public_base_url: AnyHttpUrl = Field(validation_alias="MCP_PUBLIC_BASE_URL")

    @field_validator("accepted_audiences")
    @classmethod
    def explicit_audiences(cls, values: list[str]) -> list[str]:
        if any(not value.strip() or "*" in value or value != value.strip() for value in values):
            raise ValueError(
                "Accepted audiences must be explicit nonempty values without wildcards"
            )
        return values

    @field_validator("identifier_uri")
    @classmethod
    def resource_identifier(cls, value: str) -> str:
        if (
            not value.startswith(("api://", "https://"))
            or value.endswith("/")
            or any(character.isspace() for character in value)
        ):
            raise ValueError("Use the exact Entra Application ID URI without a trailing slash")
        return value

    @field_validator("public_base_url")
    @classmethod
    def public_https_origin(cls, value: AnyHttpUrl) -> AnyHttpUrl:
        if (
            value.scheme != "https"
            or value.path not in ("", "/")
            or any([value.query, value.fragment, value.username, value.password])
        ):
            raise ValueError(
                "MCP_PUBLIC_BASE_URL must be an HTTPS origin, without path or credentials"
            )
        return value

    @property
    def issuer(self) -> str:
        return f"https://login.microsoftonline.com/{self.tenant_id}/v2.0"


class EntraTokenVerifier(JWTVerifier):
    def __init__(self, settings: AuthSettings, *, public_key: bytes | None = None):
        self.settings = settings
        super().__init__(
            public_key=public_key,
            jwks_uri=None
            if public_key
            else f"https://login.microsoftonline.com/{settings.tenant_id}/discovery/v2.0/keys",
            issuer=settings.issuer,
            audience=settings.accepted_audiences,
            algorithm="RS256",
            required_scopes=[settings.required_scope],
        )

    async def verify_token(self, token: str) -> AccessToken | None:
        verified = await super().verify_token(token)
        if verified is None:
            return None
        claims = verified.claims
        now = time.time()
        exp = claims.get("exp")
        nbf = claims.get("nbf", 0)
        numeric_dates = all(
            isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
            for value in (exp, nbf)
        )
        delegated_scopes = claims.get("scp")
        if (
            not numeric_dates
            or exp <= now
            or nbf > now
            or claims.get("tid") != str(self.settings.tenant_id)
            or claims.get("ver") != "2.0"
            or not isinstance(delegated_scopes, str)
            or self.settings.required_scope not in delegated_scopes.split()
        ):
            logger.warning("Access denied: invalid Entra delegated access-token claims")
            return None
        return verified


def load_auth_settings() -> AuthSettings:
    return AuthSettings()


def build_auth(settings: AuthSettings) -> RemoteAuthProvider:
    return RemoteAuthProvider(
        token_verifier=EntraTokenVerifier(settings),
        authorization_servers=[AnyHttpUrl(settings.issuer)],
        base_url=str(settings.public_base_url).rstrip("/"),
        scopes_supported=[f"{settings.identifier_uri}/{settings.required_scope}"],
        resource_name="Replication Insights (simulated data)",
    )
