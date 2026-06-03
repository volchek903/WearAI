from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class UserAgentSettings(Base):
    __tablename__ = "user_agent_settings"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_user_agent_settings_user_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    web_search_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    documents_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    memory_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    deep_analysis_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    quick_mode_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    document_session_key: Mapped[str] = mapped_column(String(64), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    user = relationship("User", back_populates="agent_settings")
