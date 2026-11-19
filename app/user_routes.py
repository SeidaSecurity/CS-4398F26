"""Account management endpoints (R7.4). Admin-only via the central policy (auth.enforce_access).

Logic and rules (password policy, last-admin protection) live in app/auth.py.
"""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import auth
from app.configuration import record_audit_event
from app.database import get_session
from app.models import User
from app.schemas import PartialUpdate

router = APIRouter(prefix="/api/v1/users", tags=["users"])


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    role: str
    disabled: bool
    created_at: datetime


class UserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)
    role: Literal["admin", "viewer"]


class UserUpdate(PartialUpdate):
    role: Literal["admin", "viewer"] | None = None
    disabled: bool | None = None
    password: str | None = Field(default=None, min_length=1, max_length=256)


@router.get("", response_model=list[UserRead])
def list_users(db: Session = Depends(get_session)):
    return list(db.scalars(select(User).order_by(User.username)))


@router.post("", response_model=UserRead, status_code=201)
def create_user(
    payload: UserCreate,
    admin: User = Depends(auth.current_user),
    db: Session = Depends(get_session),
):
    try:
        user = auth.create_user(db, payload.username, payload.password, payload.role)
    except auth.PasswordPolicyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except auth.UserValidationError as exc:
        status = 409 if "already exists" in str(exc) else 422
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    record_audit_event(
        db, admin.username, "user.create", "succeeded",
        detail=f"Created {user.role} '{user.username}'",
    )
    db.commit()
    return user


@router.patch("/{user_id}", response_model=UserRead)
def update_user(
    user_id: int,
    payload: UserUpdate,
    admin: User = Depends(auth.current_user),
    db: Session = Depends(get_session),
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found. Refresh the list.")
    try:
        changes = auth.update_user(
            db, user, role=payload.role, disabled=payload.disabled, password=payload.password
        )
    except auth.LastAdminError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (auth.PasswordPolicyError, auth.UserValidationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if changes:
        record_audit_event(
            db, admin.username, "user.update", "succeeded",
            detail=f"User '{user.username}': {', '.join(changes)}",
        )
    db.commit()
    return user
