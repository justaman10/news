"""Command line entry point: `python -m newspaper`."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .build import build_edition, load_editions, save_edition
from .config import load_config
from .render import render_site


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build your personal daily newspaper.")
    parser.add_argument("--config", default="config.yaml", help="path to config.yaml")
    parser.add_argument("--data", default="editions", help="where edition JSON is stored")
    parser.add_argument("--out", default="site", help="where the HTML site is written")
    parser.add_argument("--date", help="edition date (YYYY-MM-DD); default: today in paper.timezone")
    parser.add_argument("--force", action="store_true", help="rebuild even if today's edition exists")
    parser.add_argument("--no-ai", action="store_true", help="skip Claude; plain headline digest")
    parser.add_argument("--render-only", action="store_true", help="only re-render HTML from saved editions")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    log = logging.getLogger("newspaper")

    config = load_config(args.config)
    data_dir, out_dir = Path(args.data), Path(args.out)
    date = args.date or datetime.now(ZoneInfo(config.paper.timezone)).date().isoformat()

    if not args.render_only:
        existing = data_dir / f"{date}.json"
        if existing.exists() and not args.force:
            log.info("Edition %s already exists (use --force to rebuild).", date)
        else:
            edition = build_edition(config, date, data_dir, use_ai=not args.no_ai)
            stories = sum(len(s.stories) for s in edition.sections)
            if stories == 0:
                log.error("No stories found — are the feeds reachable? Not saving an empty edition.")
                return 1
            log.info("Saved %s (%d stories, AI=%s)", save_edition(edition, data_dir), stories, edition.ai)

    editions = load_editions(data_dir)
    if not editions:
        log.error("No editions to render yet.")
        return 1
    render_site(editions, out_dir)
    log.info("Site written to %s/ (%d editions)", out_dir, len(editions))
    return 0


if __name__ == "__main__":
    sys.exit(main())
