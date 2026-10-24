"""Postgres access, migrations and job-run bookkeeping."""

from __future__ import annotations

import json
import logging
import os
import traceback
from contextlib import contextmanager
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .settings import BACKEND_DIR

log = logging.getLogger(__name__)
MIGRATIONS_DIR = BACKEND_DIR / "db" / "migrations"


def connect(url: str | None = None) -> psycopg.Connection:
    url = url or os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL is not set. See SETUP.md.")
    # prepare_threshold=None keeps us compatible with Supabase's connection pooler.
    return psycopg.connect(url, row_factory=dict_row, prepare_threshold=None, autocommit=True)


def migrate(conn: psycopg.Connection, directory: Path = MIGRATIONS_DIR) -> list[str]:
    conn.execute(
        "create table if not exists public.schema_migrations "
        "(name text primary key, applied_at timestamptz not null default now())"
    )
    conn.execute("alter table public.schema_migrations enable row level security")
    done = {r["name"] for r in conn.execute("select name from public.schema_migrations")}
    applied = []
    for path in sorted(directory.glob("*.sql")):
        if path.name in done:
            continue
        with conn.transaction():
            conn.execute(path.read_text(encoding="utf-8"))
            conn.execute("insert into public.schema_migrations (name) values (%s)", (path.name,))
        applied.append(path.name)
        log.info("Applied migration %s", path.name)
    return applied


class JobRun:
    """Collects a summary dict while a job runs; stored in public.job_runs."""

    def __init__(self, conn: psycopg.Connection, job: str):
        self.conn = conn
        self.job = job
        self.summary: dict = {}
        self.partial = False
        self.id = conn.execute(
            "insert into public.job_runs (job) values (%s) returning id", (job,)
        ).fetchone()["id"]

    def note(self, **items) -> None:
        self.summary.update(items)

    def warn(self, message: str) -> None:
        self.partial = True
        self.summary.setdefault("warnings", []).append(message[:500])
        log.warning(message)

    def finish(self, status: str, error: str | None = None) -> None:
        self.conn.execute(
            "update public.job_runs set finished_at = now(), status = %s, summary = %s, error = %s "
            "where id = %s",
            (status, Jsonb(self.summary), error, self.id),
        )


@contextmanager
def job_run(conn: psycopg.Connection, job: str):
    run = JobRun(conn, job)
    try:
        yield run
    except BaseException as exc:
        run.finish("failed", "".join(traceback.format_exception_only(exc)).strip()[:2000])
        raise
    else:
        run.finish("partial" if run.partial else "ok")
        log.info("%s finished: %s", job, json.dumps(run.summary, default=str)[:1000])


def owner_prefs(conn: psycopg.Connection, owner_email: str | None) -> dict | None:
    """The newspaper owner's saved preferences, if they have saved any."""
    if owner_email:
        row = conn.execute(
            "select p.prefs from public.profiles p join auth.users u on u.id = p.user_id "
            "where lower(u.email) = lower(%s)",
            (owner_email,),
        ).fetchone()
    else:
        row = conn.execute(
            "select prefs from public.profiles order by updated_at desc limit 1"
        ).fetchone()
    return row["prefs"] if row else None
