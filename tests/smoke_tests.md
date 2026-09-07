# Smoke tests

Manual smoke tests run with curl against the running app. Not an automated suite
(no pytest yet — not on the roadmap till later) — this is a record of what was
checked and what happened, to rerun by eye after changes.

## How to run

```bash
rm -f log.db                          # start from a clean db
.venv/bin/uvicorn app:app --reload &
```

## Phase 1 results (form-encoded `POST /entries`, last run: 2026-08-28)

| # | Case | Expected | Actual |
|---|------|----------|--------|
| 1 | `GET /` on empty db | 200, empty table | 200 |
| 2 | Normal entry | 303 redirect to `/` | 303 |
| 3 | Zero distance | 303, stored as `0.0` | 303 |
| 4 | Zero duration | 303, stored as `0.0` | 303 |
| 5 | Empty notes (`notes=`) | 303, empty cell | 303 |
| 6 | Notes field omitted entirely | 303, empty cell (defaults to `""`) | 303 |
| 7 | Both distance and duration zero | 303, both stored as `0.0` | 303 |
| 8 | Missing required field (`distance_km`) | 422, rejected before DB write | 422 |

Findings: 0 is a legitimate value for `distance_km`/`duration_min` (columns are
`REAL NOT NULL`), empty-string and omitted notes behave identically (`Form("")`
default), and FastAPI's `Form(...)` rejects missing required fields before
`db.insert_entry()` ever runs. No path existed to store a true SQL `NULL`.

This route (`POST /entries`, form-encoded) was **removed in Phase 2** — see below.

## Phase 2 results (JSON `POST /api/entries`, last run: 2026-08-28)

Superset of the Phase 1 cases, replayed against the new JSON API, plus two cases
that only Pydantic validation (not raw SQLite) can catch.

```bash
curl -X POST http://127.0.0.1:8000/api/entries \
  -H "Content-Type: application/json" \
  -d '{"date":"2026-08-01","distance_km":5.2,"duration_min":28,"notes":"easy run"}'
```

| # | Case | Expected | Actual |
|---|------|----------|--------|
| 1 | `GET /api/entries` on empty db | 200, `[]` | 200 |
| 2 | Normal entry | 201 | 201 |
| 3 | Zero distance | 201, stored as `0.0` | 201 |
| 4 | Zero duration | 201, stored as `0.0` | 201 |
| 5 | Empty notes string | 201, `"notes": ""` | 201 |
| 6 | Notes field omitted from JSON body | 201, defaults to `""` (Pydantic `Field` default) | 201 |
| 7 | Both distance and duration zero | 201, both `0.0` | 201 |
| 8 | Missing required field (`distance_km`) | 422 | 422 |
| 9 | Negative distance (`-5`) | 422 — **new**: `ge=0` constraint added in Phase 2 | 422 |
| 10 | Malformed date (`"not-a-date"`) | 422 — **new**: Pydantic `date` type parsing | 422 |

Verified with a clean db (`rm -f log.db`, restart) that all 6 valid POSTs land with
no duplicates: `GET /api/entries` returned exactly 6 rows, ids 1–6, matching the
inserted values.

Findings:
- Cases 9 and 10 didn't exist as failure modes in Phase 1 — raw `sqlite3` had no
  type or range checking, so `-5` or a garbage date string would have been written
  straight to the DB. Pydantic's `EntryCreate` model (`models.py`) catches both
  before `db.insert_entry()` runs.
- Case 6 (Pydantic default) behaves the same as Phase 1's `Form("")` default —
  same guarantee, different mechanism.
- **Known gap, still unresolved**: nothing tests a true SQL `NULL`. `notes` is
  always at least `""`; every other field is required. No optional-field design
  yet — likely arrives with the ORM layer in Phase 3.
- **Browser check (manual, 2026-08-28)**: clicked through `index.html` by hand —
  table loads via fetch on page load, form submit POSTs JSON to `/api/entries`
  and the new row appears without a full page reload. Confirmed working.

## Phase 3, Step A results (SQLAlchemy ORM + Postgres, last run: 2026-08-28)

Same 10-case suite from Phase 2, replayed against the Postgres-backed API (`db.py`
now uses SQLAlchemy instead of raw `sqlite3`; `app.py`/`models.py` untouched).

| # | Case | Expected | Actual |
|---|------|----------|--------|
| 1 | `GET /api/entries` on empty db | 200, `[]` | 200 |
| 2 | Normal entry | 201 | 201 |
| 3 | Zero distance | 201 | 201 |
| 4 | Zero duration | 201 | 201 |
| 5 | Empty notes string | 201 | 201 |
| 6 | Notes field omitted | 201 | 201 |
| 7 | Both distance and duration zero | 201 | 201 |
| 8 | Missing required field (`distance_km`) | 422 | 422 |
| 9 | Negative distance | 422 | 422 |
| 10 | Malformed date | 422 | 422 |

All identical to Phase 2 — the ORM swap changed the storage layer, not the API's
behavior. Verified via `psql`: 6 rows, ids 1–6, no duplicates.

Findings:
- `\d entries` in Postgres: `date` is a real `date` column, `distance_km`/
  `duration_min` are `double precision`, `notes` is `text not null default ''::text`
  — all inferred automatically from the SQLAlchemy 2.0 `Mapped[...]` type hints.
- Concrete SQLite → Postgres upgrade: inserting `'not-a-date'` directly via `psql`
  is **rejected** (`ERROR: invalid input syntax for type date`). SQLite's `TEXT`
  column would have silently stored it — Postgres's real `DATE` type catches it at
  the database layer, a second line of defense below Pydantic's own validation.
- **Bug caught during implementation**: passing a bare Python string to
  `server_default` (e.g. `server_default="''"`) does NOT emit raw SQL — SQLAlchemy
  quotes it as a literal *value*, so the actual stored default became the 2-character
  string `''` instead of an empty string (visible as `''''''::text` in `\d entries`).
  Fixed by wrapping it in `sqlalchemy.text("''")`, which SQLAlchemy treats as raw SQL.
  Confirmed via `CreateTable(Entry.__table__)` showing `DEFAULT ''` before applying.

## Phase 3, Step B results (Alembic migrations, last run: 2026-08-28)

Dropped Step A's `create_all()`-made table, ran
`alembic revision --autogenerate -m "create entries table"`, read the generated file
by hand before applying (`alembic/versions/be5629bbd1e8_create_entries_table.py` —
correctly used `sa.text("''")` for the `notes` default, matching the earlier fix),
then `alembic upgrade head`. `db.py`'s `init_db()` and `app.py`'s `db.init_db()`
startup call were both removed — schema creation is Alembic's job now, not the app's.

Re-ran the same 10-case suite once more against the migration-created table (after
restarting the server with `init_db()` gone):

| # | Case | Expected | Actual |
|---|------|----------|--------|
| 1 | `GET /api/entries` on empty db | 200, `[]` | 200 |
| 2 | Normal entry | 201 | 201 |
| 3 | Zero distance | 201 | 201 |
| 4 | Zero duration | 201 | 201 |
| 5 | Empty notes string | 201 | 201 |
| 6 | Notes field omitted | 201 | 201 |
| 7 | Both distance and duration zero | 201 | 201 |
| 8 | Missing required field (`distance_km`) | 422 | 422 |
| 9 | Negative distance | 422 | 422 |
| 10 | Malformed date | 422 | 422 |

All identical again. Verified via `psql`: `\d entries` matches Step A's schema
exactly, `alembic_version` holds one row (`be5629bbd1e8`), `\dt` shows both tables,
and `select count(*) from entries` returned 6 after the 6 valid POSTs.

Findings:
- Autogenerate correctly detected the whole table as new (`Detected added table
  'entries'`) since it was dropped first — a genuine `CREATE TABLE` migration file
  exists and was reviewed, not a blind `alembic stamp head` against a pre-existing table.
- Expected an import gotcha (the plain `alembic` console-script not putting the repo
  root on `sys.path`, breaking `alembic/env.py`'s `from db import DATABASE_URL`) —
  it did **not** occur here; `.venv/bin/alembic ...` worked directly. Noting this
  because the assumption turned out to be wrong for this setup rather than silently
  dropping it — if it ever does break elsewhere, `python -m alembic ...` is the fix.

## Phase 4 results (session auth + security headers, last run: 2026-08-28)

Tested with curl using a cookie jar (`-c`/`-b`) to carry the session cookie across
requests, since auth is now cookie-based. Credential used for testing: a random
password I generated and hashed myself (`APP_USERNAME=testuser` in `.env`) — I know
this value, so it must be rotated via `scripts/hash_password.py` before real use.

| # | Case | Expected | Actual |
|---|------|----------|--------|
| 1 | `GET /` with no session | 307 redirect to `/login` | 307 |
| 2 | `GET /api/entries` with no session | 401 | 401 |
| 3 | `POST /login` wrong password | 401 | 401 |
| 4 | `POST /login` wrong username | 401 | 401 |
| 5 | `POST /login` correct credentials | 200, sets session cookie | 200 |
| 6 | `GET /` with valid session cookie | 200 | 200 |
| 7 | `GET /api/entries` with valid session cookie | 200, full list | 200 |
| 8 | `POST /api/entries` with valid session cookie | 201 | 201 |
| 9 | `POST /logout` | 200, clears session | 200 |
| 10 | `GET /api/entries` after logout, same cookie | 401 again | 401 |

All as expected — the full login → authenticated access → logout → 401-again
lifecycle works.

Findings:
- `Set-Cookie` header confirmed: `httponly; samesite=lax` — cookie isn't readable
  from JS (mitigates a stolen-cookie XSS scenario) and won't be sent on cross-site
  requests except top-level navigation (mitigates classic CSRF). `https_only` is
  intentionally off for now — this is plain HTTP until Phase 7 adds a reverse proxy.
- Security headers confirmed present on responses: `X-Content-Type-Options: nosniff`,
  `X-Frame-Options: DENY`, `Referrer-Policy: same-origin`.
- Single-user by design (see `CLAUDE.md`): authz reduces to "must be logged in" —
  there's exactly one account, so there's no per-resource permission check to test.
- **Known gaps, not addressed this phase**: no rate limiting / brute-force protection
  on `/login` (Phase 7 territory), no dependency vulnerability scanning, HTTPS still
  absent (Phase 6/7 — reverse proxy + TLS termination).

## Phase 5, Step A results (structured JSON logging, last run: 2026-09-04)

Restarted the server and exercised the same auth flow used in Phase 4's table, this
time inspecting stdout for structured log lines instead of just HTTP status codes.

| # | Case | Expected | Actual |
|---|------|----------|--------|
| 1 | `GET /api/entries` with no session | `request` log, `status_code: 401` | present |
| 2 | `POST /login` wrong password | `login_failed` log with `username`, no password field anywhere | present |
| 3 | `POST /login` correct credentials | `login_succeeded` log with `username` | present |
| 4 | `GET /api/entries` with valid session | `request` log, `status_code: 200`, `duration_ms` present | present |
| 5 | `POST /logout` | `logout` log, then `request` log for the same call | present |
| 6 | Server startup | uvicorn's own startup lines are JSON too (not the default colored text) | present |

Findings:
- Every line on stdout is one JSON object (`logging_config.py`'s `JSONFormatter`) —
  `timestamp`, `level`, `logger`, `message`, plus whatever's passed via `extra={...}`.
  No new dependency: built on stdlib `logging`, not `python-json-logger` or similar.
- Uvicorn's own loggers (`uvicorn`, `uvicorn.error`, `uvicorn.access`) are rewired to
  the same JSON handler so the whole process emits one consistent format.
- **Caught and fixed during testing**: `uvicorn.access` was double-logging every
  request (its own plain-text access line alongside our richer `request` log, which
  already includes `duration_ms`). Silenced `uvicorn.access` at `WARNING` level in
  `logging_config.py` rather than living with the duplicate.
- Confirmed by inspection: `login_failed` logs the attempted `username` but the
  request body's `password` field never appears anywhere in the log output.
- **Known gap, not addressed this step**: no request/trace ID correlating a single
  request across log lines yet — arrives naturally with Step C (OTel), which
  generates trace/span IDs that can be attached to log records.

## Phase 5, Step B results (health/readiness endpoints, last run: 2026-09-04)

`/healthz` and `/readyz` are both unauthenticated (standard for orchestrator probes —
a kubelet doesn't have a session cookie). Tested with the DB reachable, then again
with a second uvicorn instance on port 8001 pointed at an unreachable port
(`DATABASE_URL` overridden via env var for that one process only — the real local
Postgres and `.env` were never touched) to force the `/readyz` failure path without
needing `sudo` to actually stop Postgres.

| # | Case | Expected | Actual |
|---|------|----------|--------|
| 1 | `GET /healthz`, DB reachable | 200, `{"status": "ok"}` | 200 |
| 2 | `GET /readyz`, DB reachable | 200, `{"status": "ok"}` | 200 |
| 3 | `GET /healthz`, DB unreachable | 200 — liveness must not depend on the DB | 200 |
| 4 | `GET /readyz`, DB unreachable | 503, `{"detail": "Database unreachable"}` | 503 |

Findings:
- The DB-down test confirms the intended split: `/healthz` answers "is the process
  alive" and never touches the database; `/readyz` answers "can this instance
  actually serve requests" via `db.ping()` (`SELECT 1`). A real orchestrator restarts
  a pod on failed liveness but only pulls it from the load-balancer pool on failed
  readiness — conflating the two would cause unnecessary restarts during a transient
  DB blip.
- `/readyz`'s failure path logs the full exception traceback (`logger.exception`) —
  confirmed the real `psycopg2.OperationalError` reason ("Connection refused") is
  captured, not just a generic 503.
- Both probes are unauthenticated by design, unlike every other route. No new attack
  surface: they reveal only "up" / "up and DB-reachable", nothing else.

## Phase 5, Step C results (OpenTelemetry traces + metrics, last run: 2026-09-04)

Restarted the server, exercised `POST /login` then `GET /api/entries` then
`GET /readyz`, and inspected stdout for span/metric output (`ConsoleSpanExporter` /
`ConsoleMetricExporter` — both print pretty-printed JSON directly to stdout,
interleaved with the app's own single-line JSON logs).

| # | Case | Expected | Actual |
|---|------|----------|--------|
| 1 | `POST /login` | a `POST /login` span, `SpanKind.SERVER` | present |
| 2 | `GET /api/entries` | a `GET /api/entries` span, plus a child `SELECT simpleapp` span from the SQLAlchemy instrumentation | present |
| 3 | `login_succeeded` log line during an active span | log line carries `trace_id`/`span_id` matching the active span's | present, matched |
| 4 | Metrics export (every 5s) | `http.server.duration`, `http.server.active_requests`, `http.server.request.size`, `http.server.response.size` | all present |
| 5 | `GET /readyz` | traced like any other route (DB check span appears as a child) | present |
| 6 | Clean shutdown (`kill` the process) | no errors; `shutdown_telemetry()` flushes providers via the FastAPI `lifespan` context | clean, no errors in log |

Findings:
- Span nesting confirmed: a request span (`GET /api/entries`) is the parent of the DB
  query span (`SELECT simpleapp`) — a single trace shows exactly how much of the
  request's total time was spent in the database vs. elsewhere, without any manual
  instrumentation in `db.py` or `app.py`. This is auto-instrumentation
  (`FastAPIInstrumentor`, `SQLAlchemyInstrumentor`) doing its job.
- Log/trace correlation confirmed by direct comparison: the `trace_id`/`span_id`
  attached to a log line via `TraceContextFilter` (`logging_config.py`) match the
  `context.trace_id`/`context.span_id` on the corresponding span exactly (same hex
  value, modulo the `0x` prefix the span JSON adds). Closes the gap flagged in Step A.
- **Deliberate scope for this step**: exporting to the console, not a real backend —
  no Collector or Elastic endpoint exists yet (Step D). `otel_setup.py` isolates the
  exporter choice to two lines (`ConsoleSpanExporter()`, `ConsoleMetricExporter()`),
  so Step D is a config swap, not a redesign.
- **Bug caught during implementation**: `FastAPI.add_event_handler("shutdown", ...)`
  (used for the initial shutdown-flush attempt) doesn't exist on this project's
  installed FastAPI version (0.141.1) — that whole `on_event`/`add_event_handler` API
  was removed in favor of the `lifespan` context-manager parameter. Fixed by passing
  `lifespan=lifespan` to `FastAPI()` instead; confirmed via a clean `kill` that
  `shutdown_telemetry()` still runs (no errors, no leftover process).
- **Trade-off noted, not fixed**: `SimpleSpanProcessor` (synchronous, per-span export)
  instead of `BatchSpanProcessor` — right choice for this trivial app's traffic
  volume; a production-grade version would batch to reduce exporter overhead under
  real load. Also noted: metrics export interval was shortened to 5s from the SDK's
  60s default purely for local-testing convenience — a production deployment would
  leave it at (or near) the default.

## Phase 6, Step A results (Dockerfile, last run: 2026-09-07)

Built the image (`docker build -t simpleapp:dev .`) and ran it standalone
(`docker run`, `--add-host=host.docker.internal:host-gateway`, `DATABASE_URL`
pointed at the existing native Postgres) to verify the image itself before
introducing compose. Non-DB routes tested with plain curl; DB-dependent routes
tested with `curl --max-time 5` since the DB call was expected to hang, not fail
fast (see finding below) — a bare `curl` with no timeout would have looked stuck.

| # | Case | Expected | Actual |
|---|------|----------|--------|
| 1 | `docker build` | succeeds, non-root `appuser`, image runs `uvicorn` on `0.0.0.0:8000` | succeeded |
| 2 | Container startup logs | same structured JSON logging as native, uvicorn lines included | present, correctly formatted |
| 3 | `GET /healthz` (no DB) | 200 | 200 |
| 4 | `POST /login` (no DB — hash comparison only) | 200, `{"ok": true}` | 200 |
| 5 | `GET /readyz` (needs DB) | 200 or 503 | **hung** — see finding |
| 6 | `GET /api/entries` (needs DB) | 200 | **hung** — see finding |

Findings:
- **Expected limitation, not a bug**: the container could not reach the native
  Postgres via `host.docker.internal`. Native Postgres listens on `localhost` only
  by default (not on the Docker bridge gateway IP), and the connection attempt hung
  rather than failing fast — consistent with a firewall/network layer silently
  dropping the packets rather than the OS returning "connection refused." This is a
  well-known Docker-to-host networking gotcha, not something to fix in the
  Dockerfile — Step B's compose setup puts the app and Postgres on the same Docker
  network, which sidesteps this class of problem entirely rather than working
  around it.
- Everything not touching the DB (routing, auth hash check, structured JSON
  logging, OTel console output) worked identically to the native run — confirms the
  image itself, not just the app's Python code, behaves correctly.
- `pip install` inside the build prints the usual "Running pip as the 'root' user"
  warning — expected and harmless in a container build (each container is an
  isolated, disposable filesystem; there's no host system package manager to
  conflict with), not a real issue.

## Phase 6, Step B results (docker-compose, last run: 2026-09-07)

`docker compose up -d --build`, then re-ran a subset of the standard auth/entries
suite against `http://127.0.0.1:8000` (now backed by the compose Postgres, not
native). Also tested restart behavior (`docker compose down` + `up` again) to check
migration idempotency and data persistence via the named volume.

| # | Case | Expected | Actual |
|---|------|----------|--------|
| 1 | `db` service startup | reports `(healthy)` via `pg_isready` | healthy |
| 2 | `migrate` service, first run (empty DB) | exits 0, log shows `Running upgrade -> ... create entries table` | exit 0, ran |
| 3 | `app` service | starts only after `migrate` exits successfully; reports `(healthy)` via its own `/healthz` healthcheck | started, healthy |
| 4 | `GET /readyz` | 200 — DB now reachable (Step A's gap fixed by design) | 200 |
| 5 | `POST /login` → `GET /api/entries` → `POST /api/entries` | 200 / 200 (`[]` on fresh DB) / 201 | all as expected |
| 6 | `docker compose down` + `docker compose up -d` (2nd run) | `migrate` exits 0 with **no** "Running upgrade" line (already at head); entry from step 5 still present | confirmed both |

Findings:
- Step A's finding is resolved by design, not patched: app and Postgres share the
  compose network (`db` is a resolvable hostname), so there's no host-networking gap
  to work around.
- The `migrate` service (`command: ["alembic", "upgrade", "head"]`, same image as
  `app`) plus `depends_on: migrate: condition: service_completed_successfully` is a
  clean, standard init-container-style pattern — migrations run as an explicit,
  separate step with their own exit code, never silently baked into app startup.
- Confirmed genuinely idempotent: the second `migrate` run's log has no "Running
  upgrade" line at all (Alembic checked `alembic_version`, found it already at
  `head`, did nothing) — safe to run on every `docker compose up`.
- Confirmed the named volume (`pgdata`) is what makes data survive `docker compose
  down` + `up` — `down` alone removes containers/network but not volumes; `down -v`
  would remove the volume too (not used here, to avoid accidentally wiping real data
  once this is used for real).
- App healthcheck uses a Python one-liner (`urllib.request.urlopen`) hitting
  `/healthz`, not `curl` — the `python:3.13-slim` base image doesn't include `curl`,
  and Python's stdlib already can do the job without adding a package just for a
  healthcheck.
