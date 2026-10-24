"""The AI editor. Claude chooses and explains stories; it never supplies the news.

Every story it writes is tied to real articles we fetched (by cluster id), and
links it cites are checked against the URLs we actually have. Anything that
fails falls back to a plain, unedited digest of the source headlines.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass, field

import anthropic

from .cluster import Cluster
from .gemini import GeminiClient, GeminiError
from .gemini import from_env as gemini_from_env
from .settings import AISettings

log = logging.getLogger(__name__)

# USD per million tokens (input, output); web search is per search.
PRICES = {
    "claude-opus-5-5": (4.0, 20.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-haiku-5-5": (0.10, 0.50),
}
WEB_SEARCH_PRICE = 0.01

SYSTEM_PROMPT = """\
You are the editor of a personal daily newspaper with one reader. The reader \
wants to truly understand the day's news and to be ready to discuss it in \
consulting, strategy and business interviews.

Non-negotiable standards:
- The reporting you are given (headlines and publisher descriptions from named \
outlets) is the only source of facts about today's events. Never invent events, \
quotes, numbers, dates or names. If the material is thin, write less.
- You may add widely established background knowledge (how something works, \
history, who the actors are). Keep it clearly separate from what was reported \
today, and never present speculation as fact.
- Analysis (why it matters, implications, perspectives) is your judgement; \
phrase it as analysis ("this could…", "critics argue…"), not as reporting.
- Represent different perspectives fairly, including ones you may disagree with.
- Write plainly and concretely, like a sharp briefing from a well-read \
colleague. No hype, no clichés, no filler.
- Interview questions are ones a real interviewer might ask; answers are \
structured outlines (framework, key trade-offs, what a strong answer covers).
"""

DEPTH_GUIDE = {
    "headlines": (
        "HEADLINES depth: `summary` is one sentence (max 25 words). Leave "
        "why_it_matters, background, implications and talking_point empty; "
        "perspectives, key_terms and interview empty lists."
    ),
    "brief": (
        "BRIEF depth: `summary` 2-3 sentences; `why_it_matters` 1-2 sentences; "
        "0-2 key_terms; exactly 1 interview item. Leave background, implications "
        "and talking_point empty and perspectives an empty list."
    ),
    "deep": (
        "DEEP depth: `summary` 3-5 sentences on what was reported; "
        "`why_it_matters` 2-3 sentences incl. second-order effects; `background` "
        "3-5 sentences of context; `perspectives` 2-3 viewpoints (label who holds "
        "it); `implications` 2-3 sentences; 2-4 key_terms; 2-3 interview items; "
        "`talking_point` a crisp, defensible 1-2 sentence view."
    ),
}

_S = {"type": "string"}


def _obj(props: dict) -> dict:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def _arr(item: dict) -> dict:
    return {"type": "array", "items": item}


STORY_SCHEMA = _obj({
    "cluster_id": _S, "headline": _S, "summary": _S, "why_it_matters": _S, "background": _S,
    "perspectives": _arr(_obj({"label": _S, "view": _S})),
    "implications": _S,
    "key_terms": _arr(_obj({"term": _S, "definition": _S})),
    "interview": _arr(_obj({"question": _S, "answer": _S})),
    "talking_point": _S,
    "importance": {"type": "integer"},
})
CONCEPT_SCHEMA = _obj({"name": _S, "explanation": _S, "example": _S, "question": _S, "answer": _S})
SECTION_SCHEMA = _obj({"intro": _S, "stories": _arr(STORY_SCHEMA), "concept": CONCEPT_SCHEMA})
FRONT_SCHEMA = _obj({
    "lead_story_id": {"type": "integer"},
    "top_story_ids": _arr({"type": "integer"}),
    "lead_note": _S,
    "quiz": _arr(_obj({"question": _S, "options": _arr(_S), "answer_index": {"type": "integer"},
                       "explanation": _S})),
})
DEEP_DIVE_TOOL = {
    "name": "publish_deep_dive",
    "description": "Publish the finished deep dive. Call exactly once, when your research is done.",
    "strict": True,
    "input_schema": _obj({
        "what_happened": _S,
        "background": _S,
        "why_it_matters": _S,
        "perspectives": _arr(_obj({"label": _S, "view": _S})),
        "implications": _S,
        "what_to_watch": _S,
        "timeline": _arr(_obj({"date": _S, "event": _S})),
        "sources_used": _arr(_S),
    }),
}


class EditorError(Exception):
    pass


@dataclass
class Budget:
    """Tracks spend so optional work stops at the daily cap."""

    limit_usd: float
    spent_usd: float = 0.0
    calls: int = 0
    searches: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add(self, model: str, usage) -> None:
        price_in, price_out = PRICES.get(model, PRICES["claude-opus-5-5"])
        tin = (getattr(usage, "input_tokens", 0) or 0) + (getattr(usage, "cache_creation_input_tokens", 0) or 0)
        cached = getattr(usage, "cache_read_input_tokens", 0) or 0
        tout = getattr(usage, "output_tokens", 0) or 0
        stu = getattr(usage, "server_tool_use", None)
        searches = (getattr(stu, "web_search_requests", 0) or 0) if stu else 0
        cost = (tin * price_in + cached * price_in * 0.1 + tout * price_out) / 1e6 + searches * WEB_SEARCH_PRICE
        with self._lock:
            self.calls += 1
            self.searches += searches
            self.tokens_in += tin + cached
            self.tokens_out += tout
            self.spent_usd += cost

    def add_free(self, usage: dict) -> None:
        """Gemini free tier: count usage, no cost."""
        with self._lock:
            self.calls += 1
            self.tokens_in += usage.get("promptTokenCount", 0) or 0
            self.tokens_out += (usage.get("candidatesTokenCount", 0) or 0) + (usage.get("thoughtsTokenCount", 0) or 0)

    @property
    def exhausted(self) -> bool:
        return self.spent_usd >= self.limit_usd

    def as_dict(self) -> dict:
        return {"calls": self.calls, "searches": self.searches, "tokens_in": self.tokens_in,
                "tokens_out": self.tokens_out, "estimated_usd": round(self.spent_usd, 3)}


def make_client(ai: AISettings | None = None) -> anthropic.Anthropic | GeminiClient | None:
    ai = ai or AISettings()
    has_claude = bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))
    if ai.provider in ("auto", "claude") and has_claude:
        return anthropic.Anthropic(max_retries=3, timeout=600)
    if ai.provider in ("auto", "gemini"):
        client = gemini_from_env(ai.gemini_model)
        if client:
            log.info("Using Google Gemini (%s) as the AI editor.", ai.gemini_model)
            return client
    if ai.provider != "none":
        log.warning("No AI key set (ANTHROPIC_API_KEY or GEMINI_API_KEY) — plain digest without AI.")
    return None


def reader_profile(prefs: dict) -> str:
    j = lambda key: ", ".join(prefs.get(key) or []) or "—"
    weights = prefs.get("categories", {})
    priorities = ", ".join(f"{slug} ({cfg.get('weight', 2)}/3)" for slug, cfg in weights.items())
    return (
        "Reader profile\n"
        f"- Follows countries: {j('countries')}\n"
        f"- Industries of interest: {j('industries')}\n"
        f"- Sports: {j('sports')}; teams: {j('teams')}; leagues: {j('leagues')}\n"
        f"- Preparing for roles: {j('interview_roles')}\n"
        f"- Section priorities: {priorities}\n"
        f"- Other interests: {prefs.get('extra_interests') or '—'}"
    )


# ─── low-level call helpers ──────────────────────────────────────────────────
def _create(client, ai: AISettings, budget: Budget, **request):
    request.setdefault("model", ai.model)
    request.setdefault("max_tokens", 16000)
    request.setdefault("system", SYSTEM_PROMPT)
    output_config = {"effort": ai.effort, **request.pop("output_config", {})}
    try:
        try:
            # On a policy decline, retry server-side on Anthropic's recommended fallback.
            response = client.beta.messages.create(
                **request, output_config=output_config,
                betas=["server-side-fallback-2026-07-01"], fallbacks="default",
            )
        except anthropic.BadRequestError as exc:
            log.info("Retrying without fallbacks (%s)", exc.message)
            response = client.beta.messages.create(**request, output_config=output_config)
    except anthropic.APIStatusError as exc:
        raise EditorError(f"API error {exc.status_code}: {exc.message}") from exc
    except anthropic.APIConnectionError as exc:
        raise EditorError(f"connection error: {exc}") from exc
    budget.add(request["model"], response.usage)
    if response.stop_reason == "refusal":
        raise EditorError("model declined the request")
    if response.stop_reason == "max_tokens":
        raise EditorError("response was cut off (max_tokens)")
    return response


def _ask_json(client, ai: AISettings, budget: Budget, prompt: str, schema: dict) -> dict:
    if isinstance(client, GeminiClient):
        try:
            data, usage = client.ask_json(SYSTEM_PROMPT, prompt, schema)
        except GeminiError as exc:
            raise EditorError(str(exc)) from exc
        budget.add_free(usage)
        return data
    response = _create(
        client, ai, budget,
        messages=[{"role": "user", "content": prompt}],
        output_config={"format": {"type": "json_schema", "schema": schema}},
    )
    text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise EditorError(f"invalid JSON from model: {exc}") from exc


# ─── section curation ────────────────────────────────────────────────────────
def format_cluster(c: Cluster, max_items: int = 4) -> str:
    arts = c.unique_articles()
    latest = c.latest.strftime("%Y-%m-%d %H:%M UTC") if c.latest else "unknown"
    lines = [f"[{c.id}] {len(c.sources)} outlet(s) · latest {latest}"]
    for a in arts[:max_items]:
        when = a["published_at"].strftime("%H:%M") if a.get("published_at") else "--:--"
        snippet = f" — {a['snippet']}" if a.get("snippet") else ""
        lines.append(f"  - {a['source']} ({when}): {a['title']}{snippet}")
    if len(arts) > max_items:
        lines.append(f"  - …and {len(arts) - max_items} more reports")
    return "\n".join(lines)


def curate_section(client, ai: AISettings, budget: Budget, prefs: dict, category, depth: str,
                   max_stories: int, clusters: list[Cluster], extra_context: str = "") -> dict:
    must_be_major = max_stories <= 1
    instructions = [
        reader_profile(prefs),
        f"Section: {category.emoji} {category.name}\nSection brief: {category.focus}",
        f"Choose up to {max_stories} stories from the candidate clusters below, most important "
        "first. Each cluster groups reports of one development from several outlets; more "
        "outlets usually means more significant. Always include globally significant "
        "developments even if they fall outside the reader's stated interests; beyond that, "
        "favour the reader's countries, industries, teams and roles. Skip promotions, "
        "listicles, gossip, opinion pieces presented as news, and stale items.",
    ]
    if must_be_major:
        instructions.append("The reader has de-prioritised this section: include a story only if it "
                            "is genuinely major news; otherwise return an empty stories list.")
    instructions += [
        "Refer to each story by its [cluster_id] exactly as given. Write a clear, informative, "
        "non-clickbait headline. `importance` is 1-10 for global significance.",
        DEPTH_GUIDE[depth],
        "`intro`: one or two sentences on what defines this section today.",
        "`concept`: one foundational idea, framework or term connected to today's stories that "
        "is worth knowing cold for interviews — explain simply, give a concrete example, then "
        "a practice question and an outline answer.",
    ]
    if category.slug == "interview":
        instructions.append(
            "This is the Interview Intelligence section. For every story, apply a consulting "
            "lens: what it means for companies, markets and strategy; which frameworks apply "
            "(e.g. Porter's five forces, value chain, market entry, pricing, M&A rationale); "
            "and give case-style interview questions with structured answer outlines. Treat "
            "every story at DEEP depth."
        )
    if extra_context:
        instructions.append(extra_context)
    instructions.append("Candidate clusters:\n\n" + "\n\n".join(format_cluster(c) for c in clusters))
    return _ask_json(client, ai, budget, "\n\n".join(instructions), SECTION_SCHEMA)


# ─── front page ──────────────────────────────────────────────────────────────
def front_page(client, ai: AISettings, budget: Budget, prefs: dict, stories: list[dict],
               n_top: int = 10) -> dict:
    listing = "\n".join(
        f"[{s['id']}] ({s['category']}, importance {s['importance']}, {len(s['sources'])} sources) "
        f"{s['headline']} — {s['summary']}"
        for s in stories
    )
    prompt = (
        f"{reader_profile(prefs)}\n\n"
        "These are today's edited stories, by id:\n\n"
        f"{listing}\n\n"
        f"Build the front page. `lead_story_id`: the single most significant story of the day. "
        f"`top_story_ids`: the next {n_top} most important stories, in order, spanning several "
        "sections (no more than 3 from one section), always including the day's globally "
        "significant developments and otherwise reflecting the reader's priorities. Use only "
        "ids from the list.\n\n"
        "`lead_note`: a 3-4 sentence 'big picture' opener addressed to the reader that connects "
        "the main threads of the day. Only use facts in the list.\n\n"
        f"`quiz`: {ai.quiz_questions} multiple-choice questions that test understanding of "
        "today's stories (not trivia), 4 options each, the 0-based `answer_index`, and a "
        "one-sentence explanation. Only use facts in the list."
    )
    return _ask_json(client, ai, budget, prompt, FRONT_SCHEMA)


# ─── deep dives ──────────────────────────────────────────────────────────────
def deep_dive(client, ai: AISettings, budget: Budget, prefs: dict, story: dict) -> dict:
    sources = "\n".join(
        f"- {s['source']}: {s['title']} ({s['url']})" + (f" — {s['snippet']}" if s.get("snippet") else "")
        for s in story["sources"]
    )
    research = (
        f"Use web search (up to {ai.web_search_max_uses} searches) to find additional reliable "
        "reporting on this story from reputable outlets, official statements or primary data. "
        if ai.web_search else ""
    )
    prompt = (
        f"{reader_profile(prefs)}\n\n"
        f"Write a deep dive on this story for the reader.\n\nHeadline: {story['headline']}\n"
        f"Summary so far: {story['summary']}\n\nReporting we have:\n{sources}\n\n"
        f"{research}Then call `publish_deep_dive` once with:\n"
        "- what_happened: 1-2 paragraphs strictly on what has been reported, attributing claims "
        "to outlets where they differ.\n"
        "- background: 1-2 paragraphs of context (history, how it works, key actors).\n"
        "- why_it_matters: 1 paragraph.\n"
        "- perspectives: 2-4 distinct viewpoints, each labelled with who holds it.\n"
        "- implications: 1 paragraph on plausible consequences, framed as analysis.\n"
        "- what_to_watch: 2-4 upcoming decisions, dates or indicators, as short sentences.\n"
        "- timeline: key dated events if known from the reporting (may be empty).\n"
        "- sources_used: the URLs you relied on (from the list above or your searches).\n"
        "Never invent facts or figures; if something is uncertain, say so."
    )
    if isinstance(client, GeminiClient):
        # Free tier: no web research; the dive is grounded in the reporting we fetched.
        prompt = prompt.replace(research, "").replace(
            "Then call `publish_deep_dive` once with:", "Return JSON with:")
        result = _ask_json(client, ai, budget, prompt, DEEP_DIVE_TOOL["input_schema"])
        known = {s["url"]: s["title"] for s in story["sources"]}
        result["citations"] = [{"url": u, "title": known[u]} for u in result.pop("sources_used", []) if u in known]
        return result

    tools: list[dict] = [DEEP_DIVE_TOOL]
    if ai.web_search:
        tools.insert(0, {"type": "web_search_20260209", "name": "web_search",
                         "max_uses": ai.web_search_max_uses})

    user_turn = {"role": "user", "content": prompt}
    messages: list = [user_turn]
    assistant_so_far: list = []
    found_urls: dict[str, str] = {}
    for _ in range(5):                              # resume server-tool pauses at most 4 times
        response = _create(client, ai, budget, messages=messages, tools=tools,
                           tool_choice={"type": "auto"})
        assistant_so_far += list(response.content)
        for block in response.content:
            if block.type == "web_search_tool_result" and isinstance(block.content, list):
                for r in block.content:
                    if getattr(r, "url", None):
                        found_urls[r.url] = getattr(r, "title", "") or r.url
            if block.type == "tool_use" and block.name == "publish_deep_dive":
                result = dict(block.input)
                known = {s["url"]: s["title"] for s in story["sources"]} | found_urls
                result["citations"] = [
                    {"url": u, "title": known[u]} for u in result.pop("sources_used", []) if u in known
                ]
                return result
        if response.stop_reason == "pause_turn":
            messages = [user_turn, {"role": "assistant", "content": assistant_so_far}]
            continue
        break
    raise EditorError("model finished without publishing a deep dive")
