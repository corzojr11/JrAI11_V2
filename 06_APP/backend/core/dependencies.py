from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache
from typing import Any

import jwt
from fastapi import Depends, HTTPException, Request

from config import JWT_SECRET_KEY
from database import get_user_by_username


def get_current_token_payload(request: Request) -> dict[str, Any]:
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=["HS256"])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


def get_current_user(request: Request) -> dict[str, Any]:
    payload = get_current_token_payload(request)
    username = str(payload.get("sub", "")).strip().lower()
    user = get_user_by_username(username)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if not user.get("active", False):
        raise HTTPException(status_code=403, detail="User inactive")
    return user


@lru_cache(maxsize=None)
def _normalized_role_set(roles: tuple[str, ...]) -> set[str]:
    return {role.strip().lower() for role in roles if role.strip()}


def require_roles(*roles: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
    allowed_roles = _normalized_role_set(tuple(roles))

    def dependency(current_user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
        if allowed_roles and str(current_user.get("role", "")).strip().lower() not in allowed_roles:
            raise HTTPException(status_code=403, detail="Forbidden")
        return current_user

    return dependency
