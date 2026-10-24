import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Quiz } from "../components/Quiz";
import { BookmarkButton, ErrorBox, Img, Loading, Reveal, SectionHead, SourceLine } from "../components/ui";
import { editionByDate, editionSections, editionStories, latestEdition, useData } from "../lib/api";
import type { Concept, Story } from "../lib/types";
import { orderedCategories, useUser } from "../lib/user";
import { Masthead } from "./Front";

type Reading = "quick" | "standard" | "full";

function readingDefault(): Reading {
  try {
    return (localStorage.getItem("reading") as Reading) || "standard";
  } catch {
    return "standard";
  }
}

export function ConceptBox({ concept }: { concept: Concept }) {
  return (
    <aside className="concept">
      <h3 className="label">Concept of the day</h3>
      <h4>{concept.name}</h4>
      <p>{concept.explanation}</p>
      {concept.example && <p className="muted"><em>Example:</em> {concept.example}</p>}
      {concept.question && <Reveal question={concept.question} answer={concept.answer} />}
    </aside>
  );
}

export function EditionStory({ s, reading }: { s: Story; reading: Reading }) {
  const [open, setOpen] = useState(false);
  const full = reading === "full" || open;
  const hasMore = Boolean(s.background || s.perspectives.length || s.implications || s.key_terms.length || s.interview.length);
  return (
    <article className={`edition-story depth-${s.depth}`}>
      <Img src={s.image_url} alt="" className="thumb" />
      <div>
        <h3><Link to={`/story/${s.id}`}>{s.headline}</Link> <BookmarkButton id={s.id} compact /></h3>
        <SourceLine story={s} />
        {s.summary && <p>{s.summary}</p>}
        {reading !== "quick" && s.why_it_matters && <p className="why"><strong>Why it matters.</strong> {s.why_it_matters}</p>}
        {full && (
          <>
            {s.background && <p><strong>Background.</strong> {s.background}</p>}
            {s.perspectives.length > 0 && (
              <ul className="perspectives">{s.perspectives.map((p, i) => <li key={i}><strong>{p.label}:</strong> {p.view}</li>)}</ul>
            )}
            {s.implications && <p><strong>Implications.</strong> {s.implications}</p>}
            {s.key_terms.length > 0 && (
              <dl className="terms">{s.key_terms.map((t) => <div key={t.term}><dt>{t.term}</dt><dd>{t.definition}</dd></div>)}</dl>
            )}
            {s.interview.length > 0 && (
              <div className="interview">
                <h4 className="label">Interview corner</h4>
                {s.interview.map((q, i) => <Reveal key={i} question={q.question} answer={q.answer} />)}
                {s.talking_point && <p className="talking"><span>Your talking point</span>{s.talking_point}</p>}
              </div>
            )}
          </>
        )}
        <div className="story-actions">
          {hasMore && reading !== "full" && (
            <button type="button" className="link-btn" onClick={() => setOpen(!open)}>{open ? "Show less" : "Read more"}</button>
          )}
          <Link className="more" to={`/story/${s.id}`}>{s.has_dive ? "Deep dive →" : "Full story →"}</Link>
        </div>
      </div>
    </article>
  );
}

export function EditionPage() {
  const { date } = useParams();
  const { categories, prefs } = useUser();
  const [reading, setReading] = useState<Reading>(readingDefault);
  const ed = useData(`edition:${date ?? "latest"}`, () => (date ? editionByDate(date) : latestEdition()), [date]);
  const edition = ed.data ?? null;
  const st = useData(`stories:${edition?.id}`, () => (edition ? editionStories(edition.id) : Promise.resolve([])), [edition?.id]);
  const secs = useData(`sections:${edition?.id}`, () => (edition ? editionSections(edition.id) : Promise.resolve([])), [edition?.id]);

  if (ed.loading && !edition) return <Loading />;
  if (ed.error) return <ErrorBox message={ed.error} />;
  if (!edition) return <div className="notice"><h2>No edition for this date</h2><Link to="/archive">Browse the archive →</Link></div>;

  const choose = (r: Reading) => {
    setReading(r);
    try { localStorage.setItem("reading", r); } catch { /* ignore */ }
  };
  const stories = st.data ?? [];
  const sections = secs.data ?? [];

  return (
    <>
      <Masthead edition={edition} />
      <div className="toolbar">
        <span className="muted">Reading depth</span>
        <div className="segmented" role="radiogroup" aria-label="Reading depth">
          {(["quick", "standard", "full"] as Reading[]).map((r) => (
            <button key={r} role="radio" aria-checked={reading === r} onClick={() => choose(r)}>{r[0].toUpperCase() + r.slice(1)}</button>
          ))}
        </div>
      </div>
      <nav className="contents" aria-label="In this edition">
        {orderedCategories(categories, prefs).map((c) => {
          const n = stories.filter((s) => s.category === c.slug).length;
          return n ? <a key={c.slug} href={`#sec-${c.slug}`} onClick={(e) => { e.preventDefault(); document.getElementById(`sec-${c.slug}`)?.scrollIntoView({ behavior: "smooth" }); }}>{c.emoji} {c.name} <span>{n}</span></a> : null;
        })}
      </nav>
      {st.loading && !stories.length && <Loading />}
      {orderedCategories(categories, prefs).map((c) => {
        const items = stories.filter((s) => s.category === c.slug);
        const sec = sections.find((x) => x.category === c.slug);
        if (!items.length) return null;
        return (
          <section key={c.slug} id={`sec-${c.slug}`} className="section">
            <SectionHead title={`${c.emoji} ${c.name}`} to={`/section/${c.slug}`} />
            {sec?.intro && <p className="intro">{sec.intro}</p>}
            {items.map((s) => <EditionStory key={s.id} s={s} reading={reading} />)}
            {sec?.concept && <ConceptBox concept={sec.concept} />}
          </section>
        );
      })}
      {edition.quiz.length > 0 && (
        <section className="section">
          <SectionHead title="Daily quiz" />
          <Quiz items={edition.quiz} />
        </section>
      )}
    </>
  );
}
