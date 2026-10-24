"""Assembles one edition: fetch → edit → save."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from .config import Config
from .editor import edit_section, make_client, write_front_page
from .fetch import gather_candidates, normalize_title
from .models import Edition

log = logging.getLogger(__name__)


def load_editions(data_dir: Path) -> list[Edition]:
    """All saved editions, newest first."""
    editions = [
        Edition.model_validate_json(p.read_text(encoding="utf-8"))
        for p in data_dir.glob("*.json")
    ]
    return sorted(editions, key=lambda e: e.date, reverse=True)


def build_edition(config: Config, date: str, data_dir: Path, use_ai: bool = True) -> Edition:
    now = datetime.now(timezone.utc)

    # Don't repeat what recent editions already covered.
    recent = [e for e in load_editions(data_dir) if e.date < date][: config.paper.avoid_repeats_days]
    seen_links = set().union(*(e.links() for e in recent)) if recent else set()
    seen_titles = {
        normalize_title(s.headline) for e in recent for sec in e.sections for s in sec.stories
    }

    # Sequential so earlier sections claim shared stories first.
    candidates = [
        gather_candidates(t, now, config.paper.lookback_hours, seen_links, seen_titles)
        for t in config.topics
    ]

    client = make_client() if (use_ai and config.ai.enabled) else None
    with ThreadPoolExecutor(max_workers=4) as pool:
        sections = list(
            pool.map(
                lambda tc: edit_section(client, config.ai, config.reader, tc[0], tc[1]),
                zip(config.topics, candidates),
            )
        )
    lead_note, quiz = write_front_page(client, config.ai, config.reader, sections)

    return Edition(
        date=date,
        title=config.paper.title,
        tagline=config.paper.tagline,
        reader_name=config.reader.name,
        generated_at=now.isoformat(timespec="seconds"),
        ai=client is not None and any(s.concept for s in sections),
        lead_note=lead_note,
        sections=sections,
        quiz=quiz,
    )


def save_edition(edition: Edition, data_dir: Path) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / f"{edition.date}.json"
    path.write_text(edition.model_dump_json(indent=2), encoding="utf-8")
    return path
