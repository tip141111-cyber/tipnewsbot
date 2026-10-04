from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ArticleRow(Base):
    __tablename__ = "articles"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(80))
    source_name: Mapped[str] = mapped_column(String(200))
    topic: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    published_at: Mapped[int] = mapped_column(Integer, index=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_version: Mapped[str | None] = mapped_column(String(160), nullable=True)


class SubscriberRow(Base):
    __tablename__ = "subscribers"
    chat_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    topics: Mapped[str] = mapped_column(Text)


class DigestRow(Base):
    __tablename__ = "digests"
    day: Mapped[str] = mapped_column(String(10), primary_key=True)
    items: Mapped[str] = mapped_column(Text)


class DeliveryRow(Base):
    __tablename__ = "deliveries"
    __table_args__ = (UniqueConstraint("day", "chat_id", name="uq_delivery_day_chat"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    day: Mapped[str] = mapped_column(ForeignKey("digests.day"))
    chat_id: Mapped[int] = mapped_column(ForeignKey("subscribers.chat_id"))
    text: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt: Mapped[int] = mapped_column(Integer, default=0)


class JobRow(Base):
    __tablename__ = "jobs"
    name: Mapped[str] = mapped_column(String(80), primary_key=True)
    last_attempt: Mapped[int] = mapped_column(Integer)
