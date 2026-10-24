export type Depth = "headlines" | "brief" | "deep";

export interface Source {
  title: string;
  url: string;
  source: string;
  published_at: string | null;
}

export interface Perspective {
  label: string;
  view: string;
}

export interface DeepDive {
  what_happened: string;
  background: string;
  why_it_matters: string;
  perspectives: Perspective[];
  implications: string;
  what_to_watch: string;
  timeline: { date: string; event: string }[];
  citations: { url: string; title: string }[];
}

export interface Story {
  id: number;
  edition_id: number;
  category: string;
  rank: number;
  depth: Depth;
  headline: string;
  summary: string;
  why_it_matters: string;
  background: string;
  perspectives: Perspective[];
  implications: string;
  key_terms: { term: string; definition: string }[];
  interview: { question: string; answer: string }[];
  talking_point: string;
  importance: number;
  image_url: string | null;
  image_source: string | null;
  primary_url: string;
  sources: Source[];
  published_at: string | null;
  has_dive?: string | null;
  deep_dive?: DeepDive | null;
  edition?: { edition_date: string };
}

export interface QuizItem {
  question: string;
  options: string[];
  answer_index: number;
  explanation: string;
}

export interface Edition {
  id: number;
  edition_date: string;
  number: number;
  ai: boolean;
  lead_note: string;
  quiz: QuizItem[];
  front_page: number[];
  stats: Record<string, unknown>;
  published_at: string;
}

export interface Concept {
  name: string;
  explanation: string;
  example: string;
  question: string;
  answer: string;
}

export interface Section {
  edition_id: number;
  category: string;
  intro: string;
  concept: Concept | null;
}

export interface Article {
  id: number;
  url: string;
  title: string;
  snippet: string;
  source: string;
  category: string;
  image_url: string | null;
  published_at: string | null;
  fetched_at: string;
}

export interface SportsEvent {
  id: string;
  sport: string;
  competition: string;
  starts_at: string;
  status: "scheduled" | "live" | "finished" | "postponed" | "cancelled";
  home: string;
  away: string;
  home_score: string | null;
  away_score: string | null;
  detail: string;
  url: string | null;
  updated_at: string;
}

export interface CategoryInfo {
  slug: string;
  name: string;
  emoji: string;
  focus: string;
  derived: boolean;
}

export interface CategoryPref {
  weight: number;
  depth: Depth;
}

export interface Prefs {
  categories: Record<string, CategoryPref>;
  countries: string[];
  industries: string[];
  sports: string[];
  teams: string[];
  leagues: string[];
  interview_roles: string[];
  extra_interests: string;
}

export interface JobStatus {
  job: string;
  last_success: string | null;
  last_attempt: string | null;
}
