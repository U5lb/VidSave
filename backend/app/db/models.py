from app.core.config import settings
from app.db.database import Base
from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    phone: Mapped[str | None] = mapped_column()
    last_address: Mapped[str | None] = mapped_column()


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    url: Mapped[str] = mapped_column(String)
    chat_id: Mapped[int | None] = mapped_column(BigInteger)
    message_id: Mapped[int | None] = mapped_column()
    status: Mapped[str] = mapped_column(String, default="draft")
