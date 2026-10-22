"""
Verifies supabase access token against SUPABASE_JWKS_URL
Trace current user's id
Note missing or invalid tokens
Used as a dependency (Depends(current_user)) rather than ASGI middleware, so /health and /docs stay public,
routes receive a typed User, and tests can replace it with app.dependency_overrides
Every failure is a generic 401; the real reason is logged, never sent to the client
"""

import asyncio
import logging
from functools import lru_cache

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import Settings, get_settings
from app.schemas.auth import User

logger = logging.getLogger(__name__)

# Supabase signs user tokens with asymmetric keys published at the JWKS URL
ALGORITHMS = ["ES256", "RS256"]
# Signed-in users get aud "authenticated"; anon tokens don't, so they are rejected
AUDIENCE = "authenticated"

# auto_error=False: a missing or non-Bearer header returns None, so we answer with our own 401
bearer = HTTPBearer(auto_error=False)


@lru_cache
def jwks_client(url: str) -> jwt.PyJWKClient:
    # One client per URL; it caches the public keys and refetches when it sees an unknown key id
    return jwt.PyJWKClient(url, cache_keys=True)


def unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing access token",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    settings: Settings = Depends(get_settings),
) -> User:
    # Never fail open: without a JWKS URL no token can be verified
    if not settings.supabase_jwks_url:
        logger.error("SUPABASE_JWKS_URL is not set; rejecting authenticated request")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Authentication is not configured")
    if credentials is None:
        raise unauthorized()

    token = credentials.credentials
    try:
        # Fetching keys is blocking HTTP, so keep it off the event loop
        signing_key = await asyncio.to_thread(jwks_client(settings.supabase_jwks_url).get_signing_key_from_jwt, token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=ALGORITHMS,
            audience=AUDIENCE,
            options={"require": ["exp", "sub"]},
        )
    except jwt.PyJWKClientConnectionError as error:
        # Supabase unreachable is our outage, not a bad token
        logger.error("Could not fetch JWKS: %s", error)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Authentication is temporarily unavailable") from error
    except jwt.PyJWTError as error:
        logger.info("Rejected access token: %s", error)
        raise unauthorized() from error

    return User(id=claims["sub"], email=claims.get("email"))
