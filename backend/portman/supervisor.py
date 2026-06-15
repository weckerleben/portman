"""Process supervisor: launch, monitor and tear down managed services.

Deliberately DB-agnostic — it owns OS processes and their log files, keyed by an
opaque integer (the caller's service id). The API layer maps these to ``Run``
records. Each service runs in its own session/process group so we can signal the
whole tree, not just the shell.
"""

from __future__ import annotations

import os
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import config, ports


@dataclass
class LaunchSpec:
    """Everything needed to launch a service process."""

    key: int  # registry key (the service id)
    run_id: int  # used to name the log file
    slug: str
    command: str
    cwd: str = ""
    env: dict | None = None


@dataclass
class ProcInfo:
    key: int
    pid: int
    run_id: int
    log_path: str
    running: bool
    returncode: int | None = None


class _Handle:
    __slots__ = ("popen", "log_file", "log_path", "spec")

    def __init__(self, popen: subprocess.Popen, log_file, log_path: str, spec: LaunchSpec):
        self.popen = popen
        self.log_file = log_file
        self.log_path = log_path
        self.spec = spec


class Supervisor:
    """In-memory registry of running managed processes."""

    def __init__(self, logs_dir: str | Path | None = None):
        self._logs_dir = Path(logs_dir) if logs_dir else Path(config.LOGS_DIR)
        self._procs: dict[int, _Handle] = {}

    # --- inspection ---------------------------------------------------------

    def keys(self) -> list[int]:
        return list(self._procs.keys())

    def is_running(self, key: int) -> bool:
        handle = self._procs.get(key)
        return handle is not None and handle.popen.poll() is None

    def info(self, key: int) -> ProcInfo | None:
        handle = self._procs.get(key)
        if handle is None:
            return None
        rc = handle.popen.poll()
        return ProcInfo(
            key=key,
            pid=handle.popen.pid,
            run_id=handle.spec.run_id,
            log_path=handle.log_path,
            running=rc is None,
            returncode=rc,
        )

    # --- lifecycle ----------------------------------------------------------

    def start(self, spec: LaunchSpec) -> ProcInfo:
        if self.is_running(spec.key):
            raise RuntimeError(f"service {spec.key} is already running")
        self._drop_if_dead(spec.key)

        log_dir = self._logs_dir / spec.slug
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"{spec.run_id}.log"
        log_file = open(log_path, "ab", buffering=0)

        env = {**os.environ, **{k: str(v) for k, v in (spec.env or {}).items()}}
        try:
            popen = subprocess.Popen(  # noqa: S602 - user-authorized local command
                spec.command,
                shell=True,
                cwd=spec.cwd or None,
                env=env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except Exception:
            log_file.close()
            raise

        self._procs[spec.key] = _Handle(popen, log_file, str(log_path), spec)
        return self.info(spec.key)  # type: ignore[return-value]

    def stop(self, key: int, timeout: float = 5.0) -> ProcInfo | None:
        """Graceful: SIGTERM the group, then SIGKILL if it overstays ``timeout``."""
        return self._signal_and_wait(key, signal.SIGTERM, timeout)

    def kill(self, key: int) -> ProcInfo | None:
        """Forceful: SIGKILL the group immediately."""
        return self._signal_and_wait(key, signal.SIGKILL, timeout=2.0)

    def restart(self, spec: LaunchSpec) -> ProcInfo:
        self.stop(spec.key)
        return self.start(spec)

    def kill_port(self, port: int, sig: int = signal.SIGTERM) -> list[int]:
        """Signal whatever is listening on ``port`` (managed or not)."""
        killed: list[int] = []
        for pid in ports.pids_on_port(port):
            try:
                os.kill(pid, sig)
                killed.append(pid)
            except ProcessLookupError:
                continue
        return killed

    # --- internals ----------------------------------------------------------

    def _signal_and_wait(self, key: int, sig: int, timeout: float) -> ProcInfo | None:
        handle = self._procs.get(key)
        if handle is None:
            return None
        if handle.popen.poll() is None:
            self._signal_group(handle.popen.pid, sig)
            try:
                handle.popen.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                self._signal_group(handle.popen.pid, signal.SIGKILL)
                try:
                    handle.popen.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    pass
        info = self.info(key)
        self._close(key)
        return info

    @staticmethod
    def _signal_group(pid: int, sig: int) -> None:
        try:
            os.killpg(os.getpgid(pid), sig)
        except ProcessLookupError:
            pass

    def _close(self, key: int) -> None:
        handle = self._procs.get(key)
        if handle is not None:
            try:
                handle.log_file.close()
            except OSError:
                pass

    def _drop_if_dead(self, key: int) -> None:
        handle = self._procs.get(key)
        if handle is not None and handle.popen.poll() is not None:
            self._close(key)
            del self._procs[key]
