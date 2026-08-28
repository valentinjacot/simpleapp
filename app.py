from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates

import db
from models import EntryCreate, EntryOut

app = FastAPI()
templates = Jinja2Templates(directory="templates")


@app.get("/")
def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {})


@app.get("/api/entries", response_model=list[EntryOut])
def list_entries():
    rows = db.get_all_entries()
    return [dict(row) for row in rows]


@app.post("/api/entries", response_model=EntryOut, status_code=201)
def create_entry(entry: EntryCreate):
    new_id = db.insert_entry(
        date=entry.date.isoformat(),
        distance_km=entry.distance_km,
        duration_min=entry.duration_min,
        notes=entry.notes,
    )
    return {**entry.model_dump(), "id": new_id}
