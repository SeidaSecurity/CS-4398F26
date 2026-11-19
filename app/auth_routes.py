"""Login, logout, and current-user endpoints (R7.1, R4.4, SRS 3.1.1). Logic lives in app/auth.py."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app import auth
from app.configuration import record_audit_event
from app.database import get_session
from app.models import User

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

# One message for every failure, so it never reveals whether a username exists (SRS 3.1.1).
LOGIN_FAILED = "Invalid username or password."


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class CurrentUserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    role: str
    created_at: datetime


@router.post("/login", response_model=CurrentUserRead)
def login(payload: LoginRequest, response: Response, db: Session = Depends(get_session)):
    user = auth.authenticate(db, payload.username, payload.password)
    if user is None:
        record_audit_event(
            db, payload.username, "auth.login", "failed", detail="Invalid credentials"
        )
        db.commit()
        raise HTTPException(status_code=401, detail=LOGIN_FAILED)
    hours = auth.session_hours()
    token = auth.start_session(db, user, hours=hours)
    record_audit_event(db, user.username, "auth.login", "succeeded")
    db.commit()
    response.set_cookie(
        auth.SESSION_COOKIE,
        token,
        max_age=int(hours * 3600),
        path="/",
        httponly=True,
        samesite="lax",
        secure=auth.cookie_secure(),
    )
    return user


@router.post("/logout", status_code=204)
def logout(request: Request, db: Session = Depends(get_session)) -> Response:
    """Idempotent: ends the session if there is one and clears the cookie either way."""
    token = request.cookies.get(auth.SESSION_COOKIE)
    if token:
        user = auth.resolve_session(db, token)
        auth.end_session(db, token)
        if user is not None:
            record_audit_event(db, user.username, "auth.logout", "succeeded")
        db.commit()
    response = Response(status_code=204)
    response.delete_cookie(auth.SESSION_COOKIE, path="/")
    return response


@router.get("/me", response_model=CurrentUserRead)
def me(user: User = Depends(auth.current_user)):
    return user
