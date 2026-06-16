# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.4.0] - 2026-06-16

### Added
- **Conflict-free daemon port** — the daemon binds a random free port chosen on
  first use and persisted to `~/.portman/daemon.port`, so a fresh install never
  collides with a well-known port. `PORTMAN_PORT` still overrides; `up`
  self-heals if the saved port was taken. New **`portman daemon-port`** shows,
  sets, or regenerates it, and `status` now reports the port.
- **`portman doctor`** — reports port conflicts across registered services,
  reservations and live processes.
- Port reservations are now idempotent.

### Changed
- `portman init` assigns concrete random free ports (replacing framework
  defaults), reuses existing ports on re-init, and reserves them when the daemon
  is up.
- Registering or importing a service reassigns a busy fixed port to a free one
  and reports the change.
- `portman upgrade` always checks PyPI fresh, bypassing the 24h cache the passive
  update notifier relies on.

### Tests
- Test suite expanded to **100% coverage**, enforced by a CI coverage floor.

## [0.3.0] - 2026-06-15

### Added
- **`portman --version` / `-v`** — print the version and exit.
- **`portman logs <service>`** — tail a service's most recent run (`--tail N`,
  `--run ID`); previously logs were reachable only from the web UI.
- **`portman unregister <service>`** (alias **`rm`**) — deauthorize a registered
  service from the CLI (`DELETE /api/services` had no CLI caller before).
- **`portman reservations`** and **`portman release <port>`** — list and free
  port reservations from the terminal.
- **`portman audit`** — view recent audit-log events.
- **`portman up --restart`** — restart the daemon when it is already running.

### Changed
- `portman register` accepts `--auto` as an alias of `--auto-port`, consistent
  with `reserve --auto`.
- Service-lifecycle commands now document their `service` argument in `--help`;
  the internal `serve` command is hidden from the command list.
- `__version__` is derived from installed distribution metadata (single source
  of truth), fixing drift from a stale hardcoded value.

### Fixed
- Eliminated all build and test warnings: GitHub Actions bumped to the node24
  runtimes (`checkout@v5`, `setup-python@v6`, `setup-node@v5`, Node 22),
  `asyncio_default_fixture_loop_scope` pinned, and the SQLAlchemy engine is now
  disposed on re-init to stop a `ResourceWarning` connection leak. The one
  remaining third-party deprecation (starlette's `TestClient` httpx notice) is
  filtered until `httpx2` is generally available.

## [0.2.0] - 2026-06-15

### Added
- **`portman init`** — generate a project's `portman.yaml` without the daemon.
  Statically analyses the project (`package.json`, `pyproject.toml`/
  `requirements.txt`, `manage.py`, `docker-compose.yml`, `go.mod`, `Cargo.toml`,
  `Procfile`), including nested frontend/backend subdirs, and writes the detected
  services as ready-to-use, commented entries. `--blank` writes a plain template;
  `--ai` (or an interactive prompt when nothing is detected) enriches detection
  with a small Claude model (`detect.py`, `ai.py`).
- **`portman login` / `logout`** — store/remove an Anthropic API key under
  `~/.portman/credentials.json` (chmod 600) for the AI features; `ANTHROPIC_API_KEY`
  takes precedence. `init --ai` prompts for and saves the key when missing
  (`credentials.py`). Note: there is no "log in with your Claude account" — that
  OAuth is first-party to Anthropic's apps; an API key is the supported path.
- Optional `ai` extra (`pip install "portreeve[ai]"`) pulling in the `anthropic`
  SDK, imported lazily so core portman never requires it.
- **Update notifier + `portman upgrade`** — the CLI checks PyPI for a newer
  release at most once a day (cached in `~/.portman`, fail-silent, opt out with
  `PORTMAN_NO_UPDATE_CHECK=1`) and nudges when one exists; `portman upgrade` runs
  the right command for how it was installed (pipx / uv tool / pip) (`update.py`).
- **Release automation** — `.github/workflows/release.yml` builds the SPA + wheel
  and publishes to PyPI via Trusted Publishing on a `v*` tag.

### Changed
- **Self-contained packaging** — the built web UI is now bundled inside the
  package (`portman/web`) via a hatch build hook, and the daemon resolves the SPA
  from there first (falling back to `frontend/dist` in a dev checkout). This makes
  portman installable as a normal CLI (`uv tool install portreeve`, `pipx install
  portreeve`, `pip install portreeve`) with the dashboard served out of the box —
  no repo checkout or separate frontend build required at install time. The PyPI
  distribution is named `portreeve` (the bare `portman` is taken); the command and
  import package remain `portman`.

## [0.1.0] - 2026-06-15

Initial release.

### Added
- **Port introspection** — live map of every listening port with process, PID,
  command, cwd and owner (`ports.py`, per-process enumeration so it works on
  macOS without root).
- **Random free-port generation** within a configurable range, avoiding ports
  that are in use or reserved.
- **Service supervisor** — register services (command, cwd, env, description,
  assigned port) and run them under portman with start / stop / kill / restart,
  per-run log capture, and a `kill-port` for any port.
- **Reconciliation scanner** — classifies live ports as `managed` or
  `unauthorized` and audit-logs newly appearing unauthorized ports.
- **Append-only audit log** of every authorize / start / stop / kill / kill-port
  / restart / reserve / release / flag event.
- **Port reservations** — hold a port for a stated purpose.
- **FastAPI daemon** — REST API + WebSockets (live status, live logs) that also
  serves the built SPA; background scan loop.
- **`portman` CLI** (Typer) — `up`, `down`, `status`, `ls`, `services`,
  `register`, `reserve`, `new`, `import`, `start`, `stop`, `restart`, `kill`,
  `kill-port`, `open`.
- **Web UI** — dark control-room dashboard: services, live port table, reserve /
  generate, live log drawer, and an activity/audit feed.
- **Per-project manifests** — declare services in `portman.yaml` and import them
  idempotently (`portman import`).
- Documentation: README, architecture, per-project setup, and security model.

[0.3.0]: https://github.com/weckerleben/portman/releases/tag/v0.3.0
[0.2.0]: https://github.com/weckerleben/portman/releases/tag/v0.2.0
[0.1.0]: https://github.com/weckerleben/portman/releases/tag/v0.1.0
