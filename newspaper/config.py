"""Loads and validates config.yaml."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator

Depth = Literal["headlines", "brief", "deep"]


class Reader(BaseModel):
    name: str = "Reader"
    goal: str = "Stay informed and prepare for interviews."
    background: str = ""
    target_roles: list[str] = Field(default_factory=list)
    region: str = "Global"


class Paper(BaseModel):
    title: str = "The Daily Brief"
    tagline: str = ""
    timezone: str = "UTC"
    lookback_hours: int = 36
    avoid_repeats_days: int = 3


class AISettings(BaseModel):
    enabled: bool = True
    model: str = "claude-opus-5-5"
    effort: Literal["low", "medium", "high"] = "medium"
    quiz_questions: int = 5


class Topic(BaseModel):
    name: str
    slug: str = ""
    depth: Depth = "brief"
    max_stories: int = 4
    feeds: list[str]
    keywords: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)
    interview_focus: str = ""

    @model_validator(mode="after")
    def _fill_slug(self) -> "Topic":
        if not self.slug:
            self.slug = re.sub(r"[^a-z0-9]+", "-", self.name.lower()).strip("-")
        return self


class Config(BaseModel):
    reader: Reader = Field(default_factory=Reader)
    paper: Paper = Field(default_factory=Paper)
    ai: AISettings = Field(default_factory=AISettings)
    topics: list[Topic]


def load_config(path: str | Path) -> Config:
    with open(path, encoding="utf-8") as f:
        return Config.model_validate(yaml.safe_load(f))
