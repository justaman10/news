"""Backend tests against a real Postgres.

Set TEST_DATABASE_URL to a server you can create databases on, e.g.
  TEST_DATABASE_URL=postgresql://postgres@localhost:5432/postgres
Each test class gets a fresh database with the Supabase stubs + migrations.
"""

from __future__ import annotations

import functools
import http.server
import json
import os
import re
import tempfile
import threading
import unittest
import uuid
from datetime import date, datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import psycopg
from psycopg.conninfo import make_conninfo

from newspaper import db, edition, editor, sports
from newspaper.__main__ import main
from newspaper.cluster import cluster_articles, similar, tokens
from newspaper.settings import load_settings, merge_prefs

HERE = Path(__file__).parent
ADMIN_URL = os.environ.get("TEST_DATABASE_URL")


def rss(name: str, slug: str, items: list[tuple[str, str]], now: datetime, image=True) -> str:
    parts = ['<?xml version="1.0"?><rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/">'
             f"<channel><title>{name}</title>"]
    for i, (title, desc) in enumerate(items):
        media = f'<media:content url="http://img.example.com/{slug}/{i}.jpg" medium="image"/>' if image else ""
        parts.append(
            f"<item><title>{title}</title><link>https://{slug}.example.com/story/{i}</link>"
            f"<description>&lt;p&gt;{desc}&lt;/p&gt;</description>{media}"
            f"<pubDate>{format_datetime(now - timedelta(hours=i + 1))}</pubDate></item>"
        )
    parts.append("<item><title>Ancient history</title><link>https://old.example.com/x</link>"
                 f"<pubDate>{format_datetime(now - timedelta(days=9))}</pubDate></item>")
    parts.append("</channel></rss>")
    return "".join(parts)


class FakeMessages:
    """Stands in for client.beta.messages, answering from the ids in each prompt."""

    def __init__(self):
        self.calls = []
        self.lock = threading.Lock()

    def create(self, **kw):
        with self.lock:
            self.calls.append(kw)
        prompt = kw["messages"][0]["content"]
        usage = SimpleNamespace(input_tokens=1000, output_tokens=500, cache_read_input_tokens=0,
                                cache_creation_input_tokens=0,
                                server_tool_use=SimpleNamespace(web_search_requests=1 if "tools" in kw else 0))
        if "tools" in kw:                         # deep dive
            if len(kw["messages"]) == 1:          # first turn: pause after a search
                return SimpleNamespace(stop_reason="pause_turn", usage=usage, content=[
                    SimpleNamespace(type="web_search_tool_result", content=[
                        SimpleNamespace(type="web_search_result", url="https://extra.example.com/a",
                                        title="Extra reporting")])])
            urls = re.findall(r"\((https://[^)]+)\)", prompt)
            return SimpleNamespace(stop_reason="tool_use", usage=usage, content=[SimpleNamespace(
                type="tool_use", name="publish_deep_dive", input={
                    "what_happened": "Reported facts.", "background": "Context.",
                    "why_it_matters": "Because.", "perspectives": [{"label": "Analysts", "view": "A view."}],
                    "implications": "Effects.", "what_to_watch": "Next vote.", "timeline": [],
                    "sources_used": [urls[0], "https://extra.example.com/a", "https://invented.example.com/"],
                })])
        if "Candidate clusters" in prompt:
            ids = re.findall(r"^\[(c\d+)\]", prompt, flags=re.M)
            payload = {"intro": "Today in brief.", "stories": [
                {"cluster_id": cid, "headline": f"Edited {cid}", "summary": "What happened.",
                 "why_it_matters": "Why.", "background": "", "perspectives": [], "implications": "",
                 "key_terms": [{"term": "Term", "definition": "Meaning."}],
                 "interview": [{"question": f"Question on {cid}?", "answer": "Outline."}],
                 "talking_point": "", "importance": 9 - n}
                for n, cid in enumerate(ids[:3])
            ] + [{"cluster_id": "c999", "headline": "Invented", "summary": "", "why_it_matters": "",
                  "background": "", "perspectives": [], "implications": "", "key_terms": [],
                  "interview": [], "talking_point": "", "importance": 10}],
                "concept": {"name": "Opportunity cost", "explanation": "x", "example": "y",
                            "question": "q", "answer": "a"}}
        else:                                     # front page
            ids = [int(i) for i in re.findall(r"^\[(\d+)\]", prompt, flags=re.M)]
            payload = {"lead_story_id": ids[-1], "top_story_ids": ids[:5] + [424242],
                       "lead_note": "The big picture.",
                       "quiz": [{"question": "Q?", "options": ["a", "b", "c", "d"], "answer_index": 1,
                                 "explanation": "b."},
                                {"question": "Broken", "options": ["a"], "answer_index": 3, "explanation": ""}]}
        return SimpleNamespace(stop_reason="end_turn", usage=usage,
                               content=[SimpleNamespace(type="text", text=json.dumps(payload))])


@unittest.skipUnless(ADMIN_URL, "TEST_DATABASE_URL not set")
class WorkerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dbname = f"news_{uuid.uuid4().hex[:8]}"
        with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
            admin.execute(f"create database {cls.dbname}")
        cls.url = make_conninfo(ADMIN_URL, dbname=cls.dbname)
        with psycopg.connect(cls.url, autocommit=True) as conn:
            conn.execute((HERE / "supabase_stub.sql").read_text())

        now = datetime.now(timezone.utc)
        cls.feeds = Path(tempfile.mkdtemp())
        (cls.feeds / "world_a.xml").write_text(rss("Outlet A", "a", [
            ("Leaders agree landmark climate finance deal at summit", "Nations pledged new money."),
            ("Earthquake strikes coastal region, hundreds evacuated", "A 6.8 magnitude quake."),
            ("Shipping disruption pushes freight rates higher", "Red Sea route avoided."),
        ], now))
        (cls.feeds / "world_b.xml").write_text(rss("Outlet B", "b", [
            ("Summit leaders agree landmark climate finance deal", "Different outlet, same deal."),
            ("Central bank raises interest rates again", "Inflation stubborn."),
        ], now, image=False))
        (cls.feeds / "germany.xml").write_text(rss("Outlet DE", "de", [
            ("Koblenz council approves new Rhine bridge plan", "Local decision."),
            ("German coalition debates migration reform", "Bundestag vote next week."),
        ], now))
        (cls.feeds / "biz.xml").write_text(rss("Outlet Biz", "biz", [
            ("Central bank raises interest rates again amid inflation", "Markets fell."),
            ("Carmaker announces battery plant investment", "Billions committed."),
        ], now))

        class Quiet(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *a):
                pass

        cls.server = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0), functools.partial(Quiet, directory=str(cls.feeds)))
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{cls.server.server_port}"
        cls.config = cls.feeds / "sources.yaml"
        cls.config.write_text(f"""
timezone: Europe/Berlin
ai: {{deep_dives: 2, daily_budget_usd: 10}}
categories:
  - {{slug: world, name: World, feeds: [{base}/world_a.xml, {base}/world_b.xml, {base}/missing.xml]}}
  - {{slug: germany, name: Germany, local_keywords: [Koblenz], feeds: [{base}/germany.xml]}}
  - {{slug: business, name: Business, feeds: [{base}/biz.xml]}}
  - {{slug: interview, name: Interview Intelligence, derived_from: [business, world], feeds: []}}
default_prefs:
  categories:
    world: {{weight: 2, depth: brief}}
    germany: {{weight: 3, depth: deep}}
    business: {{weight: 3, depth: deep}}
    interview: {{weight: 3, depth: deep}}
  countries: [Germany]
sports:
  football_data: {{enabled: false}}
  f1: {{enabled: false}}
  thesportsdb: {{enabled: false}}
  cricket: {{enabled: false}}
""")
        cls.env = mock.patch.dict(os.environ, {"DATABASE_URL": cls.url, "NEWSPAPER_CONFIG": str(cls.config)})
        cls.env.start()

    @classmethod
    def tearDownClass(cls):
        cls.env.stop()
        cls.server.shutdown()
        with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
            admin.execute(f"drop database {cls.dbname} with (force)")

    def q(self, sql, *params):
        with db.connect(self.url) as conn:
            return conn.execute(sql, params).fetchall()

    def test_1_migrate_and_refresh(self):
        self.assertEqual(main(["migrate"]), 0)
        self.assertEqual(main(["migrate"]), 0)       # idempotent
        self.assertEqual(main(["refresh"]), 0)
        rows = self.q("select * from public.articles")
        titles = {r["title"] for r in rows}
        self.assertIn("Koblenz council approves new Rhine bridge plan", titles)
        self.assertNotIn("Ancient history", titles)
        self.assertTrue(all((r["image_url"] or "").startswith("https://") or r["image_url"] is None for r in rows))
        state = {r["feed_url"].rsplit("/", 1)[1]: r for r in self.q("select * from public.feed_state")}
        self.assertIn("HTTP 404", state["missing.xml"]["last_error"])
        self.assertIsNotNone(state["world_a.xml"]["last_modified"])
        run = self.q("select * from public.job_runs where job = 'refresh' order by id desc limit 1")[0]
        self.assertEqual(run["status"], "partial")    # one feed failed

        # Second run: conditional GET → 304, no duplicates.
        before = len(rows)
        self.assertEqual(main(["refresh"]), 0)
        self.assertEqual(len(self.q("select id from public.articles")), before)

    def test_2_daily_with_ai(self):
        fake = SimpleNamespace(beta=SimpleNamespace(messages=FakeMessages()))
        with mock.patch.object(editor, "make_client", return_value=fake):
            self.assertEqual(main(["daily", "--date", "2026-03-02"]), 0)
            self.assertEqual(main(["daily", "--date", "2026-03-02"]), 0)   # already published: no-op
        calls = fake.beta.messages.calls
        self.assertEqual(calls[0]["model"], "claude-opus-5-5")
        self.assertEqual(calls[0]["fallbacks"], "default")

        ed = self.q("select * from public.editions where edition_date = '2026-03-02'")[0]
        self.assertEqual(ed["status"], "published")
        self.assertTrue(ed["ai"])
        self.assertEqual(ed["lead_note"], "The big picture.")
        self.assertEqual(len(ed["quiz"]), 1)                 # malformed question dropped
        stories = self.q("select * from public.stories where edition_id = %s order by category, rank", ed["id"])
        ids = {s["id"] for s in stories}
        self.assertTrue(set(ed["front_page"]) <= ids)         # invented id 424242 dropped
        self.assertNotIn("Invented", {s["headline"] for s in stories})

        # The climate deal (2 outlets) is one story, not two; the rates story
        # appears in one news section only (Interview Intelligence may revisit it).
        news = [s for s in stories if s["category"] != "interview"]
        climate = [s for s in news if any("climate" in src["title"].lower() for src in s["sources"])]
        self.assertEqual(len(climate), 1)
        self.assertEqual(len(climate[0]["sources"]), 2)
        rates = [s for s in news if any("interest rates" in src["title"] for src in s["sources"])]
        self.assertEqual(len(rates), 1)

        dives = [s for s in stories if s["deep_dive"]]
        self.assertEqual(len(dives), 2)
        cites = [c["url"] for c in dives[0]["deep_dive"]["citations"]]
        self.assertIn("https://extra.example.com/a", cites)
        self.assertNotIn("https://invented.example.com/", cites)
        self.assertEqual(self.q("select concept->>'name' as n from public.sections where edition_id = %s "
                                "and category = 'germany'", ed["id"])[0]["n"], "Opportunity cost")
        run = self.q("select * from public.job_runs where job = 'daily' order by id desc limit 1")[0]
        self.assertGreater(run["summary"]["ai"]["estimated_usd"], 0)

    def test_3_daily_without_ai_and_no_repeats(self):
        now = datetime.now(timezone.utc)
        # Overnight news arrives; yesterday's items are still in the feed too.
        (self.feeds / "world_b.xml").write_text(rss("Outlet B", "b", [
            ("Summit leaders agree landmark climate finance deal", "Same as yesterday."),
            ("Election results announced in island nation", "Opposition wins."),
            ("Floods hit river delta after record rainfall", "Thousands displaced."),
        ], now, image=False))
        os.utime(self.feeds / "world_b.xml", (now.timestamp() + 5, now.timestamp() + 5))
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}):
            self.assertEqual(main(["daily", "--date", "2026-03-03"]), 0)
        ed = self.q("select * from public.editions where edition_date = '2026-03-03'")[0]
        self.assertFalse(ed["ai"])
        stories = self.q("select * from public.stories where edition_id = %s", ed["id"])
        self.assertTrue(stories)
        self.assertEqual(ed["number"], 2)
        # Yesterday's stories are not repeated.
        prev = self.q("select sources from public.stories s join public.editions e on e.id = s.edition_id "
                      "where e.edition_date = '2026-03-02'")
        prev_urls = {src["url"] for r in prev for src in r["sources"]}
        for s in stories:
            self.assertFalse({src["url"] for src in s["sources"]} & prev_urls)

    def test_4_rls(self):
        uid_a, uid_b = uuid.uuid4(), uuid.uuid4()
        with psycopg.connect(self.url, autocommit=True) as conn:
            conn.execute("insert into auth.users (id, email) values (%s, 'a@x.com'), (%s, 'b@x.com')", (uid_a, uid_b))
            conn.execute("insert into public.editions (edition_date, number) values ('2030-01-01', 99)")
            story = conn.execute("select id from public.stories limit 1").fetchone()[0]
            conn.execute("insert into public.profiles (user_id, prefs) values (%s, %s)",
                         (uid_a, json.dumps({"countries": ["India"]})))
            conn.execute("insert into public.bookmarks values (%s, %s)", (uid_a, story))

            conn.execute("set role anon")
            dates = {r[0] for r in conn.execute("select edition_date from public.editions")}
            self.assertNotIn(date(2030, 1, 1), dates)       # drafts are invisible
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                conn.execute("select * from public.bookmarks")
            conn.execute("reset role")

            conn.execute("set role authenticated")
            conn.execute("select set_config('request.jwt.claims', %s, false)", (json.dumps({"sub": str(uid_b)}),))
            self.assertEqual(conn.execute("select count(*) from public.bookmarks").fetchone()[0], 0)
            self.assertEqual(conn.execute("select count(*) from public.profiles").fetchone()[0], 0)
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                conn.execute("insert into public.bookmarks values (%s, %s)", (uid_a, story))
            conn.execute("reset role")

        # The worker uses the owner's saved preferences.
        with db.connect(self.url) as conn:
            self.assertEqual(db.owner_prefs(conn, "A@x.com"), {"countries": ["India"]})


class UnitTest(unittest.TestCase):
    def test_clustering(self):
        now = datetime.now(timezone.utc)
        mk = lambda t, src, cat="world", url=None: {"title": t, "source": src, "category": cat,
                                                    "url": url or f"https://{src}/{t}", "snippet": "",
                                                    "published_at": now, "fetched_at": now}
        clusters = cluster_articles([
            mk("Leaders agree landmark climate finance deal at summit", "a"),
            mk("Summit leaders agree landmark climate finance deal", "b"),
            mk("Earthquake strikes coastal region", "a"),
            mk("Earthquake strikes coastal region", "a", "science", url="https://a/Earthquake strikes coastal region"),
        ])
        self.assertEqual(len(clusters), 2)
        self.assertEqual({len(c.sources) for c in clusters}, {1, 2})
        self.assertFalse(similar(tokens("Apple launches new iPhone"), tokens("Apple shares fall on tariffs")))

    def test_merge_prefs(self):
        merged = merge_prefs({"categories": {"world": {"weight": 2, "depth": "brief"}}, "teams": ["A"]},
                             {"categories": {"world": {"depth": "deep"}}, "teams": ["B"], "countries": None})
        self.assertEqual(merged["categories"]["world"], {"weight": 2, "depth": "deep"})
        self.assertEqual(merged["teams"], ["B"])

    def test_edition_timing(self):
        s = load_settings()
        winter = datetime(2026, 1, 15, 4, 30, tzinfo=timezone.utc)     # 05:30 Berlin
        summer = datetime(2026, 7, 15, 4, 30, tzinfo=timezone.utc)     # 06:30 Berlin
        self.assertEqual(edition.edition_date_now(s, winter), (date(2026, 1, 15), False))
        self.assertEqual(edition.edition_date_now(s, summer), (date(2026, 7, 15), True))

    def test_sports_parsers(self):
        s = load_settings()
        now = datetime(2026, 10, 24, tzinfo=timezone.utc)
        fd = {"matches": [{"id": 1, "utcDate": "2026-10-23T19:00:00Z", "status": "FINISHED",
                           "competition": {"name": "Bundesliga", "code": "BL1"},
                           "homeTeam": {"shortName": "Bayern"}, "awayTeam": {"shortName": "Dortmund"},
                           "score": {"fullTime": {"home": 3, "away": 1}}, "stage": "REGULAR_SEASON"}]}
        with mock.patch.object(sports, "_get_json", return_value=fd), \
                mock.patch.dict(os.environ, {"FOOTBALL_DATA_TOKEN": "t"}):
            e = sports.football_data(s, now)[0]
        self.assertEqual((e["home"], e["home_score"], e["away_score"], e["status"]), ("Bayern", "3", "1", "finished"))

        tsdb = {"events": [{"idEvent": "9", "strTimestamp": "2026-10-24T00:00:00", "dateEvent": "2026-10-24", "strStatus": "Q3",
                            "strHomeTeam": "Lakers", "strAwayTeam": "Celtics", "intHomeScore": "88",
                            "intAwayScore": "80"}]}
        with mock.patch.object(sports, "_get_json", return_value=tsdb), mock.patch.object(sports.time, "sleep"):
            ev = sports.thesportsdb(s, now)
        self.assertEqual((ev[0]["home"], ev[0]["home_score"], ev[0]["status"]), ("Lakers", "88", "live"))
        self.assertEqual(len(ev), 1)                     # same event on several days counted once

        f1_last = {"MRData": {"RaceTable": {"Races": [{"season": "2026", "round": "19", "raceName": "Mexico GP",
                   "date": "2026-10-18", "time": "20:00:00Z", "url": "https://f1.example",
                   "Results": [{"position": "1", "Driver": {"familyName": "Norris"}, "Constructor": {"name": "McLaren"}}]}]}}}
        f1_next = {"MRData": {"RaceTable": {"Races": [{"season": "2026", "round": "20", "raceName": "Brazil GP",
                   "date": "2026-11-01", "Circuit": {"circuitName": "Interlagos"}}]}}}
        with mock.patch.object(sports, "_get_json", side_effect=[f1_last, f1_next]):
            f1 = sports.formula1(s, now)
        self.assertIn("Norris", f1[0]["detail"])
        self.assertEqual(f1[1]["status"], "scheduled")

        cric = {"status": "success", "data": [{"id": "m1", "name": "India vs Australia, 2nd ODI",
                "matchType": "odi", "status": "India won by 5 wkts", "dateTimeGMT": "2026-10-23T08:00:00",
                "teams": ["India", "Australia"], "matchStarted": True, "matchEnded": True,
                "score": [{"r": 250, "w": 8, "o": 50, "inning": "Australia Inning 1"},
                          {"r": 251, "w": 5, "o": 47.2, "inning": "India Inning 1"}]}]}
        with mock.patch.object(sports, "_get_json", return_value=cric), \
                mock.patch.dict(os.environ, {"CRICKET_API_KEY": "k"}):
            c = sports.cricket(s, now)[0]
        self.assertEqual((c["home_score"], c["away_score"], c["competition"]), ("251/5 (47.2)", "250/8 (50)", "2nd ODI"))


if __name__ == "__main__":
    unittest.main()


class FakeGemini(http.server.BaseHTTPRequestHandler):
    """Mimics the Gemini REST API, including the awkward bits we must handle."""
    calls: list = []
    rate_limited_once = False

    def log_message(self, *a):
        pass

    def _send(self, code, payload):
        data = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self._send(200, {"models": [
            {"name": "models/gemini-9-flash", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/gemini-9-flash-lite", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/gemini-9-flash-image", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/embedding-1", "supportedGenerationMethods": ["embedContent"]},
        ]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        FakeGemini.calls.append((self.path, body))
        if "gemini-flash-latest" in self.path:
            return self._send(404, {"error": {"code": 404, "message": "model not found"}})
        if not FakeGemini.rate_limited_once:
            FakeGemini.rate_limited_once = True
            return self._send(429, {"error": {"code": 429, "details": [{"retryDelay": "0s"}]}})
        if "responseJsonSchema" in body["generationConfig"]:
            return self._send(400, {"error": {"code": 400, "message": "Unknown name responseJsonSchema"}})
        prompt = body["contents"][0]["parts"][0]["text"]
        if "Candidate clusters" in prompt:
            ids = re.findall(r"^\[(c\d+)\]", prompt, flags=re.M)
            payload = {"intro": "Gemini intro.", "stories": [
                {"cluster_id": c, "headline": f"Gemini {c}", "summary": "s", "why_it_matters": "w", "background": "",
                 "perspectives": [], "implications": "", "key_terms": [], "interview": [{"question": "q?", "answer": "a"}],
                 "talking_point": "", "importance": 7} for c in ids[:2]],
                "concept": {"name": "Moat", "explanation": "e", "example": "x", "question": "q", "answer": "a"}}
        elif "deep dive" in prompt:
            urls = re.findall(r"\((https://[^)]+)\)", prompt)
            payload = {"what_happened": "w", "background": "b", "why_it_matters": "y", "perspectives": [],
                       "implications": "i", "what_to_watch": "t", "timeline": [], "sources_used": urls[:1] + ["https://x.invalid/"]}
        else:
            ids = [int(i) for i in re.findall(r"^\[(\d+)\]", prompt, flags=re.M)]
            payload = {"lead_story_id": ids[0], "top_story_ids": ids[1:4], "lead_note": "Gemini note.", "quiz": []}
        self._send(200, {"candidates": [{"finishReason": "STOP", "content": {"parts": [
            {"text": "thinking...", "thought": True}, {"text": "```json\n" + json.dumps(payload) + "\n```"}]}}],
            "usageMetadata": {"promptTokenCount": 1200, "candidatesTokenCount": 300}})


@unittest.skipUnless(ADMIN_URL, "TEST_DATABASE_URL not set")
class GeminiEditionTest(WorkerTest):
    """Runs the same pipeline with the free Gemini editor instead of Claude."""

    def test_2_daily_with_ai(self):
        from newspaper.gemini import GeminiClient
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeGemini)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        client = GeminiClient("k", "gemini-flash-latest", base_url=f"http://127.0.0.1:{srv.server_port}/v1beta", min_interval=0)
        with mock.patch.object(editor, "make_client", return_value=client), \
                mock.patch("newspaper.gemini.time.sleep"):
            self.assertEqual(main(["daily", "--date", "2026-03-02"]), 0)
        srv.shutdown()
        self.assertEqual(client.model, "gemini-9-flash")            # discovered the current Flash model
        self.assertEqual(client._schema_mode, "openapi")             # fell back after the 400
        sent = FakeGemini.calls[-1][1]["generationConfig"]["responseSchema"]
        self.assertNotIn("additionalProperties", json.dumps(sent))
        ed = self.q("select * from public.editions where edition_date = '2026-03-02'")[0]
        self.assertTrue(ed["ai"])
        self.assertEqual(ed["lead_note"], "Gemini note.")
        self.assertEqual(ed["stats"]["ai_provider"], "gemini")
        self.assertEqual(ed["stats"]["ai"]["estimated_usd"], 0)
        dives = self.q("select deep_dive from public.stories where deep_dive is not null")
        self.assertTrue(dives)
        for d in dives:
            self.assertNotIn("https://x.invalid/", [c["url"] for c in d["deep_dive"]["citations"]])


class ProviderTest(unittest.TestCase):
    def test_provider_choice(self):
        from newspaper.gemini import GeminiClient
        from newspaper.settings import AISettings
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "", "GEMINI_API_KEY": "g"}):
            self.assertIsInstance(editor.make_client(AISettings()), GeminiClient)
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "a", "GEMINI_API_KEY": "g"}):
            self.assertNotIsInstance(editor.make_client(AISettings()), GeminiClient)
            self.assertIsInstance(editor.make_client(AISettings(provider="gemini")), GeminiClient)
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "", "GEMINI_API_KEY": ""}):
            self.assertIsNone(editor.make_client(AISettings()))
