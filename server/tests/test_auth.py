import time
from uuid import UUID

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import ValidationError

TENANT = "6e2c494d-9870-4196-8e41-ded386cba051"
API = "56f4b570-60c7-42b5-96fe-59b4d4d6460e"


@pytest.fixture
def signing_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def settings(**changes):
    from replication_insights.auth import AuthSettings

    values = dict(
        tenant_id=UUID(TENANT),
        api_client_id=UUID(API),
        accepted_audiences=[API, f"api://{API}"],
        identifier_uri=f"api://{API}",
        required_scope="Replication.Read",
        public_base_url="https://replication-demo.example.com",
    )
    return AuthSettings(_env_file=None, **(values | changes))


def verifier(signing_key):
    from replication_insights.auth import EntraTokenVerifier

    pem = signing_key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return EntraTokenVerifier(settings(), public_key=pem)


def token(signing_key, **changes):
    claims = (
        dict(
            iss=f"https://login.microsoftonline.com/{TENANT}/v2.0",
            aud=API,
            tid=TENANT,
            ver="2.0",
            exp=int(time.time()) + 3600,
            nbf=int(time.time()) - 10,
            scp="Replication.Read",
            azp="development-client",
            sub="demo-user",
        )
        | changes
    )
    return jwt.encode(
        {key: value for key, value in claims.items() if value is not None},
        signing_key,
        algorithm="RS256",
    )


async def test_valid_delegated_api_access_token_is_accepted(signing_key):
    result = await verifier(signing_key).verify_token(token(signing_key))
    assert result is not None
    assert result.scopes == ["Replication.Read"]


@pytest.mark.parametrize(
    "changes",
    [
        {"aud": "https://graph.microsoft.com"},
        {"aud": "unrelated-api"},
        {"iss": "https://login.microsoftonline.com/wrong-tenant/v2.0"},
        {"tid": "wrong-tenant"},
        {"exp": int(time.time()) - 60},
        {"exp": None},
        {"scp": None, "roles": ["Replication.Read"]},
        {"scp": "Other.Read"},
        {"nbf": int(time.time()) + 3600},
        {"ver": "1.0"},
    ],
)
async def test_invalid_claims_cannot_authorize_mcp(signing_key, changes):
    assert await verifier(signing_key).verify_token(token(signing_key, **changes)) is None


async def test_bad_signature_and_malformed_token_fail_without_leaking_tokens(signing_key, caplog):
    wrong_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    encoded = token(wrong_key)
    check = verifier(signing_key)
    assert await check.verify_token(encoded) is None
    assert await check.verify_token("not-a-token") is None
    assert encoded not in caplog.text


def test_auth_configuration_is_required_and_bounded(monkeypatch):
    from replication_insights.auth import AuthSettings

    for name in (
        "ENTRA_TENANT_ID",
        "ENTRA_API_CLIENT_ID",
        "ENTRA_ACCEPTED_AUDIENCES",
        "ENTRA_IDENTIFIER_URI",
        "ENTRA_REQUIRED_SCOPE",
        "MCP_PUBLIC_BASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ValidationError):
        AuthSettings(_env_file=None)
    for changes in [
        {"tenant_id": "common"},
        {"accepted_audiences": []},
        {"accepted_audiences": ["*"]},
        {"public_base_url": "http://demo.example.com"},
        {"public_base_url": "https://demo.example.com/path"},
        {"required_scope": ""},
    ]:
        with pytest.raises(ValidationError):
            settings(**changes)


def test_metadata_advertises_full_scope_and_intended_authority():
    from replication_insights.auth import build_auth

    config = settings()
    auth = build_auth(config)
    assert [str(value) for value in auth.authorization_servers] == [
        f"https://login.microsoftonline.com/{TENANT}/v2.0"
    ]
    assert auth._scopes_supported == [f"api://{API}/Replication.Read"]
