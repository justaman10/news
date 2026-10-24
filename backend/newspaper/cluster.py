"""Groups articles about the same development, across outlets and categories.

How many independent outlets cover a story is the strongest signal of
significance we have, and clustering is also how duplicates disappear.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

STOPWORDS = set("""
a an the and or but if then of in on at to for from by with without as is are was were be been being
it its this that these those he she they them his her their we our you your i me my not no yes do does
did has have had will would can could should may might must over under after before about into out up
down off new news says say said report reports amid live update updates latest how why what who when
where which while than more most less least very just also first last top big video watch photos
year years day days week weeks today yesterday tomorrow vs via per one two three
""".split())


def tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9äöüß]+", text.lower())
    out = set()
    for w in words:
        if len(w) < 3 or w in STOPWORDS:
            continue
        if len(w) > 4 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        out.add(w)
    return out


@dataclass
class Cluster:
    id: str
    articles: list[dict] = field(default_factory=list)
    title_tokens: set[str] = field(default_factory=set)
    score: float = 0.0

    @property
    def sources(self) -> set[str]:
        return {a["source"] for a in self.articles}

    @property
    def categories(self) -> set[str]:
        return {a["category"] for a in self.articles}

    @property
    def latest(self) -> datetime | None:
        times = [_when(a) for a in self.articles]
        return max(times) if times else None

    @property
    def image(self) -> tuple[str | None, str | None]:
        for a in self.articles:
            if a.get("image_url"):
                return a["image_url"], a["source"]
        return None, None

    def home_category(self, weights: dict[str, int]) -> str:
        counts: dict[str, int] = {}
        for a in self.articles:
            counts[a["category"]] = counts.get(a["category"], 0) + 1
        return max(counts, key=lambda c: (counts[c], weights.get(c, 0)))

    def unique_articles(self) -> list[dict]:
        """One article per URL (the same link can sit in several categories)."""
        seen, out = set(), []
        for a in sorted(self.articles, key=_when, reverse=True):
            if a["url"] not in seen:
                seen.add(a["url"])
                out.append(a)
        return out


def _when(a: dict) -> datetime:
    t = a.get("published_at") or a.get("fetched_at")
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def similar(a: set[str], b: set[str]) -> bool:
    if not a or not b:
        return False
    shared = len(a & b)
    overlap = shared / min(len(a), len(b))
    jaccard = shared / len(a | b)
    return (shared >= 3 and overlap >= 0.6) or (shared >= 2 and jaccard >= 0.5)


def cluster_articles(articles: list[dict]) -> list[Cluster]:
    clusters: list[Cluster] = []
    by_url: dict[str, Cluster] = {}
    for art in sorted(articles, key=_when, reverse=True):
        if art["url"] in by_url:                  # same link, other category
            by_url[art["url"]].articles.append(art)
            continue
        toks = tokens(art["title"])
        home = next((c for c in clusters if similar(toks, c.title_tokens)), None)
        if home is None:
            home = Cluster(id=f"c{len(clusters) + 1}")
            clusters.append(home)
        home.articles.append(art)
        home.title_tokens |= toks if len(home.articles) <= 3 else set()
        by_url[art["url"]] = home
    return clusters


def score_clusters(clusters: list[Cluster], now: datetime, boost_terms: list[str],
                   local_terms: list[str]) -> None:
    boosts = [t.lower() for t in boost_terms if t]
    local = [t.lower() for t in local_terms if t]
    for c in clusters:
        n_sources = len(c.sources)
        age_h = max(0.0, (now - c.latest).total_seconds() / 3600) if c.latest else 24
        text = " ".join(a["title"] + " " + a.get("snippet", "") for a in c.articles).lower()
        c.score = (
            3.0 * math.log2(1 + n_sources)          # independent coverage
            + max(0.0, 2.0 - age_h / 12)             # freshness
            + 0.8 * sum(1 for t in boosts if t in text)
            + 2.0 * sum(1 for t in local if t in text)
            + (0.5 if any(a.get("image_url") for a in c.articles) else 0)
        )
