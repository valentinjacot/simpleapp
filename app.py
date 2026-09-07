import logging
import os
import time
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

import db
from auth import require_login, verify_password
from logging_config import configure_logging, shutdown_logging
from models import EntryCreate, EntryOut, LoginRequest
from otel_setup import configure_telemetry, instrument_app, instrument_engine, shutdown_telemetry

load_dotenv()
configure_logging()
logger = logging.getLogger("simpleapp")
configure_telemetry()
instrument_engine(db.engine)

APP_USERNAME = os.environ["APP_USERNAME"]
APP_PASSWORD_HASH = os.environ["APP_PASSWORD_HASH"]
SESSION_SECRET_KEY = os.environ["SESSION_SECRET_KEY"]

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    shutdown_telemetry()
    shutdown_logging()


app = FastAPI(lifespan=lifespan)
instrument_app(app)
# https_only=False: this app is plain HTTP for now (no TLS/reverse proxy yet —
# that's Phase 7). Revisit once HTTPS is in place.
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET_KEY, same_site="lax", https_only=False)
templates = Jinja2Templates(directory="templates")


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    return response


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - start) * 1000, 2)
    logger.info(
        "request",
        extra={
            "http_method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
        },
    )
    return response


@app.get("/healthz")
def healthz():
    """Liveness: is the process up and able to respond at all. No dependency checks."""
    return {"status": "ok"}


@app.get("/readyz")
def readyz():
    """Readiness: is the process able to serve real traffic (i.e. reach the DB)."""
    try:
        db.ping()
    except Exception:
        logger.exception("readyz_failed")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database unreachable")
    return {"status": "ok"}


@app.get("/login")
def login_page(request: Request):
    if request.session.get("authenticated"):
        return RedirectResponse(url="/")
    return templates.TemplateResponse(request, "login.html", {})


@app.post("/login")
def login(credentials: LoginRequest, request: Request):
    valid = credentials.username == APP_USERNAME and verify_password(
        credentials.password, APP_PASSWORD_HASH
    )
    if not valid:
        # Log the attempted username, never the password.
        logger.warning("login_failed", extra={"username": credentials.username})
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")
    request.session["authenticated"] = True
    logger.info("login_succeeded", extra={"username": credentials.username})
    return {"ok": True}


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    logger.info("logout")
    return {"ok": True}


@app.get("/")
def index(request: Request):
    if not request.session.get("authenticated"):
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(request, "index.html", {})


@app.get("/api/entries", response_model=list[EntryOut], dependencies=[Depends(require_login)])
def list_entries():
    rows = db.get_all_entries()
    return [dict(row) for row in rows]


@app.post("/api/entries", response_model=EntryOut, status_code=201, dependencies=[Depends(require_login)])
def create_entry(entry: EntryCreate):
    new_id = db.insert_entry(
        date=entry.date.isoformat(),
        distance_km=entry.distance_km,
        duration_min=entry.duration_min,
        notes=entry.notes,
    )
    return {**entry.model_dump(), "id": new_id}
