import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.core import auth
from app.core.auth import current_user
from app.core.config import Settings, get_settings
from app.schemas.auth import User

USER_ID = "8f14e45f-ceea-4e7a-9f6e-1c2b3d4e5f60"
KEY = ec.generate_private_key(ec.SECP256R1())
OTHER_KEY = ec.generate_private_key(ec.SECP256R1())


def make_token(key=KEY, **overrides) -> str:
    claims = {"sub": USER_ID, "email": "a@example.com", "aud": "authenticated", "exp": int(time.time()) + 300}
    claims.update(overrides)
    claims = {name: value for name, value in claims.items() if value is not None}
    return jwt.encode(claims, key, algorithm="ES256", headers={"kid": "test"})


class FakeJwks:
    # Stands in for PyJWKClient: always hands back the test public key, or raises the given error
    def __init__(self, error: Exception | None = None):
        self.error = error

    def get_signing_key_from_jwt(self, token: str):
        if self.error:
            raise self.error
        return SimpleNamespace(key=KEY.public_key())


def make_app(jwks_url: str | None = "https://example.supabase.co/auth/v1/.well-known/jwks.json") -> FastAPI:
    app = FastAPI()
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, supabase_jwks_url=jwks_url)

    @app.get("/me")
    async def me(user: User = Depends(current_user)) -> User:
        return user

    return app


@pytest.fixture
def jwks(monkeypatch):
    fake = FakeJwks()
    monkeypatch.setattr(auth, "jwks_client", lambda url: fake)
    return fake


async def call(app: FastAPI, headers: dict[str, str] | None = None):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.get("/me", headers=headers or {})


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_valid_token_returns_user(jwks):
    response = await call(make_app(), bearer(make_token()))
    assert response.status_code == 200
    assert response.json() == {"id": USER_ID, "email": "a@example.com"}


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Basic abc"},
        bearer("not-a-jwt"),
        bearer(make_token(exp=int(time.time()) - 10)),
        bearer(make_token(aud="anon")),
        bearer(make_token(aud=None)),
        bearer(make_token(sub=None)),
        bearer(make_token(key=OTHER_KEY)),
    ],
    ids=["missing", "wrong-scheme", "malformed", "expired", "wrong-audience", "no-audience", "no-sub", "bad-signature"],
)
async def test_rejected_tokens_are_401(jwks, headers):
    response = await call(make_app(), headers)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    # Same generic message whatever the reason
    assert response.json() == {"detail": "Invalid or missing access token"}


async def test_unknown_key_id_is_401(jwks):
    jwks.error = jwt.PyJWKClientError("Unable to find a signing key that matches")
    response = await call(make_app(), bearer(make_token()))
    assert response.status_code == 401


async def test_jwks_unreachable_is_503(jwks):
    jwks.error = jwt.PyJWKClientConnectionError("timed out")
    response = await call(make_app(), bearer(make_token()))
    assert response.status_code == 503


async def test_missing_jwks_url_fails_closed(jwks):
    response = await call(make_app(jwks_url=None), bearer(make_token()))
    assert response.status_code == 500
