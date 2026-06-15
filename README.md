<div align="center">

# portman

**A local control plane for ports and dev services.**
See what's listening, *why*, and on whose authority — then start, stop, kill,
reserve, generate and audit it all from one place.

</div>

---

portman runs on your machine and answers the questions every developer with a
dozen projects eventually asks: *what is on port 3000? what command started it?
what does it even do? and can I stop grabbing random ports by hand?*

Unlike a passive tracker, portman is a **supervisor**: you launch services
*through* it, so it owns the process, captures the logs, monitors health and
controls the lifecycle. A background scanner continuously reconciles every real
listening socket against what it manages and flags anything else as
**unauthorized** — with a one-click kill and a full audit trail.

> **The authorization model, honestly.** On macOS nothing can truly *prevent* a
> process from binding a port without kernel-level hooks. portman enforces
> "nothing runs without authorization" as a **workflow + detective control**:
> you commit to launching services through portman, and it surfaces (and lets you
> kill) anything that bypassed it, recording every action. See
> [docs/SECURITY.md](docs/SECURITY.md).

## Features

- **Live port map** — every listening port with its process, PID, command, cwd
  and owner, classified as `managed` / `unauthorized`.
- **Authorize & supervise services** — register a command + working dir + env +
  description, get an assigned port, and run it under portman.
- **Full lifecycle** — start · stop (SIGTERM) · kill (SIGKILL) · restart, plus
  **kill-port** for anything (managed or rogue) sitting on a port.
- **Live logs** — every run's stdout/stderr captured to a file and streamed to
  the dashboard.
- **Reserve & generate ports** — hold a port for a purpose, or generate a random
  free one that avoids everything in use or reserved.
- **Unauthorized detection** — a scanner flags ports bound outside portman and
  records them in the audit log.
- **Audit trail** — every authorize / start / stop / kill / reserve / flag event
  is persisted.
- **Per-project manifests** — declare a project's services in `portman.yaml` and
  `portman import` them. Generate that file in one step with `portman init`, which
  scans the project and infers its services (with optional AI enrichment). See
  [docs/PER_PROJECT.md](docs/PER_PROJECT.md).
- **CLI + Web UI** — a dark control-room dashboard and a full `portman` CLI over
  the same local API.

## Architecture at a glance

```
 React + Vite SPA  ──HTTP/WS──▶  FastAPI daemon (127.0.0.1:7878)
 (control-room UI)               ├─ ports.py      psutil introspection
                                 ├─ supervisor.py subprocess lifecycle + logs
       portman CLI ──HTTP──▶     ├─ scanner.py    reconcile → unauthorized
                                 ├─ audit.py      append-only event log
                                 └─ SQLite        services / reservations / runs / audit
```

Runtime state lives in `~/.portman/` (SQLite DB + per-run logs); the repo never
holds it. Full detail in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Requirements

- macOS or Linux
- Python ≥ 3.11
- Node ≥ 18 (only to build the web UI)

## Install

```bash
git clone https://github.com/weckerleben/portman.git
cd portman

# 1. Backend (creates the `portman` command)
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 2. Web UI (build once; the daemon serves it)
cd ../frontend
npm install
npm run build
```

## Usage

```bash
portman up                 # start the daemon (detached) and open the dashboard
portman ls                 # live port map, classified
portman services           # registered services

# Authorize and run a service
portman register -n web -c "npm run dev -- --port \$PORT" --cwd ~/dev/site --auto-port
portman start web
portman restart web
portman stop web
portman kill web

# Ports
portman new                # a random free port
portman reserve 8080 --for "future websocket gateway"
portman kill-port 3000     # kill whatever is on a port (managed or not)

# Project manifests
portman init               # scan the project → write a ./portman.yaml (no daemon needed)
portman init --blank       # just a template to fill in
portman init --ai          # enrich detection with Claude (needs an API key)
portman import             # register services from ./portman.yaml

# AI key (for `init --ai`; there is no Claude-account login for third-party tools)
portman login              # store an Anthropic API key in ~/.portman (chmod 600)
portman logout             # remove it

portman down               # stop the daemon (supervised services keep running)
```

`$PORT` is injected into each service's environment, so commands like
`npm run dev -- --port $PORT` bind the port portman assigned.

## Development

```bash
# Backend tests (TDD core: ports, supervisor, scanner, audit, manifest, api)
cd backend && pytest --cov=portman

# Frontend
cd frontend && npm run test       # vitest
npm run dev                       # Vite dev server, proxies /api + /ws to the daemon
```

## License

[MIT](LICENSE) © 2026 William Eckerleben
