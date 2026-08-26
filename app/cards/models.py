# app/cards/models.py
# Таблицы движка карточек: каталог типов, сгенерированные карточки, контент-банк.
# Время хранится в UTC: DateTime(timezone=True) → TIMESTAMPTZ.
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CardType(Base):
    """Тип карточки (1. card_types): один из 12 форматов + параметры ротации."""

    __tablename__ = "card_types"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    min_group_size: Mapped[int] = mapped_column(
        Integer, default=2, server_default=text("2"), nullable=False
    )
    max_group_size: Mapped[int | None] = mapped_column(Integer)
    cefr_min: Mapped[str] = mapped_column(String(10), default="A2", nullable=False)
    cefr_max: Mapped[str] = mapped_column(String(10), default="C1", nullable=False)
    base_weight: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    # Тип не повторяется чаще, чем раз в cooldown встреч (ТЗ §4.3).
    cooldown: Mapped[int] = mapped_column(Integer, default=3, server_default=text("3"), nullable=False)
    # 1 — безопасно; 2 — только из промодерированного контент-банка.
    safety_tier: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true"), nullable=False
    )


class Card(Base):
    """Сгенерированная карточка занятия (2. cards). Дублирует историю для ротации."""

    __tablename__ = "cards"
    __table_args__ = (
        Index("idx_cards_space_created", "space_id", "created_at"),
        Index("idx_cards_meeting", "meeting_id"),
        Index("idx_cards_type", "card_type_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    space_id: Mapped[str] = mapped_column(String(255), nullable=False)
    meeting_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("meeting_instances.id"), nullable=False
    )
    card_type_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("card_types.id"), nullable=False
    )
    difficulty_level: Mapped[str] = mapped_column(String(10), nullable=False)
    content: Mapped[dict] = mapped_column(JSONB, nullable=False)
    generated_by: Mapped[str] = mapped_column(String(20), nullable=False)  # template|llm|hybrid
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ContentBank(Base):
    """Курируемый контент (3. content_bank): темы/утверждения/новости/сценарии."""

    __tablename__ = "content_bank"
    __table_args__ = (
        Index("idx_content_bank_type", "card_type_id"),
        Index("idx_content_bank_approved", "is_approved"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    card_type_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("card_types.id"), nullable=False
    )
    safety_tier: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    is_approved: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true"), nullable=False
    )
    added_by: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
