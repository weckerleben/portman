"""Tests for the optional AI enrichment layer (model call is mocked)."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest

from portman import ai
from portman.detect import DetectedService


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


def test_build_prompt_includes_snapshot_and_existing(tmp_path):
    (tmp_path / "package.json").write_text('{"scripts": {"dev": "vite"}}')
    prompt = ai._build_prompt(tmp_path, [DetectedService(name="web", command="x")])
    assert "package.json" in prompt
    assert "Already detected" in prompt and "web" in prompt


def test_call_model_uses_anthropic_sdk(monkeypatch):
    message = MagicMock()
    message.content = [MagicMock(text="[]")]
    fake_client = MagicMock()
    fake_client.messages.create.return_value = message
    fake_anthropic = MagicMock()
    fake_anthropic.Anthropic.return_value = fake_client
    monkeypatch.setitem(sys.modules, "anthropic", fake_anthropic)

    assert ai._call_model("a prompt", "sk-ant-test") == "[]"
    fake_anthropic.Anthropic.assert_called_once_with(api_key="sk-ant-test")


def test_parse_rejects_non_array():
    with pytest.raises(ai.AIError):
        ai._parse("{}")  # a JSON object, not the required array


def test_parse_skips_items_missing_required_fields():
    parsed = ai._parse('[{"name": "x"}, {"name": "ok", "command": "run"}]')
    assert [s.name for s in parsed] == ["ok"]  # the entry without a command is dropped
