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
