"""``portman`` command line: manage the daemon and talk to its API.

The daemon is a uvicorn process serving :data:`portman.app.app`. ``up`` launches
it detached and waits until healthy; every other command is a thin client over
the local HTTP API.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

import httpx
import typer
from rich.console import Console
from rich.table import Table

from . import ai as ai_mod
from . import config, credentials, detect
from . import update as update_mod
from .manifest import MANIFEST_NAME

app = typer.Typer(help="Local port & service manager.", no_args_is_help=True)
console = Console()


@app.callback()
def _main() -> None:
    """Local port & service manager."""
    # Best-effort, cache-gated, fail-silent "new version available" nudge.
    update_mod.notify_if_outdated()

STATUS_STYLE = {
    "managed": "bold green",
    "unauthorized": "bold red",
    "reserved": "yellow",
}


def _url(path: str = "") -> str:
    return f"http://{config.DEFAULT_HOST}:{config.DEFAULT_PORT}{path}"


def _client() -> httpx.Client:
    return httpx.Client(base_url=_url(), timeout=10.0)


def _daemon_running() -> bool:
    try:
        return httpx.get(_url("/api/health"), timeout=1.0).status_code == 200
    except httpx.HTTPError:
        return False


def _require_daemon() -> None:
    if not _daemon_running():
        console.print("[red]portman daemon is not running.[/] Start it with [bold]portman up[/].")
        raise typer.Exit(code=1)


def _resolve_service(client: httpx.Client, ref: str) -> dict:
    for svc in client.get("/api/services").json():
        if ref in (str(svc["id"]), svc["slug"], svc["name"]):
            return svc
    console.print(f"[red]No service matching '{ref}'.[/]")
    raise typer.Exit(code=1)


# --- daemon lifecycle -------------------------------------------------------


@app.command()
def serve(
    host: str = config.DEFAULT_HOST,
    port: int = config.DEFAULT_PORT,
) -> None:
    """Run the daemon in the foreground (used internally by ``up``)."""
    import uvicorn

    config.ensure_dirs()
    uvicorn.run("portman.app:app", host=host, port=port, log_level="info")


@app.command()
def up(open_ui: bool = typer.Option(True, "--open/--no-open", help="Open the UI in a browser.")) -> None:
    """Start the daemon (detached) and open the dashboard."""
    if _daemon_running():
        console.print("[green]portman is already running.[/]")
    else:
        config.ensure_dirs()
        log = open(config.DATA_DIR / "daemon.log", "ab", buffering=0)
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "portman.app:app",
             "--host", config.DEFAULT_HOST, "--port", str(config.DEFAULT_PORT)],
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        config.PID_FILE.write_text(str(proc.pid))
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and not _daemon_running():
            time.sleep(0.25)
        if not _daemon_running():
            console.print("[red]Daemon failed to start.[/] Check ~/.portman/daemon.log")
            raise typer.Exit(code=1)
        console.print(f"[green]portman is up[/] at {_url()}")
    if open_ui:
        webbrowser.open(_url("/"))


@app.command()
def down() -> None:
    """Stop the daemon. (Supervised services keep running — they are detached.)"""
    if not config.PID_FILE.exists():
        console.print("[yellow]No PID file; daemon may not be running.[/]")
        raise typer.Exit(code=0)
    pid = int(config.PID_FILE.read_text().strip())
    try:
        os.kill(pid, signal.SIGTERM)
        console.print(f"[green]Stopped daemon[/] (pid {pid}).")
    except ProcessLookupError:
        console.print("[yellow]Daemon was not running.[/]")
    config.PID_FILE.unlink(missing_ok=True)


@app.command()
def status() -> None:
    """Show whether the daemon is up."""
    if _daemon_running():
        console.print(f"[green]running[/] at {_url()}")
    else:
        console.print("[red]not running[/]")


@app.command(name="open")
def open_ui() -> None:
    """Open the dashboard in a browser."""
    webbrowser.open(_url("/"))


# --- inspection -------------------------------------------------------------


@app.command()
def ls() -> None:
    """List every live port and how portman classifies it."""
    _require_daemon()
    with _client() as client:
        view = client.get("/api/ports").json()
    table = Table(title="Ports", header_style="bold")
    for col in ("Port", "Status", "Service / Process", "PID", "Command"):
        table.add_column(col, overflow="fold")
    for entry in view["ports"]:
        style = STATUS_STYLE.get(entry["status"], "")
        table.add_row(
            str(entry["port"]),
            f"[{style}]{entry['status']}[/]" if style else entry["status"],
            entry.get("name") or "-",
            str(entry.get("pid") or "-"),
            (entry.get("cmdline") or "")[:60],
        )
    console.print(table)
    counts = view["counts"]
    console.print(
        f"managed=[green]{counts['managed']}[/]  "
        f"unauthorized=[red]{counts['unauthorized']}[/]  "
        f"reserved-idle=[yellow]{counts['reserved_idle']}[/]"
    )


@app.command()
def services() -> None:
    """List registered services."""
    _require_daemon()
    with _client() as client:
        rows = client.get("/api/services").json()
    table = Table(title="Services", header_style="bold")
    for col in ("ID", "Name", "Port", "Running", "Command"):
        table.add_column(col, overflow="fold")
    for svc in rows:
        table.add_row(
            str(svc["id"]),
            svc["name"],
            str(svc["assigned_port"] or "-"),
            "[green]yes[/]" if svc["running"] else "no",
            svc["command"][:50],
        )
    console.print(table)


# --- mutations --------------------------------------------------------------


@app.command()
def register(
    name: str = typer.Option(..., "--name", "-n"),
    command: str = typer.Option(..., "--command", "-c"),
    description: str = typer.Option("", "--desc", "-d"),
    cwd: str = typer.Option("", "--cwd"),
    port: int = typer.Option(None, "--port", "-p"),
    auto_port: bool = typer.Option(False, "--auto-port", help="Assign a random free port."),
) -> None:
    """Register (authorize) a new service."""
    _require_daemon()
    with _client() as client:
        resp = client.post(
            "/api/services",
            json={
                "name": name,
                "command": command,
                "description": description,
                "cwd": cwd,
                "port": port,
                "auto_port": auto_port,
            },
        )
    _print_response(resp, f"Registered '{name}'")


@app.command()
def reserve(
    port: int = typer.Argument(None, help="Port to reserve (omit with --auto)."),
    purpose: str = typer.Option("", "--for", help="What the port is for."),
    auto: bool = typer.Option(False, "--auto", help="Reserve a random free port."),
) -> None:
    """Reserve a port for a purpose."""
    _require_daemon()
    with _client() as client:
        resp = client.post("/api/reservations", json={"port": port, "purpose": purpose, "auto": auto})
    _print_response(resp, "Reserved")


@app.command()
def new() -> None:
    """Generate a random free port (not reserved, not in use)."""
    _require_daemon()
    with _client() as client:
        port = client.post("/api/ports/generate").json()["port"]
    console.print(f"[green]{port}[/]")


@app.command(name="import")
def import_manifest(path: str = typer.Argument(".", help="Project dir or portman.yaml path.")) -> None:
    """Register services declared in a project's portman.yaml."""
    _require_daemon()
    with _client() as client:
        resp = client.post("/api/manifest/import", json={"path": os.path.abspath(path)})
    _print_response(resp, "Imported manifest")


@app.command()
def init(
    path: str = typer.Argument(".", help="Project directory to scan."),
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite an existing portman.yaml."),
    blank: bool = typer.Option(False, "--blank", help="Write a template instead of analysing."),
    ai: bool = typer.Option(False, "--ai", help="Use AI to enrich the detected services."),
) -> None:
    """Generate a portman.yaml for a project (no daemon required).

    With no flags, scans the directory and writes the services it detects. If
    nothing is found it offers AI enrichment. ``--blank`` writes a plain
    template; ``--ai`` forces AI enrichment.
    """
    root = Path(path).expanduser().resolve()
    target = root / MANIFEST_NAME
    if target.exists() and not force:
        console.print(f"[yellow]{target} already exists.[/] Use [bold]--force[/] to overwrite.")
        raise typer.Exit(code=1)

    services: list[detect.DetectedService] = []
    if not blank:
        services = detect.detect_services(root)
        if services:
            console.print(f"[green]Detected {len(services)} service(s)[/] from project files.")
        elif not ai and sys.stdin.isatty():
            console.print("[yellow]No services detected automatically.[/]")
            ai = typer.confirm("Try AI enrichment with an Anthropic API key?", default=False)
        if ai:
            services = _merge(services, _enrich(root, services))

    target.write_text(detect.render_manifest(services))
    console.print(f"[green]Wrote {target}[/] ({len(services)} service(s)). Review it, then [bold]portman import[/].")


@app.command()
def login(key: str = typer.Option(None, "--key", help="Anthropic API key (omit to be prompted).")) -> None:
    """Store an Anthropic API key for the AI features (~/.portman, chmod 600).

    There is no "log in with your Claude account" — that OAuth is first-party to
    Anthropic's apps. Create an API key at https://console.anthropic.com.
    """
    if not key:
        key = typer.prompt("Paste your Anthropic API key", hide_input=True)
    path = credentials.set_api_key(key)
    console.print(f"[green]API key saved[/] to {path}.")


@app.command()
def logout() -> None:
    """Remove the stored Anthropic API key."""
    credentials.clear_api_key()
    console.print("[green]Stored API key removed.[/]")


@app.command()
def upgrade() -> None:
    """Upgrade portman to the latest published version."""
    latest = update_mod.check_for_update()
    current = update_mod.installed_version()
    if latest is None:
        console.print(f"[green]portman is up to date[/] ({current}).")
        return
    cmd = update_mod.detect_upgrade_command()
    console.print(f"[bold]Upgrading[/] {current} → {latest}: {' '.join(cmd)}")
    try:
        code = subprocess.call(cmd)
    except FileNotFoundError:
        console.print(f"[red]{cmd[0]} not found.[/] Upgrade manually with your installer.")
        raise typer.Exit(code=1)
    raise typer.Exit(code=code)


def _enrich(root: Path, existing: list[detect.DetectedService]) -> list[detect.DetectedService]:
    key = credentials.get_api_key()
    if not key:
        console.print("[yellow]No Anthropic API key found.[/]")
        key = typer.prompt("Paste your Anthropic API key", hide_input=True).strip()
        credentials.set_api_key(key)
        console.print("[green]Saved for next time.[/]")
    try:
        return ai_mod.enrich_services(root, existing, key)
    except ai_mod.AIError as exc:
        console.print(f"[red]AI enrichment failed:[/] {exc}")
        return []


def _merge(*groups: list[detect.DetectedService]) -> list[detect.DetectedService]:
    seen: set[str] = set()
    merged: list[detect.DetectedService] = []
    for group in groups:
        for svc in group:
            if svc.name in seen:
                continue
            seen.add(svc.name)
            merged.append(svc)
    return merged


@app.command()
def start(service: str) -> None:
    """Start a service."""
    _lifecycle(service, "start")


@app.command()
def stop(service: str) -> None:
    """Stop a service (SIGTERM)."""
    _lifecycle(service, "stop")


@app.command()
def restart(service: str) -> None:
    """Restart a service."""
    _lifecycle(service, "restart")


@app.command()
def kill(service: str) -> None:
    """Kill a service (SIGKILL)."""
    _lifecycle(service, "kill")


@app.command(name="kill-port")
def kill_port(port: int) -> None:
    """Kill whatever is listening on a port (managed or not)."""
    _require_daemon()
    with _client() as client:
        resp = client.post(f"/api/ports/{port}/kill")
    _print_response(resp, f"Signalled port {port}")


def _lifecycle(service: str, action: str) -> None:
    _require_daemon()
    with _client() as client:
        svc = _resolve_service(client, service)
        resp = client.post(f"/api/services/{svc['id']}/{action}")
    _print_response(resp, f"{action} '{svc['name']}'")


def _print_response(resp: httpx.Response, ok_message: str) -> None:
    if resp.is_success:
        console.print(f"[green]{ok_message}.[/]")
    else:
        detail = resp.json().get("detail", resp.text) if resp.content else resp.text
        console.print(f"[red]Error {resp.status_code}:[/] {detail}")
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
