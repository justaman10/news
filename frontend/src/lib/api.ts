import { useEffect, useState } from "react";
import { supabase } from "./supabase";
import type {
  Article, CategoryInfo, Edition, JobStatus, Prefs, Section, SportsEvent, Story,
} from "./types";

// List views skip the large deep-dive body; `has_dive` tells us one exists.
const STORY_LIST =
  "id, edition_id, category, rank, depth, headline, summary, why_it_matters, background, perspectives, " +
  "implications, key_terms, interview, talking_point, importance, image_url, image_source, primary_url, " +
  "sources, published_at, has_dive:deep_dive->>what_happened";

function check<T>(result: { data: T | null; error: { message: string } | null }): T {
  if (result.error) throw new Error(result.error.message);
  return result.data as T;
}

export async function siteConfig(): Promise<{ categories: CategoryInfo[]; default_prefs: Prefs }> {
  const rows = check(await supabase.from("site_config").select("key, value"));
  const map = Object.fromEntries(rows.map((r: { key: string; value: unknown }) => [r.key, r.value]));
  return { categories: (map.categories as CategoryInfo[]) ?? [], default_prefs: map.default_prefs as Prefs };
}

export async function latestEdition(): Promise<Edition | null> {
  const rows = check(await supabase.from("editions").select("*").order("edition_date", { ascending: false }).limit(1));
  return (rows[0] as Edition) ?? null;
}

export async function editionByDate(date: string): Promise<Edition | null> {
  const rows = check(await supabase.from("editions").select("*").eq("edition_date", date).limit(1));
  return (rows[0] as Edition) ?? null;
}

export async function editionStories(editionId: number): Promise<Story[]> {
  return check(await supabase.from("stories").select(STORY_LIST).eq("edition_id", editionId)
    .order("category").order("rank")) as unknown as Story[];
}

export async function editionSections(editionId: number): Promise<Section[]> {
  return check(await supabase.from("sections").select("*").eq("edition_id", editionId)) as Section[];
}

export async function story(id: number): Promise<Story | null> {
  const rows = check(await supabase.from("stories").select("*, edition:editions(edition_date)").eq("id", id).limit(1));
  return (rows[0] as Story) ?? null;
}

export async function storyUpdates(id: number): Promise<Article[]> {
  const rows = check(await supabase.from("story_updates")
    .select("created_at, article:articles(id, url, title, source, published_at, fetched_at)")
    .eq("story_id", id).order("created_at", { ascending: false }).limit(20));
  return (rows as unknown as { article: Article | null }[]).map((r) => r.article).filter(Boolean) as Article[];
}

export async function latestArticles(category: string | null, limit = 30): Promise<Article[]> {
  let q = supabase.from("articles").select("id, url, title, snippet, source, category, image_url, published_at, fetched_at")
    .order("published_at", { ascending: false, nullsFirst: false }).limit(limit * 2);
  if (category) q = q.eq("category", category);
  const rows = check(await q) as Article[];
  const seen = new Set<string>();
  return rows.filter((a) => (seen.has(a.url) ? false : (seen.add(a.url), true))).slice(0, limit);
}

export async function sectionHistory(category: string, excludeEdition: number | undefined): Promise<Story[]> {
  let q = supabase.from("stories").select("id, category, headline, summary, image_url, image_source, sources, published_at, edition_id, edition:editions(edition_date)")
    .eq("category", category).order("id", { ascending: false }).limit(15);
  if (excludeEdition) q = q.neq("edition_id", excludeEdition);
  return check(await q) as unknown as Story[];
}

export async function sportsEvents(): Promise<SportsEvent[]> {
  const from = new Date(Date.now() - 3 * 86400e3).toISOString();
  const to = new Date(Date.now() + 7 * 86400e3).toISOString();
  return check(await supabase.from("sports_events").select("*").gte("starts_at", from).lte("starts_at", to)
    .order("starts_at")) as SportsEvent[];
}

export async function archive(page: number, size = 30): Promise<Edition[]> {
  return check(await supabase.from("editions")
    .select("id, edition_date, number, lead_note, front_page, stats, published_at, ai")
    .order("edition_date", { ascending: false }).range(page * size, page * size + size - 1)) as Edition[];
}

export async function storiesByIds(ids: number[]): Promise<Story[]> {
  if (!ids.length) return [];
  return check(await supabase.from("stories").select("id, headline, category, image_url").in("id", ids)) as Story[];
}

export async function searchStories(query: string): Promise<Story[]> {
  return check(await supabase.from("stories")
    .select("id, category, headline, summary, image_url, published_at, edition:editions(edition_date)")
    .textSearch("search", query, { type: "websearch", config: "english" })
    .order("id", { ascending: false }).limit(50)) as unknown as Story[];
}

export async function prepMaterial(): Promise<{ stories: Story[]; sections: (Section & { edition: { edition_date: string } })[] }> {
  const [stories, sections] = await Promise.all([
    supabase.from("stories")
      .select("id, category, headline, summary, interview, key_terms, talking_point, edition:editions(edition_date)")
      .neq("interview", "[]").order("id", { ascending: false }).limit(400),
    supabase.from("sections").select("*, edition:editions(edition_date)").not("concept", "is", null)
      .order("edition_id", { ascending: false }).limit(200),
  ]);
  return { stories: check(stories) as unknown as Story[], sections: check(sections) as never };
}

export async function jobStatus(): Promise<JobStatus[]> {
  return check(await supabase.from("site_status").select("*")) as JobStatus[];
}

export async function recentRuns() {
  return check(await supabase.from("job_runs").select("*").order("started_at", { ascending: false }).limit(25));
}

export async function feedHealth() {
  return check(await supabase.from("feed_state").select("*").order("category"));
}

// ─── tiny data hook with in-memory caching between page visits ───
const cache = new Map<string, unknown>();

export function useData<T>(key: string, load: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | undefined>(cache.get(key) as T | undefined);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(!cache.has(key));
  useEffect(() => {
    let live = true;
    setLoading(!cache.has(key));
    setData(cache.get(key) as T | undefined);
    load()
      .then((value) => {
        cache.set(key, value);
        if (live) { setData(value); setError(null); }
      })
      .catch((e: Error) => live && setError(e.message || "Could not load"))
      .finally(() => live && setLoading(false));
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, ...deps]);
  return { data, error, loading };
}
