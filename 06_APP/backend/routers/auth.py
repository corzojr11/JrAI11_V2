from fastapi import APIRouter, Depends, HTTPException, Response, Request
from backend.schemas.auth import LoginRequest
from backend.core.auth import create_access_token, create_refresh_token, verify_refresh_token
from backend.core.dependencies import get_current_user
from config import COOKIE_SECURE, COOKIE_SAMESITE
from database import authenticate_user

router = APIRouter()


def _cookie_kwargs():
    return {
        "httponly": True,
        "secure": COOKIE_SECURE,
        "samesite": COOKIE_SAMESITE,
    }

@router.post("/login")
def login(request: LoginRequest, response: Response):
    user = authenticate_user(request.username, request.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    access_token = create_access_token({"sub": user["username"]})
    refresh_token = create_refresh_token({"sub": user["username"]})
    response.set_cookie(key="access_token", value=access_token, max_age=15 * 60, **_cookie_kwargs())
    response.set_cookie(key="refresh_token", value=refresh_token, max_age=7 * 24 * 60 * 60, **_cookie_kwargs())
    return {"message": "Login successful", "user": user}

@router.post("/refresh")
def refresh(request: Request, response: Response):
    refresh_token = request.cookies.get("refresh_token")
    if not refresh_token:
        raise HTTPException(status_code=401, detail="No refresh token")
    payload = verify_refresh_token(refresh_token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    new_access_token = create_access_token({"sub": payload["sub"]})
    response.set_cookie(key="access_token", value=new_access_token, max_age=15 * 60, **_cookie_kwargs())
    return {"message": "Refreshed"}

@router.post("/logout")
def logout(response: Response):
    response.delete_cookie("access_token")
    response.delete_cookie("refresh_token")
    return {"message": "Logged out"}

@router.get("/me")
def me(current_user=Depends(get_current_user)):
    return {"user": current_user}
