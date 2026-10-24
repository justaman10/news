"""End-to-end test: local RSS feeds → (fake) Claude → rendered site.

Run with:  python -m unittest discover tests
"""

from __future__ import annotations

import functools
import http.server
import json
import re
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from newspaper import build, editor
from newspaper.__main__ import main


def _rss(name: str, slug: str, items: list[tuple[str, str]], now: datetime) -> str:
    parts = [f'<?xml version="1.0"?><rss version="2.0"><channel><title>{name}</title>']
    for i, (title, desc) in enumerate(items):
        parts.append(
            f"<item><title>{title}</title><link>https://example.com/{slug}/{i}</link>"
            f"<description>&lt;p&gt;{desc}&lt;/p&gt;</description>"
            f"<pubDate>{format_datetime(now - timedelta(hours=i + 1))}</pubDate></item>"
        )
    parts.append(
        "<item><title>Ancient story</title><link>https://example.com/old</link>"
        f"<description>old</description><pubDate>{format_datetime(now - timedelta(days=10))}</pubDate></item>"
    )
    parts.append("</channel></rss>")
    return "".join(parts)


class FakeMessages:
    """Stands in for client.beta.messages; answers from the prompt's candidate ids."""

    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        prompt = kwargs["messages"][0]["content"]
        if "Candidates:" in prompt:
            ids = re.findall(r"^\[([a-z0-9-]+)\]", prompt, flags=re.M)
            payload = {
                "stories": [
                    {
                        "id": i,
                        "headline": f"Rewritten {i}",
                        "summary": "What happened.",
                        "why_it_matters": "Why it matters.",
                        "background": "Context.",
                        "key_terms": [{"term": "Inference", "definition": "Running a trained model."}],
                        "interview_questions": [{"question": f"Q about {i}?", "answer_hint": "Outline </script>"}],
                        "talking_point": "A view.",
                    }
                    for i in ids[:2]
                ] + [{"id": "made-up", "headline": "x", "summary": "", "why_it_matters": "",
                      "background": "", "key_terms": [], "interview_questions": [], "talking_point": ""}],
                "concept": {"name": "CAP theorem", "explanation": "Pick two.", "example": "Dynamo.",
                            "interview_question": "Explain CAP.", "answer_hint": "C, A, P."},
            }
        else:
            payload = {
                "lead_note": "Big picture.",
                "quiz": [
                    {"question": "Q1?", "options": ["a", "b", "c", "d"], "answer_index": 2, "explanation": "c."},
                    {"question": "Bad", "options": ["a"], "answer_index": 5, "explanation": ""},
                ],
            }
        return SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text=json.dumps(payload))],
        )


class PipelineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        now = datetime.now(timezone.utc)
        cls.tmp = Path(tempfile.mkdtemp())
        feeds = cls.tmp / "feeds"
        feeds.mkdir()
        (feeds / "tech.xml").write_text(_rss("Tech Wire", "tech", [
            ("Chipmaker unveils new AI accelerator", "Doubles inference throughput for LLMs."),
            ("Cloud provider suffers major outage", "A config change took down two regions."),
            ("Huge discount on laptops", "Deal of the week."),
            ("Database adds vector search", "Approximate nearest-neighbour indexes."),
        ], now))
        (feeds / "biz.xml").write_text(_rss("Biz Daily", "biz", [
            ("Central bank holds interest rates", "Sticky services inflation."),
            ("Cloud provider suffers major outage", "Same story, different outlet."),
            ("Retailer posts record revenue", "Same-store sales rose 8 percent."),
        ], now))
        class QuietHandler(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *args):
                pass

        handler = functools.partial(QuietHandler, directory=str(feeds))
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{cls.server.server_port}"

        cls.config = cls.tmp / "config.yaml"
        cls.config.write_text(f"""
reader: {{name: Tester, target_roles: [Engineer]}}
paper: {{title: Test Times}}
ai: {{quiz_questions: 3}}
topics:
  - name: Tech
    depth: deep
    max_stories: 3
    exclude: [discount]
    feeds: [{base}/tech.xml, {base}/missing.xml]
  - name: Business
    depth: headlines
    feeds: [{base}/biz.xml]
""")

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def run_cli(self, name, *extra, fake=None):
        data, out = self.tmp / name / "editions", self.tmp / name / "site"
        with mock.patch.object(build, "make_client", return_value=fake):
            code = main(["--config", str(self.config), "--data", str(data), "--out", str(out),
                         "--date", "2026-01-02", *extra])
        return code, data, out

    def test_plain_digest_without_ai(self):
        code, data, out = self.run_cli("plain", "--no-ai")
        self.assertEqual(code, 0)
        ed = json.loads((data / "2026-01-02.json").read_text())
        self.assertFalse(ed["ai"])
        tech, biz = ed["sections"]
        titles = [s["headline"] for s in tech["stories"]]
        self.assertNotIn("Huge discount on laptops", titles)       # excluded keyword
        self.assertNotIn("Ancient story", titles)                  # outside lookback
        biz_titles = [s["headline"] for s in biz["stories"]]
        self.assertNotIn("Cloud provider suffers major outage", biz_titles)  # deduped across topics
        for page in ("index.html", "2026-01-02.html", "archive.html", "prep.html", "style.css", "app.js"):
            self.assertTrue((out / page).exists(), page)

    def test_ai_edition(self):
        fake = SimpleNamespace(beta=SimpleNamespace(messages=FakeMessages()))
        code, data, out = self.run_cli("ai", fake=fake)
        self.assertEqual(code, 0)
        ed = json.loads((data / "2026-01-02.json").read_text())
        self.assertTrue(ed["ai"])
        self.assertEqual(ed["lead_note"], "Big picture.")
        self.assertEqual(len(ed["quiz"]), 1)                       # invalid quiz item dropped
        tech = ed["sections"][0]
        self.assertEqual(len(tech["stories"]), 2)                  # unknown id ignored
        self.assertTrue(tech["stories"][0]["link"].startswith("https://example.com/tech/"))
        self.assertEqual(tech["concept"]["name"], "CAP theorem")

        call = fake.beta.messages.calls[0]
        self.assertEqual(call["model"], "claude-opus-5-5")
        self.assertEqual(call["fallbacks"], "default")
        self.assertIn("Depth: DEEP", call["messages"][0]["content"])

        prep = (out / "prep.html").read_text()
        self.assertNotIn("Outline </script>", prep)                # safely embedded
        self.assertIn("Concept of the day", (out / "index.html").read_text())

        # A second run on the same day is a no-op unless forced.
        code, _, _ = self.run_cli("ai", fake=fake)
        self.assertEqual(code, 0)
        self.assertEqual(len(fake.beta.messages.calls), 3)

    def test_ai_failure_falls_back_to_plain(self):
        class Refusing:
            def create(self, **kwargs):
                return SimpleNamespace(stop_reason="refusal", content=[])

        fake = SimpleNamespace(beta=SimpleNamespace(messages=Refusing()))
        code, data, _ = self.run_cli("refusal", fake=fake)
        self.assertEqual(code, 0)
        ed = json.loads((data / "2026-01-02.json").read_text())
        self.assertTrue(ed["sections"][0]["stories"])
        self.assertIsNone(ed["sections"][0]["concept"])
        self.assertFalse(ed["ai"])

    def test_no_api_key_means_no_client(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertIsNone(editor.make_client())


if __name__ == "__main__":
    unittest.main()
