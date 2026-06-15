# Architecture

portman is a single local daemon (FastAPI) plus a React SPA and a CLI, all
talking to the same HTTP/WebSocket API on `127.0.0.1:7878`.

## Layers

```
frontend/  React + Vite + Tailwind SPA  ── built to dist/, served by the daemon
backend/portman/
  config.py      paths & constants (PORTMAN_HOME -> ~/.portman)
  db.py          SQLAlchemy engine + session_scope()
  models.py      Service · PortReservation · Run · AuditEvent
  ports.py       psutil introspection + free-port finder        (system truth)
  supervisor.py  subprocess spawn/stop/kill/restart + log files  (process truth)
  scanner.py     reconcile system truth vs managed/reserved      (classification)
  audit.py       append-only event log helpers
  manifest.py    parse + import portman.yaml
  runtime.py     operations layer wiring all of the above + singletons
  schemas.py     Pydantic request validation
  api.py         REST routes + WebSockets
  app.py         ASGI app: API + SPA mount + background scan loop
  cli.py         `portman` CLI (Typer): daemon lifecycle + API client
```

## Why these boundaries

- **`ports.py` is "system truth."** It reports what is actually listening, with
  zero knowledge of portman's database. On macOS the system-wide
  `psutil.net_connections()` requires root, so it enumerates **per process**
  (`proc.net_connections()`), which works without elevation for the current
  user's own processes — exactly the dev servers we manage.
- **`supervisor.py` is "process truth."** It owns `Popen` handles keyed by
  service id, launches each in its own session/process group
  (`start_new_session=True`) so a whole tree can be signalled, and streams
  stdout+stderr to `~/.portman/logs/<slug>/<run-id>.log`. It is DB-agnostic.
- **`scanner.py` reconciles the two.** Matching is by **port**, not PID: a
  service is launched via a shell, so the listening socket often belongs to a
  child PID — but the *port* is the assignment portman knows. A live port that
  maps to a running managed service is `managed`; everything else is
  `unauthorized`.
- **`runtime.py` is the only place that knows about all of them.** API and CLI
  stay thin; the orchestration verbs (create/start/stop/reserve/classify/import)
  live here, along with the two process-lifetime singletons (`supervisor`,
  `scanner`).

## Data model (SQLite)

| Table | Purpose | Key fields |
|---|---|---|
| `services` | Authorized service definitions | name, slug, command, cwd, env, assigned_port, source, manifest_path |
| `port_reservations` | Ports held for a purpose | port, purpose, status |
| `runs` | One execution of a service | service_id, pid, status, started_at, stopped_at, exit_code, log_path |
| `audit_events` | Append-only action log | ts, type, detail (JSON) |

## Request flow (start a service)

1. `POST /api/services/{id}/start` → `runtime.start_service`.
2. A `Run` row is created; `supervisor.start` spawns the process group, redirects
   output to the run's log file, and records the PID.
3. An `audit_events` row of type `start` is written.
4. The scan loop (every 5s) and `GET /api/ports` classify the now-listening port
   as `managed` because it maps to a running managed service.

## Background scan loop

`app.py` starts `runtime.scan_loop` on startup. Each tick reconciles the system
and writes an `audit_events` row for any **newly** unauthorized port (the scanner
remembers what it has already flagged, so a persistent rogue port is logged once,
not every tick). The loop swallows its own exceptions so it can never take the
daemon down.

## Process & data locations

- DB: `~/.portman/portman.db`
- Logs: `~/.portman/logs/<service-slug>/<run-id>.log`
- Daemon PID: `~/.portman/daemon.pid`
- Override the root with `PORTMAN_HOME` (tests point it at a temp dir).

## Frontend

A single-page dashboard polling `GET /api/ports` (2s) and `GET /api/audit` (5s),
with a WebSocket-backed live log drawer. Design tokens live in
`src/styles/tokens.css` and `tailwind.config.js`; the direction is a dark
"control-room" surface with status-driven color (green=managed, red=unauthorized,
amber=reserved). Built output is static and served by the daemon, so production
is a single process.
