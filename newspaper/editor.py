"""The AI editor: picks the stories that matter and writes them up with Claude.

Every call degrades gracefully: if the API key is missing, a request fails or the
model declines, the section falls back to a plain digest built from the feeds.
"""

from __future__ import annotations

import json
import logging
import os

import anthropic
from pydantic import ValidationError

from .config import AISettings, Reader, Topic
from .fetch import Article
from .models import Concept, InterviewQuestion, KeyTerm, QuizItem, Section, Story

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are the editor of a one-reader newspaper. Your reader wants two things from \
every edition: to genuinely understand what happened in the world today, and to \
build up knowledge they can use in job interviews.

Editorial standards:
- Choose stories by real significance and by relevance to the reader's goals and \
target roles. Skip promotions, deals, listicles, gossip and near-duplicates.
- Report only what the source material supports. You may add widely known \
background (how a technology works, who the players are, historical context), but \
never invent figures, quotes or events. If the snippet is thin, say less rather \
than speculate.
- Write plainly and concretely, like a sharp briefing from a well-read colleague. \
No hype, no filler, no "In today's fast-paced world".
- Interview questions should be ones a real interviewer for the reader's target \
roles might ask, and answer hints should be structured outlines (a framework, the \
key trade-offs, what a strong answer mentions) rather than full scripts.
"""

DEPTH_GUIDE = {
    "headlines": (
        "Depth: HEADLINES. For each story write `summary` as one sentence (max 25 "
        "words). Leave why_it_matters, background and talking_point as empty "
        "strings, and key_terms and interview_questions as empty lists. Keep the "
        "concept short (2-3 sentences) with one interview question."
    ),
    "brief": (
        "Depth: BRIEF. For each story: `summary` 2-3 sentences; `why_it_matters` "
        "1-2 sentences; 0-2 key_terms for jargon the reader may not know; exactly "
        "1 interview question with a short answer hint. Leave background and "
        "talking_point as empty strings."
    ),
    "deep": (
        "Depth: DEEP. For each story: `summary` 3-5 sentences on what happened; "
        "`why_it_matters` 2-3 sentences including second-order effects; "
        "`background` 3-5 sentences of context (how it works, history, key "
        "players) so the reader could explain it to someone else; 2-4 key_terms; "
        "2-3 interview_questions with structured answer hints; `talking_point` "
        "a crisp 1-2 sentence, defensible opinion the reader could voice in an "
        "interview."
    ),
}

_STR = {"type": "string"}

SECTION_SCHEMA = {
    "type": "object",
    "properties": {
        "stories": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": _STR,
                    "headline": _STR,
                    "summary": _STR,
                    "why_it_matters": _STR,
                    "background": _STR,
                    "key_terms": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"term": _STR, "definition": _STR},
                            "required": ["term", "definition"],
                            "additionalProperties": False,
                        },
                    },
                    "interview_questions": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"question": _STR, "answer_hint": _STR},
                            "required": ["question", "answer_hint"],
                            "additionalProperties": False,
                        },
                    },
                    "talking_point": _STR,
                },
                "required": [
                    "id", "headline", "summary", "why_it_matters", "background",
                    "key_terms", "interview_questions", "talking_point",
                ],
                "additionalProperties": False,
            },
        },
        "concept": {
            "type": "object",
            "properties": {
                "name": _STR,
                "explanation": _STR,
                "example": _STR,
                "interview_question": _STR,
                "answer_hint": _STR,
            },
            "required": ["name", "explanation", "example", "interview_question", "answer_hint"],
            "additionalProperties": False,
        },
    },
    "required": ["stories", "concept"],
    "additionalProperties": False,
}

FRONT_PAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "lead_note": _STR,
        "quiz": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question": _STR,
                    "options": {"type": "array", "items": _STR},
                    "answer_index": {"type": "integer"},
                    "explanation": _STR,
                },
                "required": ["question", "options", "answer_index", "explanation"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["lead_note", "quiz"],
    "additionalProperties": False,
}


class EditorError(Exception):
    pass


def make_client() -> anthropic.Anthropic | None:
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        log.warning("ANTHROPIC_API_KEY is not set; building a plain digest without AI.")
        return None
    return anthropic.Anthropic(max_retries=3)


def _reader_profile(reader: Reader) -> str:
    roles = ", ".join(reader.target_roles) or "not specified"
    return (
        f"Reader: {reader.name}\nGoal: {reader.goal}\nBackground: {reader.background}\n"
        f"Target roles: {roles}\nRegion of interest: {reader.region}"
    )


def _ask(client: anthropic.Anthropic, ai: AISettings, prompt: str, schema: dict) -> dict:
    request = dict(
        model=ai.model,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
        output_config={"effort": ai.effort, "format": {"type": "json_schema", "schema": schema}},
    )
    try:
        try:
            # If the model declines, retry server-side on Anthropic's recommended fallback.
            response = client.beta.messages.create(
                **request, betas=["server-side-fallback-2026-07-01"], fallbacks="default"
            )
        except anthropic.BadRequestError as exc:
            # e.g. a custom `model` that doesn't support fallbacks — try a plain request.
            log.info("Retrying without fallbacks (%s)", exc.message)
            response = client.beta.messages.create(**request)
    except anthropic.APIStatusError as exc:
        raise EditorError(f"API error {exc.status_code}: {exc.message}") from exc
    except anthropic.APIConnectionError as exc:
        raise EditorError(f"connection error: {exc}") from exc

    if response.stop_reason == "refusal":
        raise EditorError("model declined the request")
    if response.stop_reason == "max_tokens":
        raise EditorError("response was cut off (max_tokens)")
    text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise EditorError(f"invalid JSON from model: {exc}") from exc


def _format_candidates(candidates: list[Article]) -> str:
    lines = []
    for art in candidates:
        when = art.published.strftime("%Y-%m-%d %H:%M UTC") if art.published else "unknown time"
        lines.append(
            f"[{art.id}] {art.title}\n  source: {art.source} · {when}\n  snippet: {art.snippet or '(none)'}"
        )
    return "\n\n".join(lines)


def _iso(art: Article) -> str | None:
    return art.published.isoformat() if art.published else None


def plain_section(topic: Topic, candidates: list[Article]) -> Section:
    """A no-AI section: the top-ranked items with their feed snippets."""
    stories = []
    for art in candidates[: topic.max_stories]:
        summary = art.snippet
        if len(summary) > 280:
            summary = summary[:280].rsplit(" ", 1)[0] + "…"
        stories.append(
            Story(headline=art.title, link=art.link, source=art.source,
                  published=_iso(art), summary=summary)
        )
    return Section(name=topic.name, slug=topic.slug, depth=topic.depth, stories=stories)


def edit_section(
    client: anthropic.Anthropic | None,
    ai: AISettings,
    reader: Reader,
    topic: Topic,
    candidates: list[Article],
) -> Section:
    if client is None or not candidates:
        return plain_section(topic, candidates)

    prompt = (
        f"{_reader_profile(reader)}\n\n"
        f"Section: {topic.name}\n"
        f"Interview angle for this section: {topic.interview_focus or 'general'}\n\n"
        f"Pick up to {topic.max_stories} stories from the candidates below (fewer if "
        "few are worthwhile), ordered most important first. Refer to each by its "
        "[id] exactly as given. Rewrite headlines to be clear and informative.\n\n"
        f"{DEPTH_GUIDE[topic.depth]}\n\n"
        "Also choose one `concept` of the day for this section: a foundational idea, "
        "framework or term connected to today's stories that is worth knowing cold "
        "for interviews. Explain it simply, give a concrete example, and add an "
        "interview question with an answer hint.\n\n"
        f"Candidates:\n\n{_format_candidates(candidates)}"
    )
    try:
        data = _ask(client, ai, prompt, SECTION_SCHEMA)
        by_id = {art.id: art for art in candidates}
        stories = []
        for item in data["stories"]:
            art = by_id.get(item["id"])
            if art is None:
                continue
            stories.append(
                Story(
                    headline=item["headline"] or art.title,
                    link=art.link,
                    source=art.source,
                    published=_iso(art),
                    summary=item["summary"],
                    why_it_matters=item["why_it_matters"],
                    background=item["background"],
                    key_terms=[KeyTerm(**t) for t in item["key_terms"]],
                    interview_questions=[InterviewQuestion(**q) for q in item["interview_questions"]],
                    talking_point=item["talking_point"],
                )
            )
        if not stories:
            raise EditorError("no usable stories in response")
        return Section(
            name=topic.name,
            slug=topic.slug,
            depth=topic.depth,
            stories=stories[: topic.max_stories],
            concept=Concept(**data["concept"]),
        )
    except (EditorError, KeyError, TypeError, ValidationError) as exc:
        log.warning("%s: AI editing failed (%s); using plain digest.", topic.name, exc)
        return plain_section(topic, candidates)


def write_front_page(
    client: anthropic.Anthropic | None,
    ai: AISettings,
    reader: Reader,
    sections: list[Section],
) -> tuple[str, list[QuizItem]]:
    """Returns the editor's note and the end-of-paper quiz."""
    if client is None or not any(s.stories for s in sections):
        return "", []

    digest = "\n\n".join(
        f"## {sec.name}\n"
        + "\n".join(f"- {s.headline}: {s.summary} {s.why_it_matters}".strip() for s in sec.stories)
        for sec in sections
        if sec.stories
    )
    prompt = (
        f"{_reader_profile(reader)}\n\n"
        "Here is today's edition, already written:\n\n"
        f"{digest}\n\n"
        "Write `lead_note`: a 3-4 sentence 'big picture' opener that connects the "
        "most important threads of the day and tells the reader what to pay "
        "attention to. Address the reader directly; don't list every story.\n\n"
        f"Write `quiz`: {ai.quiz_questions} multiple-choice questions testing "
        "understanding (not trivia) of today's stories and concepts, each with 4 "
        "options, the 0-based `answer_index` of the correct one, and a one-sentence "
        "explanation. Use only facts stated above."
    )
    if ai.quiz_questions <= 0:
        prompt += " Return an empty quiz list."
    try:
        data = _ask(client, ai, prompt, FRONT_PAGE_SCHEMA)
        quiz = [
            QuizItem(**q)
            for q in data["quiz"]
            if len(q["options"]) >= 2 and 0 <= q["answer_index"] < len(q["options"])
        ]
        return data["lead_note"], quiz[: max(ai.quiz_questions, 0)]
    except (EditorError, KeyError, TypeError, ValidationError) as exc:
        log.warning("Front page failed (%s); skipping note and quiz.", exc)
        return "", []
