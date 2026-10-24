"""Renders saved editions into a static site."""

from __future__ import annotations

import json
import shutil
from datetime import date as date_cls, datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .models import Edition

PACKAGE_DIR = Path(__file__).parent
WORDS_PER_MINUTE = 220


def _long_date(value: str) -> str:
    d = date_cls.fromisoformat(value)
    return f"{d:%A}, {d.day} {d:%B %Y}"


def _short_time(value: str | None) -> str:
    if not value:
        return ""
    dt = datetime.fromisoformat(value)
    return f"{dt.day} {dt:%b} · {dt:%H:%M} UTC"


def _reading_minutes(edition: Edition) -> int:
    words = len(edition.model_dump_json().split())
    return max(1, round(words / WORDS_PER_MINUTE))


def _prep_items(editions: list[Edition]) -> list[dict]:
    """Everything worth revising, across every edition."""
    items = []
    for ed in editions:
        for sec in ed.sections:
            for story in sec.stories:
                for q in story.interview_questions:
                    items.append(dict(kind="Question", topic=sec.name, date=ed.date,
                                      prompt=q.question, answer=q.answer_hint,
                                      context=story.headline, link=story.link))
                if story.talking_point:
                    items.append(dict(kind="Talking point", topic=sec.name, date=ed.date,
                                      prompt=story.headline, answer=story.talking_point,
                                      context=story.summary, link=story.link))
                for t in story.key_terms:
                    items.append(dict(kind="Term", topic=sec.name, date=ed.date,
                                      prompt=t.term, answer=t.definition,
                                      context=story.headline, link=story.link))
            if sec.concept:
                c = sec.concept
                answer = c.explanation + (f"\n\nExample: {c.example}" if c.example else "")
                items.append(dict(kind="Concept", topic=sec.name, date=ed.date,
                                  prompt=c.name, answer=answer, context="", link=""))
                if c.interview_question:
                    items.append(dict(kind="Question", topic=sec.name, date=ed.date,
                                      prompt=c.interview_question, answer=c.answer_hint,
                                      context=f"Concept: {c.name}", link=""))
    return items


def render_site(editions: list[Edition], out_dir: Path) -> None:
    """`editions` must be sorted newest first."""
    env = Environment(
        loader=FileSystemLoader(PACKAGE_DIR / "templates"),
        autoescape=select_autoescape(["html", "j2"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["long_date"] = _long_date
    env.filters["short_time"] = _short_time

    out_dir.mkdir(parents=True, exist_ok=True)
    for asset in (PACKAGE_DIR / "static").iterdir():
        shutil.copy(asset, out_dir / asset.name)

    latest = editions[0]
    total = len(editions)
    edition_tpl = env.get_template("edition.html.j2")
    for i, ed in enumerate(editions):
        html = edition_tpl.render(
            edition=ed,
            number=total - i,
            minutes=_reading_minutes(ed),
            newer=editions[i - 1].date if i > 0 else None,
            older=editions[i + 1].date if i + 1 < total else None,
            page="today" if ed is latest else "archive",
        )
        (out_dir / f"{ed.date}.html").write_text(html, encoding="utf-8")
        if ed is latest:
            (out_dir / "index.html").write_text(html, encoding="utf-8")

    archive = env.get_template("archive.html.j2").render(
        editions=editions, title=latest.title, page="archive"
    )
    (out_dir / "archive.html").write_text(archive, encoding="utf-8")

    items = _prep_items(editions)
    prep = env.get_template("prep.html.j2").render(
        title=latest.title,
        page="prep",
        # Embedded in a <script> tag, so "</" must not appear literally.
        items_json=json.dumps(items, ensure_ascii=False).replace("</", "<\\/"),
        topics=sorted({it["topic"] for it in items}),
        kinds=["Question", "Concept", "Term", "Talking point"],
        count=len(items),
        days=total,
    )
    (out_dir / "prep.html").write_text(prep, encoding="utf-8")
