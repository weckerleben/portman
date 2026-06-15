"""Pydantic request models — validation at the API boundary."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ServiceIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    command: str = Field(min_length=1)
    description: str = ""
    cwd: str = ""
    env: dict[str, str] = Field(default_factory=dict)
    port: int | None = Field(default=None, ge=1, le=65535)
    auto_port: bool = False
    auto_restart: bool = False


class ReservationIn(BaseModel):
    port: int | None = Field(default=None, ge=1, le=65535)
    purpose: str = ""
    auto: bool = False
