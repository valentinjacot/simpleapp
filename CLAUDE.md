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
- Structured JSON logging via stdlib `logging` + a custom formatter (`logging_config.py`)
  — no logging library dependency
- OpenTelemetry SDK for traces + metrics (`otel_setup.py`); auto-instrumentation for
  FastAPI and SQLAlchemy; console exporters for now (real backend export deferred to
  Phase 6, alongside Elasticsearch/Kibana/Collector as compose services)
- `Dockerfile` (single-stage, non-root `appuser`, `python:3.13-slim`); no compiler
  needed since `psycopg2-binary` ships a prebuilt wheel
- `docker-compose.yml`: app + Postgres 14 + a one-off `migrate` service
  (`alembic upgrade head`, `depends_on: service_completed_successfully`) +
  Elasticsearch + Kibana + Elastic APM Server + a Grafana stack (Tempo/Loki/
  Prometheus/Grafana) + an OTel Collector (`otel-collector-config.yaml`) fanning
  the same traces/metrics/logs out to both backend sets — backend choice is a
  Collector-config concern, no application code involved;
  `opentelemetry-exporter-otlp-proto-http` sends real traces+metrics+logs to the
  Collector when `OTEL_EXPORTER_OTLP_ENDPOINT` is set (compose only — console/
  stdout still used for native dev)
- `k8s/` manifests (app + Postgres only — scoped, not the observability stack)
  tested against a local `kind` cluster

## Roadmap (current phase marked)
1. Minimal app: one HTML form, POST endpoint, SQLite write, list view — done 2026-08-28
2. Split API layer (JSON endpoints) from frontend; add Pydantic validation — done 2026-08-28
3. Data layer: SQLAlchemy ORM, swap to Postgres, Alembic migrations — done 2026-08-28
4. Security: env secrets, authn, authz, OWASP basics — done 2026-08-28
5. Observability: structured logs, OTel traces+metrics, health/readiness — done 2026-09-04
   (export to Elastic deferred to Phase 6, see phase notes)
6. [CURRENT] Packaging & deploy: Dockerfile → compose (app + Postgres + Elasticsearch +
   Kibana + OTel Collector) → k8s manifests → CI pipeline
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
- **Phase 5, Step A (done 2026-09-04)**: structured JSON logging. New file
  `logging_config.py` holds a stdlib `logging.Formatter` subclass (`JSONFormatter`) that
  emits one JSON object per line — no new dependency, deliberately not
  `python-json-logger` or similar, since stdlib `logging`'s `extra={...}` mechanism
  already does everything needed here. `configure_logging()` (called once at startup in
  `app.py`) also rewires uvicorn's own loggers (`uvicorn`, `uvicorn.error`,
  `uvicorn.access`) onto the same handler so the whole process emits one consistent
  format, not a mix of JSON and uvicorn's default colored text. A new `log_requests`
  middleware logs every request (`http_method`, `path`, `status_code`, `duration_ms`);
  `/login` and `/logout` additionally log `login_failed`/`login_succeeded` (with
  `username`, deliberately never `password`) and `logout` events. **Caught during
  testing**: uvicorn's own `uvicorn.access` logger was double-logging every request
  alongside the new richer one — silenced it at `WARNING` level rather than leaving two
  overlapping log lines per request. **Known gap, not addressed this step**: no
  request/trace ID correlating log lines from the same request — arrives naturally with
  Step C (OpenTelemetry), which generates trace/span IDs that can be attached to log
  records. Log level configurable via `LOG_LEVEL` env var (default `INFO`).
- **Phase 5, Step B (done 2026-09-04)**: `GET /healthz` (liveness) and `GET /readyz`
  (readiness) endpoints, both unauthenticated — an orchestrator's probe has no session
  cookie. `/healthz` only confirms the process can respond; it never touches the
  database, so a DB outage doesn't make a healthy process look dead. `/readyz` calls a
  new `db.ping()` (`SELECT 1`) and returns 503 if that fails — this is the one an
  orchestrator would gate load-balancer traffic on. Tested the failure path by pointing
  a second, throwaway uvicorn process at an unreachable port via an env var override,
  without touching the real local Postgres or `.env` (stopping the actual service needs
  `sudo`, unavailable non-interactively in this environment). Confirms the standard
  liveness-vs-readiness distinction: a production orchestrator restarts a container on
  failed liveness but only pulls it from rotation on failed readiness — worth having
  two separate endpoints rather than one, even though right now nothing consumes them
  (that's Phase 6's job, once there's a container/orchestrator to wire them into).
- **Phase 5, Step C (done 2026-09-04)**: OpenTelemetry traces + metrics. New file
  `otel_setup.py`; new dependencies `opentelemetry-sdk`,
  `opentelemetry-instrumentation-fastapi`, `opentelemetry-instrumentation-sqlalchemy`
  (all well-known, official OTel Python packages). `FastAPIInstrumentor` and
  `SQLAlchemyInstrumentor` auto-instrument every route and every DB query — no manual
  span creation in `app.py`/`db.py` — so a single request's trace shows a parent
  request span with a child DB-query span nested inside it, making "how much of this
  request's time was the database" visible without writing any tracing code by hand.
  Metrics (`http.server.duration`, request counts, etc.) come from the same SDK's
  meter provider. Both exporters are **console exporters** for this step deliberately
  — no Collector or Elastic endpoint exists yet (that's Step D); the exporter is
  isolated to two lines in `otel_setup.py` so swapping it for a real OTLP endpoint
  later is a config change, not a redesign. Also closed a gap flagged in Step A: a new
  `TraceContextFilter` (`logging_config.py`) attaches the active span's `trace_id`/
  `span_id` to every JSON log line, so a log line can be correlated back to its trace —
  confirmed by direct comparison that the values match exactly.
  **Bug caught during implementation**: `FastAPI.add_event_handler("shutdown", ...)` —
  the initial approach for flushing telemetry on shutdown — doesn't exist on this
  project's FastAPI version (0.141.1); that whole `on_event`/`add_event_handler` API
  was removed in favor of the `lifespan` context-manager parameter. Fixed by passing
  `lifespan=lifespan` to `FastAPI()`. **Trade-offs noted, not "fixed"** (right choice
  for this app's scale, not for production): `SimpleSpanProcessor` (synchronous
  per-span export) instead of `BatchSpanProcessor`, and a 5s metrics-export interval
  instead of the SDK's 60s default — both purely for fast local-testing feedback; a
  production-grade version would batch spans and use a longer export interval to cut
  overhead under real load.
- **Phase 5 closed, Step D deferred to Phase 6 (decided 2026-09-04)**: originally
  scoped as this phase's Step D ("export to Elastic"), pushed to Phase 6 instead —
  running Elasticsearch (+ Kibana, + an OTel Collector to receive OTLP and forward
  into it) natively, the pattern used for Postgres in Phase 3, is a much heavier
  install (Elasticsearch wants ~2GB+ RAM out of the box, plus a few `sudo` steps) for
  something that becomes nearly free once Docker Compose exists — spinning up
  Elasticsearch/Kibana/Collector as compose services next phase avoids doing the
  native-install work now just to redo it in containers immediately after. Phase 5 is
  otherwise complete: structured JSON logs (Step A), health/readiness endpoints
  (Step B), and OTel traces+metrics with console exporters (Step C) are all working
  and tested — see `tests/smoke_tests.md`. When Phase 6 adds Elasticsearch, the actual
  export wiring should be small: `otel_setup.py`'s exporters are already isolated to
  two lines, swapping `ConsoleSpanExporter`/`ConsoleMetricExporter` for OTLP exporters
  pointed at the Collector.
- **Phase 6, Step A (done 2026-09-07)**: `Dockerfile`. Single-stage build — no
  multi-stage needed since `psycopg2-binary` is a prebuilt wheel, nothing to compile.
  Runs as a non-root `appuser` (cheap, real security win: a container escape doesn't
  hand over root). `requirements.txt` copied and installed before the rest of the
  source, so `docker build` only reinstalls dependencies when they actually change,
  not on every code edit. Verified by running the built image standalone
  (`--add-host=host.docker.internal:host-gateway`, pointed at the existing native
  Postgres) before adding compose complexity. **Real finding, not a bug**: the
  container couldn't reach that native Postgres — the connection attempt hung rather
  than failing fast, because native Postgres only listens on `localhost` by default,
  not the Docker bridge gateway IP. Confirmed the image itself was fine by checking
  routes that don't touch the DB (`/healthz`, `/login`) worked identically to the
  native run. Deliberately not "fixed" here — Step B's compose setup puts the app and
  Postgres on the same Docker network, which sidesteps this whole class of problem
  rather than working around the host-networking gap.
- **Phase 6, Step B (done 2026-09-07)**: `docker-compose.yml` — `db` (Postgres 14,
  `pg_isready` healthcheck, named volume `pgdata` for persistence across restarts),
  `migrate` (same app image, `command: alembic upgrade head`, runs once and exits),
  `app` (waits for `db` healthy *and* `migrate` to exit 0 via
  `condition: service_completed_successfully` — a standard init-container-style
  pattern, migrations as an explicit separate step rather than folded into app
  startup). Confirmed Step A's host-networking gap is resolved by design: `db` is a
  resolvable hostname on the compose network, so `/readyz` and every DB-backed route
  work immediately. Confirmed idempotency (`docker compose down` + `up` again: no
  "Running upgrade" line the second time, already at `head`) and persistence (an
  entry created before `down` was still present after `up`, via the named volume —
  `down` alone doesn't remove volumes, only `down -v` does). `app`'s Docker
  healthcheck uses a Python one-liner (`urllib.request.urlopen` against `/healthz`)
  instead of `curl`, since `python:3.13-slim` doesn't include `curl` and stdlib
  already covers it — no new package just for a healthcheck. Compose's automatic
  `.env` loading supplies `SESSION_SECRET_KEY`/`APP_USERNAME`/`APP_PASSWORD_HASH`
  (same file as native dev, already gitignored); `DATABASE_URL` is set explicitly in
  `docker-compose.yml` itself (pointing at `db`, not `localhost`), not read from
  `.env`, since the native and compose databases are deliberately different
  targets. Compose's own Postgres is **not** published to the host — only `app`'s
  port 8000 is — so it can't collide with the native Postgres on 5432.
- **Phase 6, Step C (done 2026-09-07)**: Elasticsearch + Kibana + an OTel Collector
  join compose, closing out Phase 5's deferred "export to Elastic." New dependency
  `opentelemetry-exporter-otlp-proto-http` (official OTel package; the HTTP/protobuf
  variant, not gRPC, to avoid a `grpcio` native dependency for something this small).
  `otel_setup.py` now checks `OTEL_EXPORTER_OTLP_ENDPOINT`: if set (compose only),
  spans/metrics go via `BatchSpanProcessor`/`OTLPSpanExporter`/`OTLPMetricExporter`
  to the Collector; if unset (native `uvicorn --reload` dev), the Step C console
  exporters are unchanged — so the existing native workflow in `Runbook.md` keeps
  working exactly as before. **Real bug caught and fixed**: the Collector's
  `elasticsearch` exporter silently dropped every histogram metric
  (`http.server.duration` etc.) with `dropping cumulative temporality histogram` —
  it only accepts delta temporality, not the SDK's cumulative default. Fixed with
  `OTLPMetricExporter(preferred_temporality={Histogram: AggregationTemporality.DELTA})`.
  Verified traces and metrics actually land in Elasticsearch by querying its REST API
  directly (`curl :9200/...`), not just trusting the Collector's own logs — found a
  real histogram document with populated `counts`/`values` buckets. **Real, noted
  behavior**: the exporter's `metrics_index` config setting is ignored — metrics land
  under its own default OTel-native data stream name regardless; `traces_index` *is*
  respected. **Deliberately out of scope**: structured JSON logs (`logging_config.py`)
  are not part of this OTLP pipeline — still stdout-only. Shipping them to
  Elasticsearch too needs a separate mechanism (an OTel Python logging bridge, or a
  Collector `filelog` receiver on stdout), left as a known gap rather than expanding
  this step beyond what `otel_setup.py` already owns (traces + metrics). Host
  prerequisite: Elasticsearch requires `vm.max_map_count >= 262144` — the user raised
  it via `sudo sysctl -w vm.max_map_count=262144` in their own terminal (same
  `sudo`/no-TTY pattern as the Phase 3 Postgres install).
- **Phase 6, Step D (done 2026-09-07)**: Kubernetes manifests (`k8s/`), deliberately
  scoped to app + Postgres — not Elasticsearch/Kibana/Collector, already proven via
  compose in Step C; this step is about the deploy pattern itself. Tested against a
  real local `kind` cluster (installed to `~/.local/bin`, no `sudo`), not just
  written — checked the machine could actually handle it first (15GB RAM/20 cores,
  ~6GB available; a single-node `kind` cluster idles around 400MB, lighter than the
  full compose stack). Two Secrets, not one (`postgres-credentials`,
  `simpleapp-secrets`) — least privilege, so the Postgres container never sees
  `APP_PASSWORD_HASH`. `db`'s Deployment uses `strategy: Recreate`, not the default
  `RollingUpdate` — two Postgres pods can't share one `ReadWriteOnce` PVC.
  `imagePullPolicy: Never` + `kind load docker-image` is explicitly a
  local-testing-only mechanism (a real cluster needs a real image registry).
  **The real payoff of this step**: scaling `db` to 0 replicas and back proved the
  liveness/readiness distinction end-to-end, for real — the readiness probe (`/readyz`)
  failed (503), the pod was pulled from the `app` Service's endpoints, and the
  liveness probe (`/healthz`, no DB check) kept passing, so Kubernetes correctly did
  **not** restart the pod (`RESTARTS` stayed `0` throughout). Phase 5 could only
  simulate this with a second throwaway uvicorn process; this is the actual mechanism
  the two endpoints were built for. Also confirmed the PVC persisted data across the
  Postgres pod being deleted and recreated during that test. **Real k8s vs. compose
  gap, worth knowing**: there's no manifest-level equivalent of compose's
  `depends_on: condition: service_completed_successfully` — verification here
  sequenced `kubectl apply`/`kubectl wait` by hand (postgres → migrate Job → app); a
  real deployment would use a Helm hook, an Argo CD sync wave, or CI-pipeline step
  ordering instead.
- **Phase 6, Step C follow-up (done 2026-09-07)**: structured logs to Elasticsearch,
  closing the gap Step C deliberately left open. `logging_config.py` gained an OTel
  logging bridge (`LoggerProvider`/`BatchLogRecordProcessor`/`OTLPLogExporter` — all
  from already-installed packages, no new dependency) that ships every log record to
  the Collector via OTLP whenever `OTEL_EXPORTER_OTLP_ENDPOINT` is set, as a second
  handler alongside the existing stdout JSON one (native dev unaffected). New
  `simpleapp-logs` index; confirmed real trace correlation by comparing a request
  log's `TraceId`/`SpanId` in Elasticsearch against its actual span. **Real bug
  found while investigating Elastic's native APM UI**: `mapping: mode: otel` on the
  Collector's `elasticsearch` exporter — the setting that data needs to be in for
  Kibana's APM app to recognize it — broke metrics entirely
  (`document_parsing_exception`, missing dynamic templates for histogram/gauge
  types), a real incompatibility between `elasticsearchexporter` 0.113.0 and
  Elasticsearch 8.15.3. Reverted immediately rather than shipping it broken; this is
  why the next step reaches for a dedicated APM Server instead of that mapping mode.
- **Phase 6, Step C follow-up 2 (done 2026-09-07)**: Elastic APM Server. New
  `apm-server` compose service (`docker.elastic.co/apm/apm-server:8.15.3`,
  `apm-server.auth.anonymous.enabled=true` for local dev — no secret token/API key
  needed, matching Elasticsearch's own `xpack.security.enabled: false`); the
  Collector's exporter changed from `elasticsearch` to `otlphttp/elastic` pointed at
  `http://apm-server:8200`, letting APM Server own the OTel→Elastic-APM data-model
  mapping itself (its actual job) instead of fighting the generic exporter's broken
  `otel` mapping mode. Confirmed real APM data: Kibana's APM "Services" API
  recognizes `simpleapp` (`agentName: opentelemetry/python`) with genuinely distinct
  per-route latency (`POST /login` ~75ms — the scrypt cost — vs. `GET /healthz`
  ~2ms), and APM Server auto-computes rollup metrics (service summary, per-
  transaction latency/throughput, service-destination) directly from the raw trace
  data — the actual point of running a real APM Server rather than a generic index.
  Confirmed the old `elasticsearch`-exporter path is genuinely retired, not just
  replaced in config, via a before/after document-count check. **Known limit, not a
  bug**: the Service Map view returns `403` — it requires an Elastic Platinum
  license, unavailable on the free/basic tier this stack runs on.
- **Phase 6, backend fan-out exercise (done 2026-09-07)**: proved that *backend
  choice is a Collector concern, not an application concern* — fanned the exact
  same telemetry out to a second, independent set of backends (a local Grafana
  stack: Tempo for traces, Loki for logs, Prometheus for metrics, Grafana as the
  UI) by adding exporters to `otel-collector-config.yaml` only. **Zero application
  code was touched** — not `otel_setup.py`, not `logging_config.py`, not `app.py`.
  Verified by diffing what changed this session: only `docker-compose.yml`,
  `otel-collector-config.yaml`, and new infra config files (`tempo.yaml`,
  `prometheus.yml`, `grafana/provisioning/`). Elastic was never broken — checked
  after every single addition, not just at the end.
  - **`service.version`/`deployment.environment` needed no code change either**:
    verified directly that `Resource.create({"service.name": "simpleapp"})`
    (already in the code) *merges* with the standard `OTEL_RESOURCE_ATTRIBUTES` env
    var rather than overriding it — so both attributes go on purely via that env
    var on the `app` service in `docker-compose.yml`. This is the idiomatic OTel
    pattern specifically for this situation: canonical resource attributes belong
    in deployment config, not application code.
  - **Added one exporter at a time, verified data landed before adding the next**:
    `otlp/tempo` (traces) → confirmed the *same* trace ID existed in both Tempo and
    Elasticsearch simultaneously with identical resource attributes; `otlphttp/loki`
    (logs, via Loki's native OTLP endpoint) → confirmed via LogQL; `prometheus`
    exporter (metrics, pull-based — Prometheus scrapes the collector's `/metrics`,
    not the other way around) → confirmed via Prometheus's own query API; Grafana
    last, with provisioned datasources for all three plus a Tempo→Loki
    "traces to logs" link keyed on `service.name`.
  - **How each backend keys its model off the shared resource attributes — verified,
    not assumed**: Elastic APM maps `deployment.environment` straight to its own
    `service.environment` field (filterable in the Services list) and
    `service.version` to `service.version`, both plain, queryable fields on every
    span. **Tempo** stores the full resource-attribute set on every trace and
    searches by `service.name` (`rootServiceName` in its API) — no attribute
    filtering, no cardinality limit. **Loki** promotes only a small, fixed set of
    resource attributes to *indexed labels* (`service_name`, `service_instance_id`,
    `deployment_environment`) — deliberately not `service_version`, which instead
    rides along as *structured metadata* (queryable, not part of the label index) —
    a real cardinality-control design decision, confirmed by querying
    `/loki/api/v1/labels` directly. **Prometheus** doesn't have a resource-attribute
    concept at all: the exporter fabricates a synthetic `target_info` metric
    (value always `1`) carrying every resource attribute as a label, joined to real
    metrics via shared `job`/`instance` labels — and since Prometheus's own
    scrape-target `job`/`instance` labels take priority, the OTel-derived ones get
    renamed to `exported_job`/`exported_instance` to avoid colliding, confirmed by
    inspecting an actual query result.
