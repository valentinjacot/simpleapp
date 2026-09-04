import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from orm_models import Entry

load_dotenv()

DATABASE_URL = os.environ["DATABASE_URL"]

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def ping() -> None:
    """Raises if the database is unreachable. Used by the /readyz probe."""
    with SessionLocal() as session:
        session.execute(text("SELECT 1"))


def insert_entry(date, distance_km, duration_min, notes) -> int:
    with SessionLocal() as session:
        entry = Entry(date=date, distance_km=distance_km, duration_min=duration_min, notes=notes)
        session.add(entry)
        session.commit()
        return entry.id


def get_all_entries():
    with SessionLocal() as session:
        rows = session.scalars(
            select(Entry).order_by(Entry.date.desc(), Entry.id.desc())
        ).all()
        return [
            {
                "id": r.id,
                "date": r.date,
                "distance_km": r.distance_km,
                "duration_min": r.duration_min,
                "notes": r.notes,
            }
            for r in rows
        ]
