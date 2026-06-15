"""Optional AI enrichment for ``portman init``.

When static heuristics miss something, ``init --ai`` asks a small Claude model
to read a snapshot of the project and suggest services. The ``anthropic`` SDK is
an optional dependency, imported lazily so the rest of portman never needs it.

The model call is isolated in :func:`_call_model` so tests can stub it without
touching the network.
"""

from __future__ import annotations

import json
from pathlib import Path

from .detect import DetectedService

MODEL = "claude-haiku-4-5"
_MAX_FILE_BYTES = 4000
_SNAPSHOT_FILES = (
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "docker-compose.yml",
    "compose.yaml",
    "Procfile",
    "Makefile",
    "go.mod",
    "Cargo.toml",
)

_SYSTEM = (
    "You analyze a software project and infer the long-running services a "
    "developer starts locally (dev servers, APIs, workers). Reply with ONLY a "
    "JSON array. Each item: {\"name\": str, \"command\": str, \"port\": int or "
    '"auto", "description": str, "cwd": str}. Use $PORT in commands where the '
    "service accepts a port. No prose, no markdown fences."
)


class AIError(Exception):
    """Raised when the model is unavailable or returns an unusable response."""


def enrich_services(root: Path, existing: list[DetectedService], api_key: str) -> list[DetectedService]:
    """Ask the model for services, returning parsed :class:`DetectedService`."""
    prompt = _build_prompt(Path(root), existing)
    raw = _call_model(prompt, api_key)
    return _parse(raw)


def _build_prompt(root: Path, existing: list[DetectedService]) -> str:
    listing = sorted(p.name + ("/" if p.is_dir() else "") for p in root.iterdir())
    parts = [f"Project directory contents:\n{', '.join(listing)}\n"]
    for name in _SNAPSHOT_FILES:
        path = root / name
        if path.is_file():
            parts.append(f"\n--- {name} ---\n{path.read_text(errors='replace')[:_MAX_FILE_BYTES]}")
    if existing:
        already = ", ".join(s.name for s in existing)
        parts.append(f"\nAlready detected (do not duplicate): {already}")
    return "\n".join(parts)


def _call_model(prompt: str, api_key: str) -> str:
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise AIError("AI features need the 'anthropic' package: pip install portman[ai]") from exc

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def _parse(raw: str) -> list[DetectedService]:
    text = _strip_fences(raw.strip())
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AIError(f"Model did not return valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise AIError("Model response was not a JSON array")

    services: list[DetectedService] = []
    for item in data:
        if not isinstance(item, dict) or not item.get("name") or not item.get("command"):
            continue
        port_value = item.get("port")
        auto_port = str(port_value).lower() == "auto"
        port = None if (port_value is None or auto_port) else int(port_value)
        services.append(
            DetectedService(
                name=str(item["name"]),
                command=str(item["command"]),
                description=str(item.get("description", "")),
                cwd=str(item.get("cwd", "")),
                port=port,
                auto_port=auto_port,
                note="suggested by AI — review before use",
            )
        )
    return services


def _strip_fences(text: str) -> str:
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    lines = lines[1:]  # drop the opening ``` (optionally with a language tag)
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()
