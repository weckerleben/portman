# Per-project setup

**Short answer: your projects need _no_ changes to work with portman.** You can
register any service from the dashboard or the CLI without touching the project.

The optional bits below make a project's port usage *reproducible* — worth doing
for anything you run regularly.

## Do I have to configure each project?

| You want… | Required change in the project |
|---|---|
| Manage a service ad-hoc | **None** — register it in the UI / `portman register` |
| Reproducible, version-controlled service definitions | Add a `portman.yaml` (optional) |
| The service to bind the port portman assigned | Have it read the `PORT` env var (most dev servers already do) |

## The `PORT` convention

When a service has an assigned port, portman injects it as the `PORT`
environment variable before launching the command. Two ways to use it:

1. **Reference it in the command** (works everywhere):
   ```
   npm run dev -- --port $PORT
   python -m uvicorn app:app --port $PORT
   ```
2. **Let the framework pick it up** — many already read `PORT`:
   - Next.js (`next dev`/`next start`), Create React App, Vite (with `--port $PORT`)
   - Express/Node: `app.listen(process.env.PORT || 3000)`
   - Flask/FastAPI via `uvicorn`/`gunicorn`: pass `--port $PORT`

If a service ignores `PORT` and hardcodes its own, portman still tracks and
controls it — but it can't guarantee the port matches the assignment, so prefer
the convention above.

## `portman.yaml` (optional, recommended)

Drop a `portman.yaml` at a project root to declare its services. Then:

```bash
portman import            # from the project directory
portman import /path/to/project
```

Import is **idempotent** and matches on service `name`: editing the file and
re-importing updates the existing service instead of duplicating it.

```yaml
services:
  - name: web
    command: "npm run dev -- --port $PORT"
    cwd: .                 # relative to this file; defaults to the manifest dir
    port: auto             # a fixed number, or "auto" for a generated free port
    description: "Next.js dev server"
    auto_restart: false    # reserved for a future watchdog
  - name: api
    command: "uvicorn app:app --port $PORT"
    cwd: backend
    port: 8000
    description: "Backend API"
```

| Field | Required | Notes |
|---|---|---|
| `name` | yes | Unique; re-import matches on it |
| `command` | yes | Shell command; `$PORT` is injected when a port is assigned |
| `cwd` | no | Relative to the manifest file; defaults to its directory |
| `port` | no | A number, or `auto`. Omitted = no assigned port |
| `description` | no | "What it does", shown in the UI |
| `auto_restart` | no | Stored now; honored by a future watchdog |

There is a working example at the repo root: [`../portman.yaml`](../portman.yaml).

## Recommended workflow per project

1. Add a `portman.yaml` describing its services (commit it).
2. `portman import` once (or after edits).
3. Start everything from the dashboard or `portman start <name>`.
4. Anything that appears **unauthorized** in the dashboard is something launched
   outside portman — investigate or kill it from there.
