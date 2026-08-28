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
