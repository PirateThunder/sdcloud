"""Pydantic schemas for Message."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class MessageBase(BaseModel):
    """Base message schema."""

    content: str = Field(..., min_length=1)
    role: str = Field(default="user", pattern="^(user|assistant|system)$")


class MessageCreate(MessageBase):
    """Schema for sending a new message."""

    pass


class MessageResponse(MessageBase):
    """Schema for message response."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    conversation_id: uuid.UUID
    model_metadata: dict | None = None
    tokens_used: int | None = None
    created_at: datetime


class MessageHistoryResponse(BaseModel):
    """Schema for message history listing."""

    messages: list[MessageResponse]
    total: int
