"""Token verification (req 3.2.1, 4.1.3). Invalid credentials are rejected."""
from fastapi import Header, HTTPException
from pydantic import BaseModel

from .stores import supabase


class User(BaseModel):
    id: str
    email: str | None = None


def current_user(authorization: str | None = Header(default=None)) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    try:
        user = supabase().auth.get_user(token).user
    except Exception:
        raise HTTPException(401, "Invalid credentials")
    if user is None:
        raise HTTPException(401, "Invalid credentials")
    return User(id=user.id, email=user.email)
