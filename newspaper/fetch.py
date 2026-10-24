"""Pulls RSS/Atom feeds and turns them into ranked candidate articles per topic."""

from __future__ import annotations

import calendar
import html
import logging
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import feedparser

from .config import Topic

log = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (compatible; DailyBriefBot/1.0; +https://github.com/)"
SNIPPET_CHARS = 700


@dataclass
class Article:
    id: str
    title: str
    link: str
    source: str
    published: datetime | None
    snippet: str
    score: float = 0.0


def clean_text(raw: str) -> str:
    text = re.sub(r"<(script|style)\b.*?</\1>", " ", raw or "", flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", title.lower()).strip()


def _download(url: str, timeout: int = 20) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def fetch_feed(url: str) -> list[Article]:
    try:
        parsed = feedparser.parse(_download(url))
    except Exception as exc:  # network errors, timeouts, bad TLS, ...
        log.warning("Could not fetch %s: %s", url, exc)
        return []

    source = clean_text(parsed.feed.get("title", "")) or urlparse(url).netloc
    articles = []
    for entry in parsed.entries:
        title = clean_text(entry.get("title", ""))
        link = entry.get("link", "")
        if not title or not link:
            continue
        stamp = entry.get("published_parsed") or entry.get("updated_parsed")
        published = (
            datetime.fromtimestamp(calendar.timegm(stamp), tz=timezone.utc) if stamp else None
        )
        snippet = clean_text(entry.get("summary", "") or entry.get("description", ""))
        articles.append(
            Article(
                id="",
                title=title,
                link=link,
                source=source,
                published=published,
                snippet=snippet[:SNIPPET_CHARS],
            )
        )
    return articles


def _mentions(text: str, words: list[str]) -> int:
    lowered = text.lower()
    return sum(1 for w in words if w.lower() in lowered)


def gather_candidates(
    topic: Topic,
    now: datetime,
    lookback_hours: int,
    seen_links: set[str],
    seen_titles: set[str],
) -> list[Article]:
    """Fetches the topic's feeds and returns the best candidates, best first.

    `seen_links` / `seen_titles` are shared across topics (and pre-filled with
    recent editions) so a story only ever appears once.
    """
    with ThreadPoolExecutor(max_workers=8) as pool:
        per_feed = list(pool.map(fetch_feed, topic.feeds))

    cutoff = now - timedelta(hours=lookback_hours)
    candidates: list[Article] = []
    for feed_articles in per_feed:
        for rank, art in enumerate(feed_articles):
            key = normalize_title(art.title)
            if art.link in seen_links or key in seen_titles:
                continue
            if art.published and art.published < cutoff:
                continue
            text = f"{art.title} {art.snippet}"
            if topic.exclude and _mentions(text, topic.exclude):
                continue
            # Feeds list their most important items first; reward that, recency
            # and the reader's keywords.
            art.score = 2.0 * _mentions(text, topic.keywords) + max(0.0, 3.0 - rank * 0.2)
            if art.published:
                age_h = (now - art.published).total_seconds() / 3600
                art.score += max(0.0, 2.0 - age_h / 12)
            seen_titles.add(key)
            candidates.append(art)

    candidates.sort(key=lambda a: a.score, reverse=True)
    # Give the editor a wider pool than it needs so it can choose.
    chosen = candidates[: max(topic.max_stories * 3, 8)]
    # Titles of candidates that were not chosen go back to the pool for other topics.
    for art in candidates[len(chosen):]:
        seen_titles.discard(normalize_title(art.title))
    for i, art in enumerate(chosen):
        art.id = f"{topic.slug}-{i}"
        seen_links.add(art.link)
    log.info("%s: %d candidates from %d feeds", topic.name, len(chosen), len(topic.feeds))
    return chosen
