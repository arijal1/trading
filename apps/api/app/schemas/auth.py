from __future__ import annotations

import uuid

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_minutes: int


class RegisterRequest(BaseModel):
    email: EmailStr
    # 12 rather than 8: this credential ultimately guards a kill switch and
    # (once live trading is enabled) real money.
    password: str = Field(min_length=12)
    role: str = "user"


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    role: str
    is_active: bool
