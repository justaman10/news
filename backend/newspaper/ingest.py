"""Pulls RSS/Atom feeds into public.articles, politely (conditional GET, timeouts)."""

from __future__ import annotations

import calendar
import html
import logging
import re
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import feedparser
import psycopg

from .settings import Settings

log = logging.getLogger(__name__)

USER_AGENT = "PersonalNewspaperBot/2.0 (+https://github.com/justaman10/news; personal, non-commercial)"
SNIPPET_CHARS = 600
MAX_AGE = timedelta(days=3)


@dataclass
class FeedItem:
    url: str
    title: str
    snippet: str
    source: str
    image_url: str | None
    published_at: datetime | None


@dataclass
class FeedResult:
    feed_url: str
    category: str
    items: list[FeedItem] = field(default_factory=list)
    etag: str | None = None
    last_modified: str | None = None
    not_modified: bool = False
    error: str | None = None


def clean_text(raw: str) -> str:
    text = re.sub(r"<(script|style)\b.*?</\1>", " ", raw or "", flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _https(url: str | None) -> str | None:
    if not url:
        return None
    url = html.unescape(url.strip())
    if url.startswith("//"):
        url = "https:" + url
    if url.startswith("http://"):
        url = "https://" + url[len("http://"):]
    return url if url.startswith("https://") else None


def find_image(entry) -> str | None:
    """The image the publisher attached to this item in its own feed, if any."""
    for key in ("media_content", "media_thumbnail"):
        for media in entry.get(key) or []:
            kind = (media.get("medium") or media.get("type") or "image").lower()
            if "image" in kind and media.get("url"):
                return _https(media["url"])
    for link in entry.get("links") or []:
        if link.get("rel") == "enclosure" and (link.get("type") or "").startswith("image"):
            return _https(link.get("href"))
    for enc in entry.get("enclosures") or []:
        if (enc.get("type") or "").startswith("image"):
            return _https(enc.get("href") or enc.get("url"))
    body = entry.get("summary", "") + " ".join(c.get("value", "") for c in entry.get("content") or [])
    match = re.search(r"<img[^>]+src=[\"']([^\"']+)", body)
    return _https(match.group(1)) if match else None


def parse_feed(content: bytes, feed_url: str, now: datetime) -> list[FeedItem]:
    parsed = feedparser.parse(content)
    source = clean_text(parsed.feed.get("title", "")) or urlparse(feed_url).netloc
    source = re.sub(r"\s*[-|:–]\s*(RSS|Top Stories|Latest|News Feed).*$", "", source, flags=re.I) or source
    items = []
    for entry in parsed.entries:
        title = clean_text(entry.get("title", ""))
        link = (entry.get("link") or "").strip()
        if not title or not link.startswith("http"):
            continue
        stamp = entry.get("published_parsed") or entry.get("updated_parsed")
        published = datetime.fromtimestamp(calendar.timegm(stamp), tz=timezone.utc) if stamp else None
        if published and (published < now - MAX_AGE or published > now + timedelta(hours=2)):
            continue
        snippet = clean_text(entry.get("summary", "") or entry.get("description", ""))
        if snippet.lower().startswith(title.lower()):
            snippet = snippet[len(title):].strip(" -–:")
        if len(snippet) > SNIPPET_CHARS:
            snippet = snippet[:SNIPPET_CHARS].rsplit(" ", 1)[0] + "…"
        items.append(FeedItem(link, title, snippet, source, find_image(entry), published))
    return items


def fetch_feed(feed_url: str, category: str, etag: str | None, last_modified: str | None,
               now: datetime) -> FeedResult:
    result = FeedResult(feed_url, category)
    headers = {"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*"}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    try:
        req = urllib.request.Request(feed_url, headers=headers)
        with urllib.request.urlopen(req, timeout=20) as resp:
            content = resp.read()
            result.etag = resp.headers.get("ETag")
            result.last_modified = resp.headers.get("Last-Modified")
        result.items = parse_feed(content, feed_url, now)
        if not result.items:
            result.error = "feed returned no usable items"
    except urllib.error.HTTPError as exc:
        if exc.code == 304:
            result.not_modified = True
            result.etag, result.last_modified = etag, last_modified
        else:
            result.error = f"HTTP {exc.code}"
    except Exception as exc:  # DNS, TLS, timeouts, malformed responses
        result.error = f"{type(exc).__name__}: {exc}"[:300]
    return result


def all_feeds(settings: Settings) -> list[tuple[str, str]]:
    return [(url, c.slug) for c in settings.categories for url in c.feeds]


def fetch_all(feeds: list[tuple[str, str]], state: dict[str, dict], now: datetime) -> list[FeedResult]:
    def one(feed):
        url, category = feed
        st = state.get(url, {})
        return fetch_feed(url, category, st.get("etag"), st.get("last_modified"), now)

    with ThreadPoolExecutor(max_workers=12) as pool:
        return list(pool.map(one, feeds))


def ingest(conn: psycopg.Connection, settings: Settings, now: datetime | None = None) -> dict:
    """Fetches every feed and stores new items. Returns counts for the job summary."""
    now = now or datetime.now(timezone.utc)
    state = {r["feed_url"]: r for r in conn.execute("select * from public.feed_state")}
    results = fetch_all(all_feeds(settings), state, now)

    new_items, failed = 0, []
    with conn.transaction():
        for res in results:
            for item in res.items:
                cur = conn.execute(
                    """insert into public.articles
                         (url, title, snippet, source, feed_url, category, image_url, published_at)
                       values (%s, %s, %s, %s, %s, %s, %s, %s)
                       on conflict (url, category) do update
                         set image_url = coalesce(public.articles.image_url, excluded.image_url)
                       returning (xmax = 0) as inserted""",
                    (item.url, item.title, item.snippet, item.source, res.feed_url,
                     res.category, item.image_url, item.published_at),
                )
                new_items += int(cur.fetchone()["inserted"])
            ok = res.error is None
            if not ok:
                failed.append(f"{res.feed_url}: {res.error}")
            conn.execute(
                """insert into public.feed_state
                     (feed_url, category, etag, last_modified, last_ok, last_error, last_count, updated_at)
                   values (%s, %s, %s, %s, case when %s then now() end, %s, %s, now())
                   on conflict (feed_url) do update set
                     category = excluded.category,
                     etag = coalesce(excluded.etag, public.feed_state.etag),
                     last_modified = coalesce(excluded.last_modified, public.feed_state.last_modified),
                     last_ok = coalesce(excluded.last_ok, public.feed_state.last_ok),
                     last_error = excluded.last_error,
                     last_count = case when %s then public.feed_state.last_count else excluded.last_count end,
                     updated_at = now()""",
                (res.feed_url, res.category, res.etag, res.last_modified, ok, res.error,
                 len(res.items), res.not_modified),
            )
    for line in failed:
        log.warning("Feed problem — %s", line)
    return {"feeds": len(results), "feeds_failed": len(failed), "new_articles": new_items,
            "failed_feeds": failed[:30]}
