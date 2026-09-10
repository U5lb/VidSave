from app.core.config import settings
from app.db.database import Base
from sqlalchemy import BigInteger
from sqlalchemy.orm import Mapped, mapped_column


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    phone: Mapped[str | None] = mapped_column()
    last_address: Mapped[str | None] = mapped_column()
