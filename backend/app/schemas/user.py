"""Pydantic schemas for User."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserBase(BaseModel):
    """Base user schema."""

    email: EmailStr
    username: str = Field(..., min_length=3, max_length=100)


class UserCreate(UserBase):
    """Schema for user registration."""

    password: str = Field(..., min_length=6, max_length=128)


class UserLogin(BaseModel):
    """Schema for user login."""

    username: str
    password: str


class UserUpdate(BaseModel):
    """Schema for user profile update."""

    email: EmailStr | None = None
    username: str | None = Field(default=None, min_length=3, max_length=100)


class UserResponse(UserBase):
    """Schema for user response (public data)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    is_active: bool
    created_at: datetime
    updated_at: datetime


class TokenPair(BaseModel):
    """Schema for JWT token pair response."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TokenPayload(BaseModel):
    """Schema for JWT token payload."""

    sub: str | None = None
    type: str | None = None
    exp: datetime | None = None
