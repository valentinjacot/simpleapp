# Project: Learning-Log

## Purpose
This is a LEARNING project, not a product. The owner is an observability/performance
engineer filling gaps in production & deployment knowledge. The domain (a personal
training log) is deliberately trivial — the value is in the layers built around it.

Optimize for MY understanding, not for shipping fast or being impressive.

## Working agreement
- Briefly state the approach and any trade-offs, then implement — don't wait for a "go"
  unless the decision is significant (e.g. changes the roadmap, adds a new dependency
  outside Stack, or touches more than one phase's worth of code).
- For small implementation details (file layout, naming, single- vs multi-file split),
  just pick the sensible default and note the choice in one line — don't ask.
- Make small, reviewable changes. One concern at a time.
- Do NOT jump ahead to future phases, even "to be helpful". If auth/Docker/etc.
  would help, mention it in one line and move on — don't implement it.
- When something works, tell me WHY, and how a production-grade version would differ.
- Prefer standard library and well-known packages; explain any new dependency.
- No cleverness for its own sake. Readable > concise.

## Stack
- Python 3.11+, FastAPI, Uvicorn
- SQLite to start (Postgres comes later, on purpose)
- Plain HTML frontend, no JS framework

## Roadmap (current phase marked)
1. Minimal app: one HTML form, POST endpoint, SQLite write, list view — done 2026-08-28
2. [CURRENT] Split API layer (JSON endpoints) from frontend; add Pydantic validation
3. Data layer: SQLAlchemy ORM, swap to Postgres, Alembic migrations
4. Security: env secrets, authn, authz, OWASP basics
5. Observability: structured logs, OTel traces+metrics, health/readiness, export to Elastic
6. Packaging & deploy: Dockerfile → compose → k8s manifests → CI pipeline
7. Hardening: 12-factor, rate limiting, graceful shutdown, reverse proxy, load test

## Conventions
- Commit at the end of each phase with a clear message.
- Keep a short note in this file when a phase completes.

## Phase notes
- **Phase 1 (done 2026-08-28)**: raw `sqlite3`, one server-rendered template, form-encoded
  POST. Smoke-tested with curl: 0 values for distance/duration accepted (columns are
  `REAL NOT NULL`, so 0 is valid, not missing), empty/omitted notes both default to `""`,
  missing required form field correctly 422s. No code path could store a true SQL NULL —
  expected, since nothing was optional yet. See `tests/smoke_tests.md`.
- **Phase 2 (in progress)**: added `GET/POST /api/entries` (JSON, Pydantic-validated) and
  switched `index.html` to a fetch-based client (vanilla JS, no framework) — the frontend
  is now a consumer of the API, not a privileged form-POST path. Old `POST /entries`
  form-encoded route removed; `python-multipart` dependency dropped since nothing parses
  multipart/form-data anymore. Added `ge=0` validation on distance/duration (previously
  unenforced by raw SQLite) and rendered the entries table via `textContent` rather than
  `innerHTML` to avoid an XSS hole from unescaped `notes` in client-side rendering.
