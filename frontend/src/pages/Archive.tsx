import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ErrorBox, Kicker, Loading } from "../components/ui";
import { archive, searchStories, storiesByIds, useData } from "../lib/api";
import { longDate, shortDate } from "../lib/format";
import type { Edition, Story } from "../lib/types";

function monthOf(date: string) {
  const [y, m] = date.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, 1)).toLocaleDateString("en-GB", { month: "long", year: "numeric", timeZone: "UTC" });
}

function Search() {
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";
  const [text, setText] = useState(q);
  const [results, setResults] = useState<Story[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!q) { setResults(null); return; }
    setResults(null);
    searchStories(q).then(setResults).catch((e: Error) => setError(e.message));
  }, [q]);
  return (
    <section className="search">
      <form onSubmit={(e) => { e.preventDefault(); setParams(text ? { q: text } : {}); }}>
        <input type="search" value={text} onChange={(e) => setText(e.target.value)} placeholder="Search every edition — e.g. “ECB rates”, “Bundesliga”, “semiconductors”" aria-label="Search the archive" />
        <button type="submit">Search</button>
      </form>
      {error && <ErrorBox message={error} />}
      {q && !results && !error && <Loading label="Searching…" />}
      {results && (
        <>
          <p className="meta">{results.length} result{results.length === 1 ? "" : "s"} for “{q}”</p>
          <ul className="results">
            {results.map((s) => (
              <li key={s.id}>
                <Kicker slug={s.category} />
                <Link to={`/story/${s.id}`}>{s.headline}</Link>
                {s.edition && <span className="meta"> · {shortDate(s.edition.edition_date)}</span>}
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

export function ArchivePage() {
  const [pages, setPages] = useState(1);
  const { data, error, loading } = useData(`archive:${pages}`, async () => {
    const all: Edition[] = [];
    for (let p = 0; p < pages; p++) all.push(...(await archive(p)));
    return all;
  }, [pages]);
  const editions = data ?? [];
  const leads = useData(`archive-leads:${editions.length}`, () => storiesByIds(editions.map((e) => e.front_page[0]).filter(Boolean)), [editions.length]);
  const leadById = new Map((leads.data ?? []).map((s) => [s.id, s]));

  const byMonth = new Map<string, Edition[]>();
  for (const e of editions) byMonth.set(monthOf(e.edition_date), [...(byMonth.get(monthOf(e.edition_date)) ?? []), e]);

  return (
    <>
      <header className="section-masthead">
        <h1>Archive</h1>
        <p className="muted">Every edition, kept permanently.</p>
      </header>
      <Search />
      {loading && !editions.length && <Loading />}
      {error && <ErrorBox message={error} />}
      {[...byMonth.entries()].map(([month, eds]) => (
        <section key={month} className="archive-month">
          <h2>{month}</h2>
          <ul className="archive-list">
            {eds.map((e) => {
              const lead = leadById.get(e.front_page[0]);
              return (
                <li key={e.id}>
                  <Link to={`/edition/${e.edition_date}`} className="archive-date">{longDate(e.edition_date)}</Link>
                  <span className="meta">No. {e.number} · {(e.stats?.stories as number) ?? "?"} stories</span>
                  {lead && <p><Link to={`/story/${lead.id}`}>{lead.headline}</Link></p>}
                </li>
              );
            })}
          </ul>
        </section>
      ))}
      {editions.length === pages * 30 && (
        <button type="button" className="button" onClick={() => setPages(pages + 1)}>Load older editions</button>
      )}
    </>
  );
}
