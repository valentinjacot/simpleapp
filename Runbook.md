# Runbook — Learning-Log

Operational guide: how to start the app, exercise every endpoint from the terminal,
read its logs/traces/metrics, and a plain-English summary of why the app is built the
way it is. For the detailed, phase-by-phase history of *how* each decision was made
and tested, see `CLAUDE.md`'s Phase notes and `tests/smoke_tests.md`.

All commands below assume you're in the project root (`/home/jacotdev/claude/simpleapp`)
with the virtualenv already created at `.venv/`.

---

## 1. One-time setup

```bash
.venv/bin/pip install -r requirements.txt

# Postgres 14 must already be running natively with the simpleapp role/db created.
# See CLAUDE.md's Phase 3 notes if that's not done yet. (This is the native dev setup —
# see §9 for the Docker Compose alternative, which brings its own separate Postgres.)

cp .env.example .env
# Fill in .env:
#   DATABASE_URL        — postgresql+psycopg2://simpleapp:simpleapp_dev@localhost/simpleapp
#   SESSION_SECRET_KEY  — python3 -c "import secrets; print(secrets.token_urlsafe(32))"
#   APP_USERNAME         — pick anything, e.g. your name
#   APP_PASSWORD_HASH    — .venv/bin/python scripts/hash_password.py (prompts via getpass,
#                          never echoes or stores the plaintext password anywhere)

.venv/bin/alembic upgrade head   # creates the entries table; only needed once, or after
                                  # a new migration is added
```

## 2. Starting the app

```bash
.venv/bin/uvicorn app:app --reload
```

A clean startup looks like this (every line is one JSON object, see §5):

```json
{"timestamp": "...", "level": "INFO", "logger": "uvicorn.error", "message": "Started server process [PID]"}
{"timestamp": "...", "level": "INFO", "logger": "uvicorn.error", "message": "Application startup complete."}
{"timestamp": "...", "level": "INFO", "logger": "uvicorn.error", "message": "Uvicorn running on http://127.0.0.1:8000 ..."}
```

To stop it: `Ctrl-C` in that terminal, or from elsewhere:
`pkill -f "uvicorn app:app"`.

**If the port's already taken** (`Address already in use`), an old instance is still
running — find and kill it first: `pgrep -fa "uvicorn app:app"` then `kill <pid>`.

## 3. First checks: is it alive?

Two separate probes, on purpose (see §12 for why, and §11 to see it matter for real
under Kubernetes):

```bash
curl -i http://127.0.0.1:8000/healthz   # liveness — "is the process up at all"
curl -i http://127.0.0.1:8000/readyz    # readiness — "can it actually reach the DB"
```

Both unauthenticated, both should return `200 {"status": "ok"}` when everything's
healthy. `/readyz` returns `503 {"detail": "Database unreachable"}` if Postgres is
down — try it while Postgres is stopped to see the difference.

## 4. Using the app from the terminal

Everything except `/healthz`, `/readyz`, `/login`, and static pages requires a valid
session cookie. Use a curl cookie jar to carry it across requests:

```bash
COOKIES=$(mktemp)

# Log in
curl -s -c "$COOKIES" -X POST http://127.0.0.1:8000/login \
  -H "Content-Type: application/json" \
  -d '{"username":"<APP_USERNAME>","password":"<your password>"}'
# -> {"ok": true}   (401 if wrong)

# List entries
curl -s -b "$COOKIES" http://127.0.0.1:8000/api/entries | jq

# Add an entry
curl -s -b "$COOKIES" -X POST http://127.0.0.1:8000/api/entries \
  -H "Content-Type: application/json" \
  -d '{"date":"2026-09-04","distance_km":5.2,"duration_min":28,"notes":"easy run"}'
# -> 201, the created entry with its new id

# Log out (-c as well as -b: the response clears the cookie, and the jar must be
# rewritten with that cleared value, or the old authenticated cookie lingers)
curl -s -b "$COOKIES" -c "$COOKIES" -X POST http://127.0.0.1:8000/logout
# -> {"ok": true}; the same jar now gets 401 on /api/entries

rm -f "$COOKIES"
```

Or just use a browser: visit `http://127.0.0.1:8000/` — it redirects to `/login` if
you're not authenticated, and the page itself is a plain HTML form talking to the same
JSON API via `fetch`.

## 5. Reading the structured logs

Every log line the process writes — the app's own and uvicorn's — is a single JSON
object on stdout (`logging_config.py`). Nothing is written to a file by default; it's
all just process stdout, which you'd normally redirect or pipe to a log collector.

```bash
# Pretty-print as it streams
.venv/bin/uvicorn app:app 2>&1 | jq .

# Or redirect to a file and filter after the fact
.venv/bin/uvicorn app:app > app.log 2>&1 &
tail -f app.log | jq .

# Only errors/warnings
jq 'select(.level == "WARNING" or .level == "ERROR")' app.log

# Only request logs, compact view
jq -c 'select(.message == "request") | {path, status_code, duration_ms}' app.log

# Failed login attempts (never shows the password — see auth.py)
jq 'select(.message == "login_failed")' app.log
```

`LOG_LEVEL` env var controls verbosity (default `INFO`):
`LOG_LEVEL=DEBUG .venv/bin/uvicorn app:app`.

Every request produces one `"message": "request"` line with `http_method`, `path`,
`status_code`, `duration_ms`. Login/logout produce their own `login_succeeded` /
`login_failed` / `logout` lines with `username` (never `password`).

## 6. Reading traces and metrics from the terminal

OpenTelemetry is wired up (`otel_setup.py`) but currently exports to the **console**,
not a real backend (Elastic export is Phase 6) — so traces/metrics show up as
pretty-printed multi-line JSON blocks on the same stdout, interleaved with the
single-line logs from §5. This makes them easy to eyeball locally but not yet
searchable the way a real backend would let you.

```bash
# Find a specific request's trace (span names match "<METHOD> <path>")
grep -A 40 '"name": "GET /api/entries"' app.log

# See the DB query span nested under it — SQLAlchemy auto-instrumentation
grep -A 15 '"name": "SELECT simpleapp"' app.log

# Correlate a log line back to its trace: every log line carries trace_id/span_id
# when it was logged during an active request. Grab one, then search for it in the
# span output (strip any 0x prefix — spans print it, logs don't):
jq -r 'select(.message == "login_succeeded") | .trace_id' app.log | tail -1
grep -B5 -A30 "<paste the trace_id here>" app.log

# Metrics are exported every 5s as a batch (shortened from the SDK's 60s default,
# purely for fast local feedback — see CLAUDE.md's Step C note)
grep -A5 '"name": "http.server.duration"' app.log
```

**Read this literally, not as searchable telemetry**: there's no query language, no
retention policy, no dashboard — it's `grep`/`jq` over a live stream. That's the
deliberate, temporary scope of Step C; Phase 6 replaces the console exporters with
real OTLP export to an OTel Collector → Elasticsearch, at which point you'd use
Kibana/APM instead of `grep`.

## 7. Full smoke-test walkthrough

A condensed version of the full test suite kept in `tests/smoke_tests.md` (which has
the authoritative, dated results table per phase). Re-run this after any change to
confirm nothing regressed:

```bash
COOKIES=$(mktemp)

curl -s -o /dev/null -w "no session -> %{http_code}\n" http://127.0.0.1:8000/api/entries            # expect 401
curl -s -o /dev/null -w "healthz -> %{http_code}\n" http://127.0.0.1:8000/healthz                    # expect 200
curl -s -o /dev/null -w "readyz -> %{http_code}\n" http://127.0.0.1:8000/readyz                      # expect 200

curl -s -c "$COOKIES" -o /dev/null -w "wrong password -> %{http_code}\n" -X POST http://127.0.0.1:8000/login \
  -H "Content-Type: application/json" -d '{"username":"x","password":"wrong"}'                       # expect 401

curl -s -c "$COOKIES" -o /dev/null -w "login -> %{http_code}\n" -X POST http://127.0.0.1:8000/login \
  -H "Content-Type: application/json" -d '{"username":"<APP_USERNAME>","password":"<password>"}'     # expect 200

curl -s -b "$COOKIES" -o /dev/null -w "list entries -> %{http_code}\n" http://127.0.0.1:8000/api/entries  # expect 200

curl -s -b "$COOKIES" -o /dev/null -w "negative distance -> %{http_code}\n" -X POST http://127.0.0.1:8000/api/entries \
  -H "Content-Type: application/json" -d '{"date":"2026-09-04","distance_km":-5,"duration_min":10,"notes":""}'  # expect 422

curl -s -b "$COOKIES" -o /dev/null -w "bad date -> %{http_code}\n" -X POST http://127.0.0.1:8000/api/entries \
  -H "Content-Type: application/json" -d '{"date":"not-a-date","distance_km":5,"duration_min":10,"notes":""}'   # expect 422

curl -s -b "$COOKIES" -c "$COOKIES" -o /dev/null -w "logout -> %{http_code}\n" -X POST http://127.0.0.1:8000/logout  # expect 200
curl -s -b "$COOKIES" -o /dev/null -w "after logout -> %{http_code}\n" http://127.0.0.1:8000/api/entries  # expect 401

rm -f "$COOKIES"
```

## 8. Troubleshooting

- **`Address already in use`**: a previous uvicorn instance is still running.
  `pgrep -fa "uvicorn app:app"` to find it, `kill <pid>`.
- **`KeyError` on `DATABASE_URL`/`APP_USERNAME`/etc. at startup**: `.env` is missing or
  incomplete — these are read via `os.environ[...]` (raises loudly), not `.get()` with
  a fallback, deliberately (Phase 4 — no silent fallback to a guessable default).
- **`/readyz` returns 503**: Postgres isn't reachable. Check it's running
  (`pg_lsclusters`, or `systemctl status postgresql` if you have sudo in that
  terminal) and that `DATABASE_URL` in `.env` matches the real role/db/password.
- **Managing the Postgres service itself** (start/stop/restart) needs `sudo`, which
  doesn't work non-interactively in some environments (e.g. an AI coding assistant's
  sandboxed terminal — no TTY for the password prompt) — run those specific commands
  in your own regular terminal.
- **Alembic can't find `DATABASE_URL`**: run it as `.venv/bin/alembic ...` from the
  project root, not from another directory — `alembic/env.py` imports the app's own
  `db.py`, which needs the repo root on `sys.path`.

---

## 9. Running via Docker Compose (alternative to §1–§2)

`docker-compose.yml` runs the app, Postgres, Elasticsearch, Kibana, an Elastic APM
Server, and an OTel Collector as containers on their own network — no native
Postgres, no `.venv`, no `alembic upgrade head` by hand, and (unlike native dev)
traces/metrics/logs go to a real backend instead of the console. This is a
**separate, empty database** from the native one in §1 (see `CLAUDE.md`'s Phase 6
Step B note) — entries created here won't show up in the native setup, or vice versa.

**One-time host prerequisite** (Elasticsearch requires this; it isn't `sudo`-able
from inside a container):

```bash
sudo sysctl -w vm.max_map_count=262144   # only lasts until reboot; add the same line
                                          # to /etc/sysctl.conf to make it permanent
```

```bash
docker compose up -d --build
```

This builds the app image, starts Postgres and Elasticsearch in parallel, waits for
both to report healthy, brings up Kibana and APM Server (which waits on
Elasticsearch), runs `alembic upgrade head` in a one-off `migrate` container and
starts the OTel Collector (which waits on APM Server), then starts the app — only
once `migrate` exits successfully. Check it worked:

```bash
docker compose ps                    # db, elasticsearch, app should show "(healthy)"
docker compose logs migrate          # "Running upgrade -> ... create entries table"
                                      # on the very first run, nothing on later runs
curl http://127.0.0.1:9200/_cluster/health?pretty   # "status": "green" or "yellow"
curl http://127.0.0.1:5601/api/status               # Kibana; 200 once ready (can take
                                                      # a bit longer than the others)
docker compose logs apm-server | grep "no longer blocking ingestion"   # confirms it
                                                      # connected to ES + Kibana OK
```

Everything in §3, §4, and §7 above works exactly the same against
`http://127.0.0.1:8000` — the app doesn't know or care whether it's containerized.
§5's log commands change slightly, since output goes to `docker compose logs`
instead of a redirected file:

```bash
# --no-log-prefix: compose normally prefixes each line with "app-1  | ", which
# breaks jq's JSON parsing — strip it to get back to plain JSON lines.
docker compose logs --no-log-prefix -f app | jq .
docker compose logs --no-log-prefix app | jq -c 'select(.message == "request")'
```

**§5 and §6 both work completely differently here** — the app no longer prints
spans/metrics to its own stdout at all (`OTEL_EXPORTER_OTLP_ENDPOINT` switches both
`logging_config.py` and `otel_setup.py` to real OTLP export, through the Collector,
through APM Server — stdout JSON logging is still there too, as a second parallel
output; only spans/metrics skip the console entirely).

**The main way to look at this is Kibana's APM app**, not raw Elasticsearch queries
— that's the entire point of routing through a real APM Server instead of a generic
index (see `CLAUDE.md`'s Step C follow-up note). Open **http://127.0.0.1:5601**,
then ☰ menu → **Observability → APM → Services**. You should see `simpleapp` listed
(agent: `opentelemetry/python`) with real latency/throughput/error-rate numbers.
Click into it for per-route latency (`Transactions` tab) and individual trace
waterfalls. **Service Map is not available** on this free/basic license — that tab
will 403; everything else works.

```bash
# Same data, from the terminal — useful for scripting/verification, not routine use
curl -s "http://127.0.0.1:5601/internal/apm/services?start=2026-09-01T00:00:00.000Z&end=2026-09-08T00:00:00.000Z&environment=ENVIRONMENT_ALL&kuery=&probability=1&documentType=serviceTransactionMetric&rollupInterval=1m&useDurationSummary=true" \
  -H "kbn-xsrf: true"

# Raw APM data streams, if you want to see what's actually stored
curl -s "http://127.0.0.1:9200/_cat/indices?v" | grep apm
curl -s "http://127.0.0.1:9200/.ds-traces-apm-default-*/_search?size=3&pretty"
```

Logs are routed through APM Server too now (all three OTLP pipelines go through
`otlphttp/elastic`), landing in `logs-apm.app.simpleapp-*` — the old
`simpleapp-logs` index is frozen leftover data from before this change, not live:

```bash
curl -s "http://127.0.0.1:9200/.ds-logs-apm.app.simpleapp-default-*/_search?size=5&pretty"
curl -s "http://127.0.0.1:9200/.ds-logs-apm.app.simpleapp-default-*/_search?pretty" -H "Content-Type: application/json" -d '
{"query": {"match": {"message": "login_succeeded"}}}'   # APM Server maps to ECS-style
                                                          # field names, not the raw OTel
                                                          # "Body"/"Attributes" shape
```

To watch the Collector's or APM Server's own view of what's flowing through
(useful when debugging the pipeline itself, not app behavior):

```bash
docker compose logs -f otel-collector
docker compose logs -f apm-server
```

Stopping:

```bash
docker compose down       # stops and removes containers/network; DATA IS KEPT
                           # (the pgdata and esdata volumes survive)
docker compose down -v    # also deletes both volumes — genuinely fresh next time
```

---

## 10. A guided tour: learning what Elastic Observability actually shows you

This section is for understanding the *concepts*, not just running commands — a
walkthrough of what each pillar (traces, metrics, logs) actually is, why a real APM
backend changes what you can see, and — just as important — what's still missing
from a genuinely production-grade setup. Do this with the compose stack up (§9).

### Step 1 — generate some real variety

One request tells you nothing interesting. Generate a mix, so there's something to
actually look at:

```bash
COOKIES=$(mktemp)
curl -s -c "$COOKIES" -X POST http://127.0.0.1:8000/login \
  -H "Content-Type: application/json" -d '{"username":"testuser","password":"password1234"}' -o /dev/null
curl -s -b "$COOKIES" http://127.0.0.1:8000/api/entries -o /dev/null
curl -s -b "$COOKIES" -X POST http://127.0.0.1:8000/api/entries \
  -H "Content-Type: application/json" -d '{"date":"2026-09-07","distance_km":5,"duration_min":25,"notes":"tour"}' -o /dev/null
curl -s -b "$COOKIES" -X POST http://127.0.0.1:8000/api/entries \
  -H "Content-Type: application/json" -d '{"date":"2026-09-07","distance_km":-5,"duration_min":25,"notes":"bad"}' -o /dev/null   # 422, on purpose
rm -f "$COOKIES"
```

### Step 2 — traces: the raw event data

Open **http://127.0.0.1:5601** → ☰ → Observability → APM → Services → `simpleapp` →
Transactions tab. Click into `GET /api/entries`. What you're looking at: **one span
per unit of work**, nested — a parent span for the whole HTTP request, a child span
for the SQL query inside it. This is what "auto-instrumentation" bought you for
free: nobody wrote `start_span()`/`end_span()` anywhere in `app.py` or `db.py` —
`FastAPIInstrumentor` and `SQLAlchemyInstrumentor` (`otel_setup.py`) generate this
automatically. A trace is the *ground truth* — everything else on this page is
computed from traces like this one.

### Step 3 — metrics: computed, not measured separately

Look at the latency/throughput numbers on the Services list, or the per-transaction
stats. **These are not a second, independently-collected data source** — APM
Server computes them by aggregating the raw trace data from Step 2 (look at the
`.ds-metrics-apm.service_transaction.1m-*` data stream directly if you want to see
the rollup documents themselves). This is the actual value of a real APM backend
over a generic index: it does this aggregation work for you, continuously, so
"what's my p99 latency for this route" isn't a query you have to write by hand.

### Step 4 — logs: correlated back to the trace

Same service page → Logs tab. Find a `request` log line and note its trace — then
compare it to the trace you looked at in Step 2. The correlation is real, not
cosmetic: `logging_config.py`'s `TraceContextFilter` and the OTel `LoggingHandler`
both read the *same* active span context at the moment the log line was written, so
a log line and its trace share the exact same `trace_id`. This is what "the three
pillars" actually means in practice: one identifier lets you pivot from "this
request was slow" (trace) to "here's what it logged while running" (logs) without
manually cross-referencing timestamps.

### Step 5 — errors: what an *unhandled* exception looks like

The Errors tab is empty so far — nothing has thrown an exception yet. Trigger a
real one (temporarily break the DB connection mid-request, not a validation error
— Pydantic 422s are normal responses, not exceptions):

```bash
docker compose stop db
COOKIES=$(mktemp)
curl -s -c "$COOKIES" -X POST http://127.0.0.1:8000/login \
  -H "Content-Type: application/json" -d '{"username":"testuser","password":"password1234"}' -o /dev/null
curl -s -b "$COOKIES" -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/api/entries   # 500
rm -f "$COOKIES"
docker compose start db
```

Refresh the Errors tab: a `sqlalchemy.exc.OperationalError` group appears, with the
**full original exception message and the actual failing SQL statement** —
`db.py`'s `get_all_entries()` has no `try`/`except` around the query, so the
exception propagates all the way up through FastAPI, and the instrumentation
captures it exactly as it happened. (It's flagged `"handled": true` — meaning
FastAPI's own exception-handling middleware caught it and returned a clean `500`
rather than crashing the process; "handled" here is about the process surviving,
not about anyone in application code having written a `try`/`except`.)

### What this tour does *not* show you — because it isn't there

- **No Service Map** — needs an Elastic Platinum license; `403` on this free tier.
- **No dashboards** — nothing's been built in Lens; you're reading the built-in APM
  views, not a curated operational dashboard.
- **No alerting** — nothing pages anyone if latency spikes or the error rate climbs.
  Kibana's Alerting framework exists and could be wired to this data, but isn't.
- **No retention policy** — data just accumulates on one Elasticsearch node; no
  ILM, no backups.
- **No security** — `xpack.security.enabled: false` everywhere; anyone who can
  reach these ports has full access. Fine for local learning, not for anything real.

That gap — from "I can go look at what happened" (everything above) to "the system
tells someone when something's wrong" (none of the above) — is the actual
difference between a working observability *setup* and a mature observability
*practice*. Worth keeping in mind before assuming more of this exists than does.

---

## 11. Running on Kubernetes (kind)

`k8s/` holds manifests for app + Postgres, scoped deliberately — Elasticsearch/
Kibana/Collector stay on compose (§9); this is about the deploy pattern, not
re-running the observability stack in a second place. This section uses `kind`
(Kubernetes-in-Docker) to test against a real local cluster. Not installed by
default — install once:

```bash
curl -sLo kubectl "https://dl.k8s.io/release/$(curl -sL https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
chmod +x kubectl && mv kubectl ~/.local/bin/kubectl
curl -sLo kind "https://kind.sigs.k8s.io/dl/v0.25.0/kind-linux-amd64"
chmod +x kind && mv kind ~/.local/bin/kind
```

Create the cluster and load the app image into it (`kind` clusters don't see the
host's Docker images automatically — `imagePullPolicy: Never` in the manifests
expects this explicit load, since there's no registry for local testing):

```bash
kind create cluster --name simpleapp
docker build -t simpleapp:k8s-test .
kind load docker-image simpleapp:k8s-test --name simpleapp
```

Namespace and Secrets first (see `k8s/secret.example.yaml` for the shape — same
"commit the shape, never the values" pattern as `.env.example`; reuses the same test
credentials as elsewhere in this Runbook):

```bash
kubectl apply -f k8s/namespace.yaml
kubectl create secret generic postgres-credentials -n simpleapp \
  --from-literal=POSTGRES_USER=simpleapp \
  --from-literal=POSTGRES_PASSWORD=simpleapp_dev \
  --from-literal=POSTGRES_DB=simpleapp
kubectl create secret generic simpleapp-secrets -n simpleapp \
  --from-literal=DATABASE_URL="postgresql+psycopg2://simpleapp:simpleapp_dev@db/simpleapp" \
  --from-literal=SESSION_SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')" \
  --from-literal=APP_USERNAME=testuser \
  --from-literal=APP_PASSWORD_HASH="<.venv/bin/python scripts/hash_password.py output>"
```

Then Postgres, the migration Job, and the app — **in that order, waiting between
each** (plain Kubernetes manifests have no equivalent of compose's `depends_on:
condition: service_completed_successfully`; see `CLAUDE.md`'s Step D note):

```bash
kubectl apply -f k8s/postgres.yaml
kubectl wait --for=condition=Ready pod -l app=db -n simpleapp --timeout=90s

kubectl apply -f k8s/migrate-job.yaml
kubectl wait --for=condition=Complete job/migrate -n simpleapp --timeout=60s
kubectl logs job/migrate -n simpleapp   # should show "Running upgrade -> ..."

kubectl apply -f k8s/app.yaml
kubectl wait --for=condition=Ready pod -l app=simpleapp -n simpleapp --timeout=60s
```

Reach it (no Ingress/LoadBalancer set up — that's Phase 7 territory):

```bash
kubectl port-forward -n simpleapp svc/app 8080:8000
```

Everything in §3, §4, and §7 works the same against `http://127.0.0.1:8080`.
`kubectl get pods -n simpleapp` and `kubectl logs -n simpleapp <pod>` are the
`docker compose ps`/`logs` equivalents.

**See the liveness/readiness split actually do its job** (this is what those two
separate endpoints, from Phase 5, are for):

```bash
kubectl scale deployment/db -n simpleapp --replicas=0    # simulate a DB outage
sleep 20
kubectl get pods -n simpleapp                # app: 0/1 Ready, RESTARTS still 0
kubectl get endpoints app -n simpleapp       # empty — pulled from the Service
kubectl get events -n simpleapp | grep Unhealthy   # "Readiness probe failed... 503"

kubectl scale deployment/db -n simpleapp --replicas=1    # restore
kubectl wait --for=condition=Ready pod -l app=db -n simpleapp --timeout=60s
# app returns to 1/1 Ready and back in the Service — still RESTARTS: 0 the whole time
```

Tear down:

```bash
kind delete cluster --name simpleapp
```

---

## 12. Why it's built this way — choices, trade-offs, alternatives

Plain-English summary. This is a **learning project** (see `CLAUDE.md`'s Purpose) —
several choices below deliberately favor "see how the real thing works" over "fastest
way to ship," which is called out explicitly where relevant.

| Choice | Why | Advantage | Drawback / what production would add |
|---|---|---|---|
| **Postgres over SQLite** (Phase 3) | Roadmap goal: learn a real client-server DB, not just a file format | Real types (`DATE` rejects bad literals SQLite would silently store), concurrent access, matches how most production apps run | Needs a running service, not just a file — more moving parts for a trivial app |
| **SQLAlchemy 2.0 typed ORM** | Standard, well-known Python ORM; typed `Mapped[...]` is current best practice | No hand-written SQL, DB-agnostic query layer, IDE type-checking on models | A thin wrapper over raw SQL/`psycopg2` would've been less code for something this small — the ORM earns its keep once the schema grows |
| **Alembic migrations** (not `create_all()`) | `create_all()` can't express schema *changes*, only initial creation | Every schema change is a reviewable, versioned file; `alembic upgrade head` is the same command whether it's the 1st or 50th migration | One more tool/command to learn; overkill if the schema never changes again |
| **Session-cookie auth** (Starlette `SessionMiddleware`) over JWT/OAuth | Simplest thing that's still real server-side auth; single-user app has no need for stateless tokens across services | No token-refresh logic, no client-side token storage to secure, server can invalidate a session instantly | Doesn't scale to multiple backend instances without a shared session store (Redis, etc.) — fine here, wouldn't be at scale |
| **`hashlib.scrypt`** for password hashing | Stdlib, no new dependency, real memory-hard KDF (same family as bcrypt/argon2) | One less third-party dependency to trust/patch | A dedicated library (`argon2-cffi`, `passlib`) would auto-tune parameters and handle hash-format migration over time — hand-rolled here purely for the learning value |
| **Single-user design** | This literally is one person's training log (see `CLAUDE.md` Purpose) | Authz collapses to "must be logged in" — no per-resource permission logic to get wrong | Not multi-tenant: no `users` table, no `entries.user_id` FK, no per-user data isolation — would need adding before a second real user ever touched it |
| **`SameSite=Lax` + `HttpOnly` cookie, security headers** (Phase 4) | Standard, low-effort CSRF/XSS/clickjacking mitigations that don't need a library | Meaningful protection for near-zero code | Not a substitute for rate limiting on `/login` (still absent, deferred to Phase 7) or HTTPS (deferred to Phase 6/7 — needs a reverse proxy) |
| **Stdlib `logging` + custom JSON formatter** over a logging library | `extra={...}` already does everything needed; one less dependency | Full control, no library API to learn, easy to read (`logging_config.py` is ~45 lines) | A library like `structlog` would add contextvars-based automatic context propagation (e.g. request ID threaded through without passing it explicitly everywhere) |
| **OTel auto-instrumentation** (Phase 5, Step C) | Auto-instrumentation (`FastAPIInstrumentor`, `SQLAlchemyInstrumentor`) needs zero manual span code anywhere in `app.py`/`db.py` | A request span with a nested DB-query span appears for free, in both the native (console) and compose (real backend) paths | Only covers HTTP routes and SQL queries — anything else worth tracing (a slow external call, a background job) would still need a manual span |
| **Console exporters natively, real OTLP export in compose** (Phase 5 Step C → Phase 6 Step C) | No backend needed for native dev; compose has one, so use it | See a real trace immediately with zero infrastructure locally; see the same data actually land in Elasticsearch/Kibana when running via compose — same code, `OTEL_EXPORTER_OTLP_ENDPOINT` env var is the only difference | The Collector's `elasticsearch` exporter is explicitly marked "Development component. May change in the future." in its own logs, and silently dropped every histogram metric until `otel_setup.py` was fixed to request delta temporality (see `CLAUDE.md`'s Phase 6 Step C note) — real backends have real rough edges a console exporter never surfaces |
| **Native install first, Docker later** (Postgres native in Phase 3, containerized in Phase 6) | Deliberate ordering on the roadmap — understand what's *inside* the container (a real `systemd`-managed Postgres, manual role/db creation) before automating it away | Both are now visible side by side: `docker compose up` is one command vs. several `sudo` steps for the native install | The two Postgres instances are genuinely separate databases with separate data (§9) — a source of "why don't I see my entries" confusion if forgotten |
| **Elastic export deferred from Phase 5 to Phase 6** | Running Elasticsearch (+Kibana +Collector) natively would've been heavy (~2GB+ RAM, several `sudo` steps) for something that became near-free as Compose services one phase later | Avoided doing real infrastructure work twice (once native, then redone in containers) — done once, done as Compose services (§9) | Traces + metrics now land in Elasticsearch when running via compose (§9); structured logs still don't (see the next row) — native dev is still console-only for all three, by design |
| **Structured logs now shipped to Elasticsearch too** (Step C follow-up) | Closed the gap Step C deliberately left open, via an OTel logging bridge (`logging_config.py`) — no new dependency, same `OTEL_EXPORTER_OTLP_ENDPOINT` toggle | Traces, metrics, *and* logs are all in Elasticsearch now, all correlated by `trace_id` | Stdout JSON logging stays too (§5), as a second parallel output — not a replacement, so there are now two places a log line lives when running via compose |
| **Discovered `mapping: mode: otel` is broken, used a real APM Server instead** | The `elasticsearch` exporter's OTel mapping mode broke every metric (`document_parsing_exception`) with this `elasticsearchexporter` 0.113.0 + Elasticsearch 8.15.3 pairing — a real bug, not a config mistake. Rather than work around it, added a dedicated `apm-server` service and re-pointed the Collector at it (`otlphttp/elastic` exporter) | APM Server owns the OTel→Elastic-APM mapping itself (its actual job); Kibana's APM UI now genuinely works — real per-route latency (`POST /login` ~75ms, the scrypt cost, vs. `GET /healthz` ~2ms), and APM Server auto-computes rollup metrics (service summary, per-transaction stats) from raw traces | One more service to run; Service Map specifically needs an Elastic **Platinum** license (`403` on the free/basic tier this runs on) — not a bug, a real licensing wall |
| **k8s manifests scoped to app + Postgres only** (Phase 6 Step D) | Elasticsearch/Kibana/Collector already proven via compose (§9) — re-deploying the whole observability stack a second time in `kind` would prove the same thing twice | Kept the `kind` cluster light (~400MB idle) and the step focused on the actual new thing: the deploy pattern itself (Secrets, probes, a migration Job) | A real k8s deployment of this app would need the full stack — this only proves the app+DB half of it works on Kubernetes |
| **`kind` (Kubernetes-in-Docker) for testing, not a cloud cluster** | Free, local, fast to create/destroy (~30s), no cloud account or cost | Same verify-don't-just-write discipline as every other phase, with zero external dependency | `imagePullPolicy: Never` + `kind load docker-image` only works because there's no registry involved — a real cluster needs a real one (ECR/GCR/Docker Hub), which changes the image-distribution step non-trivially |

### Known gaps, deferred on purpose (not forgotten)

- No rate limiting / brute-force protection on `/login` — Phase 7.
- No HTTPS/TLS — needs a reverse proxy, Phase 6/7 (no Ingress/LoadBalancer set up
  for the k8s manifests either — `kubectl port-forward` only, for now).
- No dependency vulnerability scanning.
- No true SQL `NULL` tested anywhere — `notes` is non-NULL at both ORM and DB level;
  every other field is required. No optional-field design exists yet.
- Kibana's APM Service Map needs an Elastic Platinum license — `403` on the free/
  basic tier this stack runs on (everything else in the APM UI works, see §9).
- k8s manifests don't include Elasticsearch/Kibana/Collector/APM Server (Phase 6
  Step D scope — see the trade-offs row above).
- CI pipeline — later Phase 6 step.
- Graceful shutdown beyond OTel flush, 12-factor config review, load testing — Phase 7.
