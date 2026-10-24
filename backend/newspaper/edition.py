"""Builds and publishes the daily edition."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import psycopg
from psycopg.types.json import Jsonb

from . import editor
from .cluster import Cluster, cluster_articles, score_clusters, similar, tokens
from .db import JobRun, owner_prefs
from .settings import Settings, category_pref, merge_prefs
from .sports import recent_results_text

log = logging.getLogger(__name__)

STORIES_FOR_WEIGHT = {0: 1, 1: 3, 2: 4, 3: 6}
POOL_SIZE = 18
AVOID_REPEATS_EDITIONS = 2


def edition_date_now(settings: Settings, now: datetime | None = None) -> tuple[date, bool]:
    """Today's date in the paper's timezone, and whether publication time has passed."""
    local = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo(settings.timezone))
    return local.date(), local.hour >= settings.edition_hour


def _recently_used_urls(conn: psycopg.Connection, before: date) -> set[str]:
    rows = conn.execute(
        """select s.sources from public.stories s join public.editions e on e.id = s.edition_id
           where e.status = 'published' and e.edition_date < %s
             and e.edition_date >= %s::date - %s""",
        (before, before, AVOID_REPEATS_EDITIONS),
    )
    return {src["url"] for r in rows for src in r["sources"]}


def _story_from_cluster(cluster: Cluster, category: str, depth: str, rank: int,
                        draft: dict | None = None) -> dict:
    arts = cluster.unique_articles()
    image, image_source = cluster.image
    draft = draft or {}
    return {
        "category": category,
        "rank": rank,
        "depth": depth,
        "headline": draft.get("headline") or arts[0]["title"],
        "summary": draft.get("summary") if draft else (arts[0].get("snippet") or ""),
        "why_it_matters": draft.get("why_it_matters", ""),
        "background": draft.get("background", ""),
        "perspectives": draft.get("perspectives", []),
        "implications": draft.get("implications", ""),
        "key_terms": draft.get("key_terms", []),
        "interview": draft.get("interview", []),
        "talking_point": draft.get("talking_point", ""),
        "importance": max(1, min(10, int(draft.get("importance") or 5))),
        "image_url": image,
        "image_source": image_source,
        "primary_url": arts[0]["url"],
        "sources": [
            {"title": a["title"], "url": a["url"], "source": a["source"], "snippet": a.get("snippet", ""),
             "published_at": a["published_at"].isoformat() if a.get("published_at") else None}
            for a in arts[:8]
        ],
        "published_at": cluster.latest,
        "cluster": cluster,
    }


def _plain_section(pool: list[Cluster], category: str, depth: str, n: int) -> dict:
    return {
        "intro": "",
        "concept": None,
        "stories": [_story_from_cluster(c, category, depth, i) for i, c in enumerate(pool[:n])],
    }


def _ai_section(client, settings, budget, prefs, cat, depth, n, pool, extra) -> dict:
    data = editor.curate_section(client, settings.ai, budget, prefs, cat, depth, n, pool, extra)
    by_id = {c.id: c for c in pool}
    stories = []
    for draft in data["stories"]:
        cluster = by_id.get(draft["cluster_id"])
        if cluster and all(s["cluster"] is not cluster for s in stories):
            stories.append(_story_from_cluster(cluster, cat.slug, depth, len(stories), draft))
    return {"intro": data["intro"], "concept": data["concept"], "stories": stories[:n]}


def build_edition(conn: psycopg.Connection, settings: Settings, run: JobRun, *,
                  edition_date: date, force: bool = False, use_ai: bool = True,
                  owner_email: str | None = None, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    existing = conn.execute(
        "select id, number, status from public.editions where edition_date = %s", (edition_date,)
    ).fetchone()
    if existing and existing["status"] == "published" and not force:
        run.note(skipped=f"edition {edition_date} already published")
        return {"skipped": True}

    prefs = merge_prefs(settings.default_prefs, owner_prefs(conn, owner_email))
    weights = {c.slug: category_pref(prefs, c.slug)[0] for c in settings.categories}

    used = _recently_used_urls(conn, edition_date)
    articles = [
        a for a in conn.execute(
            "select * from public.articles where coalesce(published_at, fetched_at) > %s",
            (now - timedelta(hours=settings.lookback_hours),),
        )
        if a["url"] not in used
    ]
    clusters = cluster_articles(articles)
    boost = [*prefs.get("countries", []), *prefs.get("industries", []), *prefs.get("teams", []),
             *prefs.get("leagues", []), *prefs.get("sports", [])]
    local = [k for c in settings.categories for k in c.local_keywords]
    score_clusters(clusters, now, boost, local)
    clusters.sort(key=lambda c: c.score, reverse=True)
    run.note(articles=len(articles), clusters=len(clusters))

    pools: dict[str, list[Cluster]] = {}
    for cat in settings.categories:
        if cat.derived_from:
            wanted = set(cat.derived_from) | {cat.slug}
            pool = [c for c in clusters if c.categories & wanted]
        else:
            pool = [c for c in clusters if c.home_category(weights) == cat.slug]
        pools[cat.slug] = pool[:POOL_SIZE]

    client = editor.make_client(settings.ai) if use_ai else None
    budget = editor.Budget(settings.ai.daily_budget_usd)
    sports_context = recent_results_text(conn)

    def make_section(cat):
        weight, depth = category_pref(prefs, cat.slug)
        if cat.slug == "interview":
            depth = "deep"
        n = STORIES_FOR_WEIGHT[weight]
        pool = pools[cat.slug]
        if not pool:
            return cat.slug, {"intro": "", "concept": None, "stories": []}, None
        if client is None:
            return cat.slug, _plain_section(pool, cat.slug, depth, n if weight else 0), None
        extra = ""
        if cat.slug == "sports" and sports_context:
            extra = ("Verified results from sports data feeds (use these exact scores; you may "
                     "write a story from them, citing the relevant cluster):\n" + sports_context)
        try:
            return cat.slug, _ai_section(client, settings, budget, prefs, cat, depth, n, pool, extra), None
        except (editor.EditorError, KeyError, TypeError, ValueError) as exc:
            return cat.slug, _plain_section(pool, cat.slug, depth, n if weight else 0), f"{cat.slug}: {exc}"

    with ThreadPoolExecutor(max_workers=5) as pool_exec:
        results = list(pool_exec.map(make_section, settings.categories))
    sections = {}
    for slug, section, problem in results:
        sections[slug] = section
        if problem:
            run.warn(f"AI editing failed for {problem}; used plain digest")

    # The same development must not run in two news sections (Interview
    # Intelligence is a deliberate second look, so it may overlap).
    order = sorted((c for c in settings.categories if not c.derived_from),
                   key=lambda c: -weights.get(c.slug, 0))
    claimed: set[int] = set()
    for cat in order:
        kept = [s for s in sections[cat.slug]["stories"] if id(s["cluster"]) not in claimed]
        claimed |= {id(s["cluster"]) for s in kept}
        for i, s in enumerate(kept):
            s["rank"] = i
        sections[cat.slug]["stories"] = kept

    if not any(sec["stories"] for sec in sections.values()):
        raise RuntimeError("No stories available — are the feeds reachable? Edition not published.")

    # ── write draft ──
    with conn.transaction():
        if existing:
            edition_id, number = existing["id"], existing["number"]
            conn.execute("delete from public.stories where edition_id = %s", (edition_id,))
            conn.execute("delete from public.sections where edition_id = %s", (edition_id,))
            conn.execute("update public.editions set status = 'draft' where id = %s", (edition_id,))
        else:
            number = conn.execute(
                "select count(*) + 1 as n from public.editions where status = 'published'"
            ).fetchone()["n"]
            edition_id = conn.execute(
                "insert into public.editions (edition_date, number) values (%s, %s) returning id",
                (edition_date, number),
            ).fetchone()["id"]
        all_stories = []
        for cat in settings.categories:
            sec = sections[cat.slug]
            conn.execute(
                "insert into public.sections (edition_id, category, intro, concept) values (%s, %s, %s, %s)",
                (edition_id, cat.slug, sec["intro"], Jsonb(sec["concept"]) if sec["concept"] else None),
            )
            for s in sec["stories"]:
                s["id"] = conn.execute(
                    """insert into public.stories
                         (edition_id, category, rank, depth, headline, summary, why_it_matters,
                          background, perspectives, implications, key_terms, interview,
                          talking_point, importance, image_url, image_source, primary_url,
                          sources, published_at)
                       values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       returning id""",
                    (edition_id, s["category"], s["rank"], s["depth"], s["headline"], s["summary"],
                     s["why_it_matters"], s["background"], Jsonb(s["perspectives"]),
                     s["implications"], Jsonb(s["key_terms"]), Jsonb(s["interview"]),
                     s["talking_point"], s["importance"], s["image_url"], s["image_source"],
                     s["primary_url"], Jsonb(s["sources"]), s["published_at"]),
                ).fetchone()["id"]
                all_stories.append(s)

    # ── front page ──
    news_stories = [s for s in all_stories if s["category"] != "interview"]
    by_id = {s["id"]: s for s in news_stories}
    lead_note, quiz, front = "", [], []
    if client is not None:
        try:
            fp = editor.front_page(client, settings.ai, budget, prefs, news_stories)
            ids = [fp["lead_story_id"], *fp["top_story_ids"]]
            front = list(dict.fromkeys(i for i in ids if i in by_id))
            lead_note = fp["lead_note"]
            quiz = [q for q in fp["quiz"]
                    if len(q["options"]) >= 2 and 0 <= q["answer_index"] < len(q["options"])]
        except (editor.EditorError, KeyError, TypeError) as exc:
            run.warn(f"Front page AI failed: {exc}")
    if not front:
        ranked = sorted(news_stories, key=lambda s: (s["importance"], s["cluster"].score), reverse=True)
        front = [s["id"] for s in ranked]
    # Prefer a lead with a picture when the top two are close.
    if len(front) > 1 and not by_id[front[0]]["image_url"] and by_id[front[1]]["image_url"] \
            and by_id[front[1]]["importance"] >= by_id[front[0]]["importance"]:
        front[0], front[1] = front[1], front[0]
    front = front[:12]

    # ── deep dives for the front page ──
    deep_dives = 0
    if client is not None and settings.ai.deep_dives > 0:
        targets = [by_id[i] for i in front[: settings.ai.deep_dives]]

        def dive(story):
            if budget.exhausted:
                return story, None, "budget reached"
            try:
                return story, editor.deep_dive(client, settings.ai, budget, prefs, story), None
            except (editor.EditorError, KeyError, TypeError) as exc:
                return story, None, str(exc)

        with ThreadPoolExecutor(max_workers=4) as pool_exec:
            for story, result, problem in pool_exec.map(dive, targets):
                if result:
                    conn.execute("update public.stories set deep_dive = %s where id = %s",
                                 (Jsonb(result), story["id"]))
                    deep_dives += 1
                elif problem:
                    run.warn(f"Deep dive skipped for story {story['id']}: {problem}")

    stats = {
        "ai_provider": "none" if client is None else ("gemini" if isinstance(client, editor.GeminiClient) else "claude"),
        "stories": len(all_stories),
        "sections": {slug: len(sec["stories"]) for slug, sec in sections.items()},
        "deep_dives": deep_dives,
        "sources": len({src["source"] for s in all_stories for src in s["sources"]}),
        "ai": budget.as_dict(),
    }
    conn.execute(
        """update public.editions set status = 'published', published_at = now(), ai = %s,
             lead_note = %s, quiz = %s, front_page = %s, stats = %s where id = %s""",
        (client is not None and budget.calls > 0, lead_note, Jsonb(quiz), front, Jsonb(stats), edition_id),
    )
    run.note(edition=str(edition_date), **stats)
    return {"edition_id": edition_id, **stats}


def attach_story_updates(conn: psycopg.Connection, settings: Settings) -> int:
    """Links newer reporting to stories in the latest edition (developing stories)."""
    edition = conn.execute(
        "select id, published_at from public.editions where status = 'published' "
        "order by edition_date desc limit 1"
    ).fetchone()
    if not edition:
        return 0
    stories = conn.execute(
        "select id, category, sources from public.stories where edition_id = %s", (edition["id"],)
    ).fetchall()
    fresh = conn.execute(
        "select id, url, title, category from public.articles where fetched_at > %s",
        (edition["published_at"],),
    ).fetchall()
    added = 0
    for story in stories:
        known = {s["url"] for s in story["sources"]}
        story_tokens = [tokens(s["title"]) for s in story["sources"]]
        for art in fresh:
            if art["url"] in known:
                continue
            art_tokens = tokens(art["title"])
            if any(similar(art_tokens, t) for t in story_tokens):
                cur = conn.execute(
                    "insert into public.story_updates (story_id, article_id) values (%s, %s) "
                    "on conflict do nothing",
                    (story["id"], art["id"]),
                )
                added += cur.rowcount
                known.add(art["url"])
    return added
