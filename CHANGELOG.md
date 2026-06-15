# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
- Optional `ai` extra (`pip install "port-man[ai]"`) pulling in the `anthropic`
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
  portman installable as a normal CLI (`uv tool install port-man`, `pipx install
  port-man`, `pip install port-man`) with the dashboard served out of the box —
  no repo checkout or separate frontend build required at install time. The PyPI
  distribution is named `port-man` (the bare `portman` is taken); the command and
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

[0.2.0]: https://github.com/weckerleben/portman/releases/tag/v0.2.0
[0.1.0]: https://github.com/weckerleben/portman/releases/tag/v0.1.0
