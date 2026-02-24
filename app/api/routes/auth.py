"""
Admin authentication routes (JWT-based).
Accepts JSON body { username, password } for SPA; rate limited.
"""
from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from pydantic import BaseModel

from app.services.auth.jwt import (
    verify_admin_credentials,
    create_access_token,
    get_current_user,
)
from app.services.auth.login_rate_limit import (
    check_login_rate_limit,
    get_client_ip,
    reset_login_attempts,
)

router = APIRouter(prefix="/admin/auth", tags=["admin-auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str
    user: dict


class UserInfo(BaseModel):
    username: str


@router.post("/login", response_model=Token)
async def login(request: Request, body: LoginRequest = Body(...)):
    """
    Admin login with JWT token. Expects JSON: { "username": "...", "password": "..." }.
    Rate limited to prevent brute-force.
    """
    client_ip = get_client_ip(request)
    if not check_login_rate_limit(client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Try again later.",
        )

    if not verify_admin_credentials(body.username, body.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    reset_login_attempts(client_ip)
    access_token = create_access_token(data={"sub": body.username})

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {"username": body.username},
    }


@router.post("/logout")
async def logout(current_user: dict = Depends(get_current_user)):
    """Logout (token invalidation handled on client side)."""
    return {"message": "Successfully logged out"}


@router.get("/me", response_model=UserInfo)
async def get_me(current_user: dict = Depends(get_current_user)):
    """Get current user info."""
    return current_user
