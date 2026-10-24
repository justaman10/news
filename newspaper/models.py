"""The data stored for each edition (editions/YYYY-MM-DD.json)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class KeyTerm(BaseModel):
    term: str
    definition: str


class InterviewQuestion(BaseModel):
    question: str
    answer_hint: str


class Story(BaseModel):
    headline: str
    link: str
    source: str
    published: str | None = None
    summary: str = ""
    why_it_matters: str = ""
    background: str = ""
    key_terms: list[KeyTerm] = Field(default_factory=list)
    interview_questions: list[InterviewQuestion] = Field(default_factory=list)
    talking_point: str = ""


class Concept(BaseModel):
    name: str
    explanation: str
    example: str = ""
    interview_question: str = ""
    answer_hint: str = ""


class Section(BaseModel):
    name: str
    slug: str
    depth: str
    stories: list[Story] = Field(default_factory=list)
    concept: Concept | None = None


class QuizItem(BaseModel):
    question: str
    options: list[str]
    answer_index: int
    explanation: str = ""


class Edition(BaseModel):
    date: str
    title: str
    tagline: str = ""
    reader_name: str = ""
    generated_at: str
    ai: bool = False
    lead_note: str = ""
    sections: list[Section] = Field(default_factory=list)
    quiz: list[QuizItem] = Field(default_factory=list)

    def links(self) -> set[str]:
        return {s.link for sec in self.sections for s in sec.stories}
