"""Tests for locating the built SPA across dev and installed layouts."""

from __future__ import annotations

from portman import app


def _make_spa(root, rel):
    path = root / rel
    path.mkdir(parents=True, exist_ok=True)
    (path / "index.html").write_text("<!doctype html>")
    return path


def test_prefers_packaged_web_dir(tmp_path):
    pkg = tmp_path / "portman"
    repo = tmp_path / "repo"
    packaged = _make_spa(pkg, "web")
    _make_spa(repo, "frontend/dist")
    assert app.resolve_spa_dir(pkg, repo) == packaged


def test_falls_back_to_repo_dist(tmp_path):
    pkg = tmp_path / "portman"
    pkg.mkdir()
    repo = tmp_path / "repo"
    dist = _make_spa(repo, "frontend/dist")
    assert app.resolve_spa_dir(pkg, repo) == dist


def test_returns_none_when_no_spa(tmp_path):
    pkg = tmp_path / "portman"
    pkg.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    assert app.resolve_spa_dir(pkg, repo) is None


def test_mounts_spa_when_present(tmp_path, monkeypatch):
    # When a built SPA exists, create_app() mounts it at "/". Patch SPA_DIR so the
    # mount runs regardless of whether the frontend was built in this environment.
    spa = _make_spa(tmp_path, "web")
    monkeypatch.setattr(app, "SPA_DIR", spa)
    built = app.create_app()
    assert any(getattr(route, "name", None) == "spa" for route in built.routes)


def test_no_spa_mount_when_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "SPA_DIR", None)
    built = app.create_app()
    assert not any(getattr(route, "name", None) == "spa" for route in built.routes)
