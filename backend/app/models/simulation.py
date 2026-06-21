"""Simulation model — stores simulation runs and their results."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, JSON, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Simulation(Base):
    """A simulation run for a generated model."""

    __tablename__ = "simulations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
    )
    model_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("generated_models.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    parameters: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        default=dict,
    )
    time_start: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
    )
    time_end: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=100.0,
    )
    time_step: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.25,
    )
    results: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relationships
    model: Mapped["GeneratedModel"] = relationship(
        "GeneratedModel",
        back_populates="simulations",
        lazy="selectin",
    )
