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
- Postgres 14 (installed natively, not Docker), SQLAlchemy 2.0 ORM, Alembic migrations
  — started on SQLite, swapped in Phase 3 on purpose
- Plain HTML frontend, no JS framework
- Single-user session-cookie auth (Starlette `SessionMiddleware` + stdlib `hashlib.scrypt`
  for password hashing); secrets loaded from a gitignored `.env` via `python-dotenv`
  (see `.env.example`)

## Roadmap (current phase marked)
1. Minimal app: one HTML form, POST endpoint, SQLite write, list view — done 2026-08-28
2. Split API layer (JSON endpoints) from frontend; add Pydantic validation — done 2026-08-28
3. Data layer: SQLAlchemy ORM, swap to Postgres, Alembic migrations — done 2026-08-28
4. Security: env secrets, authn, authz, OWASP basics — done 2026-08-28
5. [CURRENT] Observability: structured logs, OTel traces+metrics, health/readiness, export to Elastic
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
- **Phase 2 (done 2026-08-28)**: added `GET/POST /api/entries` (JSON, Pydantic-validated) and
  switched `index.html` to a fetch-based client (vanilla JS, no framework) — the frontend
  is now a consumer of the API, not a privileged form-POST path. Old `POST /entries`
  form-encoded route removed; `python-multipart` dependency dropped since nothing parses
  multipart/form-data anymore. Added `ge=0` validation on distance/duration (previously
  unenforced by raw SQLite) and rendered the entries table via `textContent` rather than
  `innerHTML` to avoid an XSS hole from unescaped `notes` in client-side rendering.
- **Phase 3, Step A (done 2026-08-28)**: swapped raw `sqlite3` for SQLAlchemy 2.0's typed
  ORM (`Mapped`/`mapped_column`, not the legacy `Column()` style) against a natively
  installed Postgres 14 (not Docker — that's Phase 6). New file `orm_models.py` holds the
  `Entry` mapped class (`models.py` was already taken by the Pydantic schemas). `db.py`
  keeps its exact same three function signatures, so `app.py` needed zero changes — the
  ORM swap is entirely invisible above the data-access layer. `DATABASE_URL` is read from
  an env var with a hardcoded local-dev fallback baked into source
  (`postgresql+psycopg2://simpleapp:simpleapp_dev@localhost/simpleapp`) — intentionally
  *not* real secrets management (no `.env`, no vault); that's Phase 4's job. Confirmed a
  real win from the swap: Postgres's native `DATE` column type rejects a bad date literal
  (`ERROR: invalid input syntax for type date`) that SQLite's untyped `TEXT` column would
  have silently stored — a second line of defense below Pydantic's own validation. Also
  hit and fixed a real bug: passing a bare Python string to `server_default` doesn't emit
  raw SQL, it gets quoted as a literal value — `server_default="''"` actually stored the
  literal 2-character string `''`, not an empty string. Fixed with `sqlalchemy.text("''")`.
  Still-open gap, unchanged from Phase 2: nothing tests a true SQL `NULL` — `notes` is
  non-NULL at both the ORM and now the DB level, but no optional fields exist anywhere yet.
- **Phase 3, Step B (done 2026-08-28)**: added Alembic. Dropped Step A's `create_all()`-made
  table so the initial migration would be a real autogenerated `CREATE TABLE`, not a blind
  `alembic stamp head` against a table that already matched — the migration file was read
  by hand before applying. `alembic/env.py` imports `DATABASE_URL` and `Base` from the
  app's own `db.py`/`orm_models.py` rather than duplicating connection config in
  `alembic.ini` — one source of truth. `db.py`'s `init_db()` and `app.py`'s startup call to
  it are both gone now — schema creation is exclusively Alembic's job going forward
  (`alembic upgrade head`), not something the app does implicitly at boot. Local dev setup
  is now: `alembic upgrade head` once, then run the app as before. Phase 3 is complete.
- **Phase 4, env secrets (done 2026-08-28)**: `DATABASE_URL`'s hardcoded local-dev fallback
  (the known gap flagged in Phase 3) is gone — `db.py` now does `os.environ["DATABASE_URL"]`
  (raises loudly if unset) after `load_dotenv()`. New `.env` (gitignored, real local secrets)
  and `.env.example` (committed template, no real values). New dependency `python-dotenv` —
  reads a local `.env` file into process env vars, standard/well-known, avoids needing to
  `export` vars by hand every terminal session.
- **Phase 4, authn + authz + OWASP basics (done 2026-08-28)**: added server-side session-cookie
  login (Starlette's `SessionMiddleware`; new dependency `itsdangerous`, which it requires
  for signing but doesn't bundle). Passwords hashed with stdlib `hashlib.scrypt` (salted,
  matches common interactive-login KDF parameters) — no new dependency needed for hashing.
  `auth.py` holds `hash_password`/`verify_password`/`require_login`; `scripts/hash_password.py`
  is a one-off setup tool (uses `getpass`, never echoes or stores the password) to generate
  `APP_PASSWORD_HASH` for `.env`. New routes `GET/POST /login`, `POST /logout`; `GET /` and
  both `/api/entries` routes now require a valid session. **Single-user by design** (see
  Purpose above — this is literally one person's training log, not a multi-tenant app), so
  authz reduces to "must be logged in"; a production-grade version serving multiple users
  would add a `users` table + `entries.user_id` FK and filter every query by the current
  user, not just gate on "any valid session". OWASP-basics pass: XSS and SQL injection were
  already mitigated (Phases 2–3); added CSRF mitigation via `SameSite=Lax` + `HttpOnly` on
  the session cookie (confirmed in `Set-Cookie` header), and a small security-headers
  middleware (`X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
  `Referrer-Policy: same-origin`). Explicitly deferred, not forgotten: rate limiting /
  brute-force protection on `/login` (Phase 7), HTTPS/TLS (Phase 6–7, needs a reverse
  proxy), dependency vulnerability scanning. Phase 4 is complete.
