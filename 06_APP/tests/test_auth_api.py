import os
import sys

import pytest
from fastapi import HTTPException
from starlette.requests import Request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _reload_auth_dependencies():
    for module_name in [
        "backend.core.dependencies",
        "database",
    ]:
        sys.modules.pop(module_name, None)

    from backend.core.dependencies import get_current_user, require_roles

    return get_current_user, require_roles


def _request_with_cookie(cookie_value: str) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(b"cookie", cookie_value.encode("utf-8"))],
        "query_string": b"",
    }

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(scope, receive)


def test_get_current_user_uses_cookie_and_db(temp_db, clean_user):
    from backend.core.auth import create_access_token
    from database import create_user

    create_user(
        username=clean_user,
        display_name="Admin Test",
        password="AdminPass123!",
        email=f"{clean_user}@test.com",
        role="admin",
    )

    get_current_user, _ = _reload_auth_dependencies()
    request = _request_with_cookie(f"access_token={create_access_token({'sub': clean_user})}")

    user = get_current_user(request)

    assert user["username"] == clean_user
    assert user["role"] == "admin"
    assert user["active"] is True


def test_require_roles_blocks_user_role(temp_db, clean_user):
    from database import create_user

    create_user(
        username=clean_user,
        display_name="User Test",
        password="UserPass123!",
        email=f"{clean_user}@test.com",
        role="user",
    )

    _, require_roles = _reload_auth_dependencies()
    guard = require_roles("admin")

    with pytest.raises(HTTPException) as exc:
        guard(current_user={"role": "user"})

    assert exc.value.status_code == 403


def test_require_roles_allows_admin_role(temp_db, clean_user):
    from database import create_user

    create_user(
        username=clean_user,
        display_name="Admin Test",
        password="AdminPass123!",
        email=f"{clean_user}@test.com",
        role="admin",
    )

    _, require_roles = _reload_auth_dependencies()
    guard = require_roles("admin")

    current_user = guard(current_user={"role": "admin", "username": clean_user})

    assert current_user["username"] == clean_user
