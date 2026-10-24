"""Scores and fixtures from sports data APIs into public.sports_events.

Each provider is independent: if one is down or unconfigured, the others still
update. Tennis and badminton have no reliable free API, so they come through the
sports news feeds instead.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

import psycopg

from .settings import Settings

log = logging.getLogger(__name__)
UA = {"User-Agent": "PersonalNewspaperBot/2.0 (personal, non-commercial)"}


def _get_json(url: str, headers: dict | None = None, timeout: int = 20):
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _event(id, sport, competition, starts_at, status, home, away="", home_score=None,
           away_score=None, detail="", url=None) -> dict:
    return dict(id=id, sport=sport, competition=competition, starts_at=starts_at, status=status,
                home=home, away=away, home_score=home_score, away_score=away_score,
                detail=detail, url=url)


# ─── football-data.org ───────────────────────────────────────────────────────
FD_STATUS = {"SCHEDULED": "scheduled", "TIMED": "scheduled", "IN_PLAY": "live", "PAUSED": "live",
             "EXTRA_TIME": "live", "PENALTY_SHOOTOUT": "live", "FINISHED": "finished",
             "AWARDED": "finished", "POSTPONED": "postponed", "SUSPENDED": "postponed",
             "CANCELLED": "cancelled"}


def football_data(settings: Settings, now: datetime) -> list[dict]:
    token = os.environ.get("FOOTBALL_DATA_TOKEN")
    cfg = settings.sports.football_data
    if not cfg.enabled or not token:
        return []
    date_from = (now - timedelta(days=2)).date().isoformat()
    date_to = (now + timedelta(days=6)).date().isoformat()     # free tier: max 10-day window
    data = _get_json(
        f"https://api.football-data.org/v4/matches?competitions={','.join(cfg.competitions)}"
        f"&dateFrom={date_from}&dateTo={date_to}",
        {"X-Auth-Token": token},
    )
    events = []
    for m in data.get("matches", []):
        ft = (m.get("score") or {}).get("fullTime") or {}
        status = FD_STATUS.get(m.get("status"), "scheduled")
        detail = {"finished": "FT", "live": "Live"}.get(status, "")
        if m.get("stage") and m["stage"] not in ("REGULAR_SEASON", "LEAGUE_STAGE"):
            detail = (detail + " · " if detail else "") + m["stage"].replace("_", " ").title()
        events.append(_event(
            f"fd:{m['id']}", "Football", m["competition"]["name"], _ts(m["utcDate"]), status,
            m["homeTeam"].get("shortName") or m["homeTeam"].get("name") or "TBD",
            m["awayTeam"].get("shortName") or m["awayTeam"].get("name") or "TBD",
            None if ft.get("home") is None else str(ft["home"]),
            None if ft.get("away") is None else str(ft["away"]),
            detail,
        ))
    return events


# ─── Formula 1 (Jolpica, the Ergast successor) ───────────────────────────────
def _race_start(race: dict) -> datetime:
    return _ts(f"{race['date']}T{race.get('time', '12:00:00Z')}")


def formula1(settings: Settings, now: datetime) -> list[dict]:
    if not settings.sports.f1.enabled:
        return []
    events = []
    last = _get_json("https://api.jolpi.ca/ergast/f1/current/last/results.json")
    for race in last["MRData"]["RaceTable"]["Races"]:
        podium = [
            f"{r['position']}. {r['Driver']['familyName']} ({r['Constructor']['name']})"
            for r in race.get("Results", [])[:3]
        ]
        events.append(_event(
            f"f1:{race['season']}-{race['round']}", "Formula 1", "Formula 1", _race_start(race),
            "finished", race["raceName"], detail=" · ".join(podium), url=race.get("url"),
        ))
    nxt = _get_json("https://api.jolpi.ca/ergast/f1/current/next.json")
    for race in nxt["MRData"]["RaceTable"]["Races"]:
        events.append(_event(
            f"f1:{race['season']}-{race['round']}", "Formula 1", "Formula 1", _race_start(race),
            "scheduled", race["raceName"], detail=race["Circuit"]["circuitName"], url=race.get("url"),
        ))
    return events


# ─── TheSportsDB (free public API) ───────────────────────────────────────────
def _sportsdb_status(ev: dict) -> str:
    raw = (ev.get("strStatus") or "").lower()
    if "postpon" in raw:
        return "postponed"
    if "cancel" in raw:
        return "cancelled"
    if "finish" in raw or raw in ("ft", "aet", "aot", "ap", "pen"):
        return "finished"
    if ev.get("intHomeScore") in (None, "") or raw in ("", "ns", "not started", "tbd"):
        return "scheduled"
    return "live"


def thesportsdb(settings: Settings, now: datetime) -> list[dict]:
    cfg = settings.sports.thesportsdb
    if not cfg.enabled:
        return []
    key = os.environ.get("THESPORTSDB_KEY") or "123"
    events, seen = [], set()
    first = True
    for lg in cfg.leagues:
        for endpoint in ("eventspastleague", "eventsnextleague"):
            if not first:
                time.sleep(2.5)                    # free tier: 30 requests/minute
            first = False
            try:
                data = _get_json(f"https://www.thesportsdb.com/api/v1/json/{key}/{endpoint}.php?id={lg.id}")
            except urllib.error.HTTPError as exc:
                log.warning("TheSportsDB %s %s: HTTP %s", lg.label, endpoint, exc.code)
                continue
            for ev in data.get("events") or data.get("results") or []:
                if ev["idEvent"] in seen or not ev.get("dateEvent"):
                    continue
                seen.add(ev["idEvent"])
                stamp = ev.get("strTimestamp") or f"{ev['dateEvent']}T{ev.get('strTime') or '12:00:00'}"
                starts = _ts(stamp if stamp.endswith(("Z", "+00:00")) else stamp + "+00:00")
                if abs((starts - now).days) > 10:
                    continue
                status = _sportsdb_status(ev)
                score = lambda v: None if v in (None, "") or status == "scheduled" else str(v)
                events.append(_event(
                    f"tsdb:{ev['idEvent']}", lg.sport, lg.label, starts, status,
                    ev.get("strHomeTeam") or ev.get("strEvent") or "TBD", ev.get("strAwayTeam") or "",
                    score(ev.get("intHomeScore")), score(ev.get("intAwayScore")),
                    ev.get("strResult") or (ev.get("strStatus") or "")[:80],
                ))
    return events


# ─── Cricket (cricketdata.org) ───────────────────────────────────────────────
def cricket(settings: Settings, now: datetime) -> list[dict]:
    key = os.environ.get("CRICKET_API_KEY")
    if not settings.sports.cricket.enabled or not key:
        return []
    data = _get_json(f"https://api.cricapi.com/v1/currentMatches?apikey={key}&offset=0")
    if data.get("status") != "success":
        raise RuntimeError(f"cricketdata: {data.get('reason') or data.get('status')}")
    events = []
    for m in data.get("data", []):
        teams = m.get("teams") or []
        if len(teams) < 2 or not m.get("dateTimeGMT"):
            continue

        def score_for(team: str) -> str | None:
            parts = [f"{s['r']}/{s['w']} ({s['o']})" for s in m.get("score") or []
                     if team.lower() in (s.get("inning") or "").lower()]
            return " & ".join(parts) or None

        if m.get("matchEnded"):
            status = "finished"
        elif m.get("matchStarted"):
            status = "live"
        else:
            status = "scheduled"
        series = m.get("name", "").split(",")[-1].strip() if "," in m.get("name", "") else (m.get("matchType") or "").upper()
        events.append(_event(
            f"cric:{m['id']}", "Cricket", series or "Cricket", _ts(m["dateTimeGMT"] + "Z"),
            status, teams[0], teams[1], score_for(teams[0]), score_for(teams[1]),
            m.get("status", ""),
        ))
    return events


PROVIDERS = {"football_data": football_data, "f1": formula1, "thesportsdb": thesportsdb, "cricket": cricket}


def update_sports(conn: psycopg.Connection, settings: Settings, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    counts, failed = {}, []
    for name, provider in PROVIDERS.items():
        try:
            events = provider(settings, now)
        except Exception as exc:
            failed.append(f"{name}: {type(exc).__name__}: {exc}"[:300])
            continue
        with conn.transaction():
            for e in events:
                conn.execute(
                    """insert into public.sports_events
                         (id, sport, competition, starts_at, status, home, away, home_score,
                          away_score, detail, url, updated_at)
                       values (%(id)s, %(sport)s, %(competition)s, %(starts_at)s, %(status)s, %(home)s,
                               %(away)s, %(home_score)s, %(away_score)s, %(detail)s, %(url)s, now())
                       on conflict (id) do update set
                         sport = excluded.sport, competition = excluded.competition,
                         starts_at = excluded.starts_at, status = excluded.status,
                         home = excluded.home, away = excluded.away,
                         home_score = excluded.home_score, away_score = excluded.away_score,
                         detail = excluded.detail, url = coalesce(excluded.url, public.sports_events.url),
                         updated_at = now()""",
                    e,
                )
        counts[name] = len(events)
    conn.execute("delete from public.sports_events where starts_at < now() - interval '45 days'")
    for line in failed:
        log.warning("Sports provider problem — %s", line)
    return {"sports_events": counts, "sports_failed": failed}


def recent_results_text(conn: psycopg.Connection, hours: int = 36) -> str:
    """Finished results for the editor to write about (real data, not guesses)."""
    rows = conn.execute(
        """select * from public.sports_events
           where status = 'finished' and starts_at > now() - make_interval(hours => %s)
           order by competition, starts_at""",
        (hours,),
    ).fetchall()
    lines = []
    for r in rows:
        if r["away"]:
            lines.append(f"- {r['competition']}: {r['home']} {r['home_score'] or ''} – "
                         f"{r['away_score'] or ''} {r['away']} {('(' + r['detail'] + ')') if r['detail'] else ''}".strip())
        else:
            lines.append(f"- {r['competition']}: {r['home']} — {r['detail']}")
    return "\n".join(lines)
