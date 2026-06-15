"""Tests for the optional AI enrichment layer (model call is mocked)."""

from __future__ import annotations

import pytest

from portman import ai


def _fixture_project(tmp_path):
    (tmp_path / "package.json").write_text('{"scripts": {"start": "node server.js"}}')
    return tmp_path


def test_enrich_parses_model_json(tmp_path, monkeypatch):
    payload = """[
      {"name": "web", "command": "node server.js", "port": 3000,
       "description": "Express server", "cwd": ""}
    ]"""
    monkeypatch.setattr(ai, "_call_model", lambda prompt, api_key: payload)

    services = ai.enrich_services(_fixture_project(tmp_path), [], "sk-ant-test")
    assert len(services) == 1
    svc = services[0]
    assert svc.name == "web"
    assert svc.port == 3000
    assert svc.note  # marks the entry as AI-suggested


def test_enrich_strips_markdown_fences(tmp_path, monkeypatch):
    fenced = '```json\n[{"name": "api", "command": "uvicorn app:app", "port": "auto"}]\n```'
    monkeypatch.setattr(ai, "_call_model", lambda prompt, api_key: fenced)

    services = ai.enrich_services(_fixture_project(tmp_path), [], "sk-ant-test")
    assert services[0].name == "api"
    assert services[0].auto_port is True


def test_enrich_raises_on_garbage(tmp_path, monkeypatch):
    monkeypatch.setattr(ai, "_call_model", lambda prompt, api_key: "not json at all")
    with pytest.raises(ai.AIError):
        ai.enrich_services(_fixture_project(tmp_path), [], "sk-ant-test")
