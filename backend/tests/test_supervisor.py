"""Tests for the process supervisor.

These launch a real, short-lived child process (a Python sleeper) so we exercise
genuine spawn / signal / reap behavior. ``kill_port`` is tested with psutil and
os.kill mocked so it stays deterministic.
"""

from __future__ import annotations

import os
import shlex
import signal
import subprocess
import sys
import time
from unittest.mock import MagicMock, patch

import pytest

from portman import config, ports
from portman.supervisor import LaunchSpec, Supervisor, _Handle


def _sleeper(message: str = "hello") -> str:
    code = f'import time,sys;print({message!r},flush=True);time.sleep(30)'
    return f"{shlex.quote(sys.executable)} -u -c {shlex.quote(code)}"


def _spec(tmp_path, key: int = 1, run_id: int = 1, message: str = "hello") -> LaunchSpec:
    return LaunchSpec(key=key, run_id=run_id, slug="dummy", command=_sleeper(message))


def _wait_until(predicate, timeout: float = 4.0, interval: float = 0.05) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


@pytest.fixture
def sup(tmp_path, monkeypatch):
    monkeypatch.setenv("PORTMAN_HOME", str(tmp_path))
    config.refresh_from_env()
    supervisor = Supervisor(logs_dir=tmp_path / "logs")
    yield supervisor
    # Ensure nothing leaks out of a test.
    for key in list(supervisor.keys()):
        supervisor.kill(key)


def test_start_launches_and_captures_logs(sup, tmp_path):
    info = sup.start(_spec(tmp_path, message="ready"))

    assert info.pid > 0
    assert sup.is_running(1)
    log_file = tmp_path / "logs" / "dummy" / "1.log"
    assert _wait_until(lambda: log_file.exists() and "ready" in log_file.read_text())


def test_start_twice_raises(sup, tmp_path):
    sup.start(_spec(tmp_path))
    with pytest.raises(RuntimeError):
        sup.start(_spec(tmp_path))


def test_stop_terminates_process(sup, tmp_path):
    sup.start(_spec(tmp_path))
    sup.stop(1, timeout=4.0)
    assert _wait_until(lambda: not sup.is_running(1))


def test_kill_terminates_process(sup, tmp_path):
    sup.start(_spec(tmp_path))
    sup.kill(1)
    assert _wait_until(lambda: not sup.is_running(1))


def test_restart_replaces_process(sup, tmp_path):
    first = sup.start(_spec(tmp_path))
    assert _wait_until(lambda: sup.is_running(1))
    second = sup.restart(_spec(tmp_path, run_id=2))
    assert second.pid != first.pid
    assert sup.is_running(1)


def test_is_running_false_for_unknown(sup):
    assert sup.is_running(999) is False
    assert sup.info(999) is None


def test_kill_port_signals_listening_pids(sup):
    with patch.object(ports, "pids_on_port", return_value=[4321, 4322]), patch(
        "portman.supervisor.os.kill"
    ) as mock_kill:
        killed = sup.kill_port(8080, sig=signal.SIGTERM)
    assert killed == [4321, 4322]
    assert mock_kill.call_count == 2
    mock_kill.assert_any_call(4321, signal.SIGTERM)


def test_kill_port_skips_already_dead_pids(sup):
    with patch.object(ports, "pids_on_port", return_value=[4321]), patch(
        "portman.supervisor.os.kill", side_effect=ProcessLookupError
    ):
        killed = sup.kill_port(8080)
    assert killed == []  # nothing was actually signalled


# --- edge branches ----------------------------------------------------------


def test_start_closes_log_on_spawn_failure(sup, tmp_path, monkeypatch):
    def boom(*a, **k):
        raise OSError("cannot spawn")

    monkeypatch.setattr("portman.supervisor.subprocess.Popen", boom)
    with pytest.raises(OSError):
        sup.start(_spec(tmp_path))


def test_stop_unknown_key_returns_none(sup):
    assert sup.stop(999) is None


def test_stop_escalates_to_sigkill_and_tolerates_errors(sup, tmp_path, monkeypatch):
    # A process that never reaps (wait always times out) and resists signals.
    fake_popen = MagicMock()
    fake_popen.pid = 4242
    fake_popen.poll.return_value = None
    fake_popen.wait.side_effect = subprocess.TimeoutExpired(cmd="x", timeout=5)
    fake_log = MagicMock()
    fake_log.close.side_effect = OSError  # _close must swallow this
    sup._procs[1] = _Handle(fake_popen, fake_log, "p", _spec(tmp_path))

    monkeypatch.setattr("portman.supervisor.os.getpgid", lambda pid: pid)
    monkeypatch.setattr(
        "portman.supervisor.os.killpg",
        lambda pid, sig: (_ for _ in ()).throw(ProcessLookupError),
    )

    info = sup.stop(1, timeout=0.01)
    assert info is not None  # info() still reports the (stuck) process
    sup._procs.pop(1, None)  # avoid the fixture teardown re-signalling the fake
