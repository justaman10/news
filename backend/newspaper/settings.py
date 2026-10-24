"""Static configuration (config/sources.yaml) and the reader's saved preferences."""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

BACKEND_DIR = Path(__file__).resolve().parent.parent
Depth = Literal["headlines", "brief", "deep"]


class AISettings(BaseModel):
    model: str = "claude-opus-5-5"
    effort: Literal["low", "medium", "high"] = "low"
    deep_dives: int = 10
    web_search: bool = True
    web_search_max_uses: int = 3
    daily_budget_usd: float = 4.0
    quiz_questions: int = 5


class Category(BaseModel):
    slug: str
    name: str
    emoji: str = ""
    focus: str = ""
    feeds: list[str] = Field(default_factory=list)
    derived_from: list[str] = Field(default_factory=list)
    local_keywords: list[str] = Field(default_factory=list)


class FootballData(BaseModel):
    enabled: bool = True
    competitions: list[str] = Field(default_factory=lambda: ["PL", "BL1", "CL"])


class EspnLeague(BaseModel):
    sport: str
    league: str
    label: str


class Espn(BaseModel):
    enabled: bool = True
    leagues: list[EspnLeague] = Field(default_factory=list)


class Toggle(BaseModel):
    enabled: bool = True


class SportsSettings(BaseModel):
    football_data: FootballData = Field(default_factory=FootballData)
    f1: Toggle = Field(default_factory=Toggle)
    espn: Espn = Field(default_factory=Espn)
    cricket: Toggle = Field(default_factory=Toggle)


class Settings(BaseModel):
    timezone: str = "Europe/Berlin"
    edition_hour: int = 6
    ai: AISettings = Field(default_factory=AISettings)
    lookback_hours: int = 30
    categories: list[Category]
    default_prefs: dict = Field(default_factory=dict)
    sports: SportsSettings = Field(default_factory=SportsSettings)

    def category(self, slug: str) -> Category:
        return next(c for c in self.categories if c.slug == slug)


def load_settings(path: str | Path | None = None) -> Settings:
    path = Path(path or os.environ.get("NEWSPAPER_CONFIG") or BACKEND_DIR / "config" / "sources.yaml")
    with open(path, encoding="utf-8") as f:
        return Settings.model_validate(yaml.safe_load(f))


def merge_prefs(defaults: dict, saved: dict | None) -> dict:
    """Saved preferences override defaults key by key (one level deep for categories)."""
    prefs = copy.deepcopy(defaults)
    for key, value in (saved or {}).items():
        if key == "categories" and isinstance(value, dict):
            cats = prefs.setdefault("categories", {})
            for slug, cfg in value.items():
                if isinstance(cfg, dict):
                    cats[slug] = {**cats.get(slug, {}), **cfg}
        elif value not in (None, ""):
            prefs[key] = value
    return prefs


def category_pref(prefs: dict, slug: str) -> tuple[int, str]:
    cfg = prefs.get("categories", {}).get(slug, {})
    weight = int(cfg.get("weight", 2))
    depth = cfg.get("depth", "brief")
    if depth not in ("headlines", "brief", "deep"):
        depth = "brief"
    return max(0, min(3, weight)), depth
