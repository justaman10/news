"""Command line for the backend worker.

  python -m newspaper migrate           apply database migrations
  python -m newspaper refresh           fetch feeds + sports, attach developing-story updates
  python -m newspaper daily --if-due    build today's edition if it's publication time
  python -m newspaper check-sources     test every feed and sports API (no database needed)
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, datetime, timezone

from . import db
from .edition import attach_story_updates, build_edition, edition_date_now
from .ingest import all_feeds, fetch_all, ingest
from .settings import load_settings
from .sports import PROVIDERS, update_sports

log = logging.getLogger("newspaper")


def cmd_migrate(args, settings) -> int:
    with db.connect() as conn:
        applied = db.migrate(conn)
    log.info("Migrations applied: %s", applied or "none (up to date)")
    return 0


def cmd_refresh(args, settings) -> int:
    with db.connect() as conn:
        db.migrate(conn)
        with db.job_run(conn, "refresh") as run:
            feeds = ingest(conn, settings)
            run.note(**feeds)
            if feeds["feeds_failed"]:
                run.warn(f"{feeds['feeds_failed']} of {feeds['feeds']} feeds failed")
            sports = update_sports(conn, settings)
            run.note(**sports)
            for problem in sports["sports_failed"]:
                run.warn(problem)
            run.note(story_updates=attach_story_updates(conn, settings))
            conn.execute("""delete from public.articles a
                            where fetched_at < now() - interval '21 days'
                              and not exists (select 1 from public.story_updates u where u.article_id = a.id)""")
            if feeds["feeds"] and feeds["feeds_failed"] == feeds["feeds"]:
                raise RuntimeError("Every feed failed — network problem?")
    return 0


def cmd_daily(args, settings) -> int:
    today, due = edition_date_now(settings)
    edition_date = date.fromisoformat(args.date) if args.date else today
    if args.if_due and not args.date and not due:
        log.info("Not yet %02d:00 in %s — nothing to do.", settings.edition_hour, settings.timezone)
        return 0
    with db.connect() as conn:
        db.migrate(conn)
        published = conn.execute(
            "select 1 from public.editions where edition_date = %s and status = 'published'",
            (edition_date,),
        ).fetchone()
        if published and not args.force:
            log.info("Edition %s is already published.", edition_date)
            return 0
        with db.job_run(conn, "refresh") as run:
            run.note(**ingest(conn, settings))
            run.note(**update_sports(conn, settings))
        with db.job_run(conn, "daily") as run:
            result = build_edition(
                conn, settings, run, edition_date=edition_date, force=args.force,
                use_ai=not args.no_ai, owner_email=os.environ.get("OWNER_EMAIL"),
            )
    log.info("Edition %s: %s", edition_date, result)
    return 0


def cmd_check_sources(args, settings) -> int:
    now = datetime.now(timezone.utc)
    results = fetch_all(all_feeds(settings), {}, now)
    bad = 0
    for r in results:
        images = sum(1 for i in r.items if i.image_url)
        if r.error:
            bad += 1
            print(f"FAIL  [{r.category:13}] {r.feed_url}  →  {r.error}")
        else:
            newest = max((i.published_at for i in r.items if i.published_at), default=None)
            print(f"ok    [{r.category:13}] {len(r.items):3} items, {images:3} images, "
                  f"newest {newest:%Y-%m-%d %H:%M}  {r.feed_url}" if newest else
                  f"ok    [{r.category:13}] {len(r.items):3} items (undated)  {r.feed_url}")
    print(f"\n{len(results) - bad}/{len(results)} feeds OK\n")
    for name, provider in PROVIDERS.items():
        try:
            events = provider(settings, now)
            print(f"ok    sports/{name}: {len(events)} events" + ("" if events else " (disabled, no key, or none in window)"))
            for e in events[:3]:
                print(f"        {e['competition']}: {e['home']} {e['home_score'] or ''} - {e['away_score'] or ''} {e['away']} [{e['status']}] {e['detail'][:60]}")
        except Exception as exc:
            print(f"FAIL  sports/{name}: {type(exc).__name__}: {exc}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="newspaper")
    parser.add_argument("--config", help="path to sources.yaml")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate")
    sub.add_parser("refresh")
    daily = sub.add_parser("daily")
    daily.add_argument("--if-due", action="store_true", help="only run once publication time has passed")
    daily.add_argument("--force", action="store_true", help="rebuild an already published edition")
    daily.add_argument("--date", help="edition date YYYY-MM-DD (default: today)")
    daily.add_argument("--no-ai", action="store_true", help="plain digest without Claude")
    sub.add_parser("check-sources")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = load_settings(args.config)
    commands = {"migrate": cmd_migrate, "refresh": cmd_refresh, "daily": cmd_daily,
                "check-sources": cmd_check_sources}
    return commands[args.command](args, settings)


if __name__ == "__main__":
    sys.exit(main())
