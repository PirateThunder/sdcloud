"""Pydantic schemas for Conversation."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ConversationBase(BaseModel):
    """Base conversation schema."""

    title: str | None = Field(default=None, max_length=255)
    model_type: str = Field(default="system_dynamics", max_length=50)


class ConversationCreate(ConversationBase):
    """Schema for creating a conversation."""

    pass


class ConversationUpdate(BaseModel):
    """Schema for updating a conversation."""

    title: str | None = Field(default=None, max_length=255)


class ConversationListItem(ConversationBase):
    """Schema for conversation list response."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    message_count: int = 0


class ConversationDetail(ConversationBase):
    """Schema for detailed conversation with messages."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    messages: list["MessageResponse"] = []


# Forward reference resolution
from app.schemas.message import MessageResponse

ConversationDetail.model_rebuild()
ConversationListItem.model_rebuild()
