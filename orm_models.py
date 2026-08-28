import datetime

from sqlalchemy import Text, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Entry(Base):
    __tablename__ = "entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[datetime.date]
    distance_km: Mapped[float]
    duration_min: Mapped[float]
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default=text("''"))
