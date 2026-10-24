import { useEffect } from "react";
import { Link, useParams } from "react-router-dom";
import { BookmarkButton, ErrorBox, ExternalLink, Img, Kicker, Loading, Reveal } from "../components/ui";
import { story as loadStory, storyUpdates, useData } from "../lib/api";
import { ago, dateTime, host, longDate } from "../lib/format";
import { useUser } from "../lib/user";

function Block({ title, text, badge }: { title: string; text?: string; badge?: "Reported" | "Analysis" | "Context" }) {
  if (!text) return null;
  return (
    <section className="dive-block">
      <h2>{title} {badge && <span className={`badge ${badge.toLowerCase()}`}>{badge}</span>}</h2>
      {text.split(/\n{2,}/).map((p, i) => <p key={i}>{p}</p>)}
    </section>
  );
}

export function StoryPage() {
  const id = Number(useParams().id);
  const { markRead } = useUser();
  const { data: s, error, loading } = useData(`story:${id}`, () => loadStory(id), [id]);
  const updates = useData(`updates:${id}`, () => storyUpdates(id), [id]);

  useEffect(() => {
    if (s) markRead(s.id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [s?.id]);

  if (loading && !s) return <Loading />;
  if (error) return <ErrorBox message={error} />;
  if (!s) return <div className="notice"><h2>Story not found</h2><Link to="/">Back to the front page</Link></div>;

  const dive = s.deep_dive;
  const outlets = [...new Set(s.sources.map((x) => x.source))];
  const share = () => {
    const url = window.location.href;
    if (navigator.share) navigator.share({ title: s.headline, url }).catch(() => undefined);
    else navigator.clipboard?.writeText(url);
  };

  return (
    <article className="story-page">
      <header>
        <Kicker slug={s.category} />
        <h1>{s.headline}</h1>
        <p className="meta">
          {s.edition && <><Link to={`/edition/${s.edition.edition_date}`}>{longDate(s.edition.edition_date)}</Link> · </>}
          Based on {s.sources.length} report{s.sources.length === 1 ? "" : "s"} from {outlets.slice(0, 4).join(", ")}
          {s.published_at && <> · latest {dateTime(s.published_at)}</>}
        </p>
        <div className="story-actions">
          <BookmarkButton id={s.id} />
          <button type="button" className="icon-btn" onClick={share}>↗ Share</button>
          <ExternalLink url={s.primary_url}>Read the original at {host(s.primary_url)} →</ExternalLink>
        </div>
      </header>

      <Img src={s.image_url} alt="" credit={s.image_source} className="hero" />
      {s.summary && <p className="standfirst">{s.summary}</p>}

      {(updates.data ?? []).length > 0 && (
        <aside className="box developing">
          <h2 className="label">Developing · newer reporting since this edition</h2>
          <ul className="latest">
            {(updates.data ?? []).map((a) => (
              <li key={a.id}><ExternalLink url={a.url}>{a.title}</ExternalLink>
                <span className="meta">{a.source} · {ago(a.published_at || a.fetched_at)}</span></li>
            ))}
          </ul>
        </aside>
      )}

      {dive ? (
        <>
          <Block title="What happened" text={dive.what_happened} badge="Reported" />
          <Block title="Background" text={dive.background} badge="Context" />
          <Block title="Why it matters" text={dive.why_it_matters} badge="Analysis" />
          {dive.perspectives.length > 0 && (
            <section className="dive-block">
              <h2>Different perspectives <span className="badge analysis">Analysis</span></h2>
              <div className="perspective-grid">
                {dive.perspectives.map((p, i) => <div key={i} className="perspective"><h3>{p.label}</h3><p>{p.view}</p></div>)}
              </div>
            </section>
          )}
          <Block title="Implications" text={dive.implications} badge="Analysis" />
          <Block title="What to watch" text={dive.what_to_watch} badge="Analysis" />
          {dive.timeline.length > 0 && (
            <section className="dive-block">
              <h2>Timeline</h2>
              <ol className="timeline">{dive.timeline.map((t, i) => <li key={i}><strong>{t.date}</strong> {t.event}</li>)}</ol>
            </section>
          )}
        </>
      ) : (
        <>
          <Block title="Why it matters" text={s.why_it_matters} badge="Analysis" />
          <Block title="Background" text={s.background} badge="Context" />
          {s.perspectives.length > 0 && (
            <section className="dive-block">
              <h2>Different perspectives <span className="badge analysis">Analysis</span></h2>
              <div className="perspective-grid">
                {s.perspectives.map((p, i) => <div key={i} className="perspective"><h3>{p.label}</h3><p>{p.view}</p></div>)}
              </div>
            </section>
          )}
          <Block title="Implications" text={s.implications} badge="Analysis" />
        </>
      )}

      {s.key_terms.length > 0 && (
        <section className="dive-block">
          <h2>Key terms</h2>
          <dl className="terms">{s.key_terms.map((t) => <div key={t.term}><dt>{t.term}</dt><dd>{t.definition}</dd></div>)}</dl>
        </section>
      )}

      {(s.interview.length > 0 || s.talking_point) && (
        <section className="dive-block interview">
          <h2>Interview corner</h2>
          {s.interview.map((q, i) => <Reveal key={i} question={q.question} answer={q.answer} />)}
          {s.talking_point && <p className="talking"><span>Your talking point</span>{s.talking_point}</p>}
        </section>
      )}

      <section className="dive-block sources">
        <h2>Original reporting</h2>
        <ul>
          {s.sources.map((src) => (
            <li key={src.url}>
              <ExternalLink url={src.url}>{src.title}</ExternalLink>
              <span className="meta">{src.source}{src.published_at && ` · ${dateTime(src.published_at)}`}</span>
            </li>
          ))}
        </ul>
        {dive && dive.citations.length > 0 && (
          <>
            <h3>Further reporting used in this deep dive</h3>
            <ul>
              {dive.citations.filter((c) => !s.sources.some((x) => x.url === c.url)).map((c) => (
                <li key={c.url}><ExternalLink url={c.url}>{c.title || host(c.url)}</ExternalLink> <span className="meta">{host(c.url)}</span></li>
              ))}
            </ul>
          </>
        )}
        <p className="meta">The summary, background and analysis above are written by an AI editor from these sources.
          “Reported” sections restate the reporting; “Analysis” sections are interpretation, not fact.</p>
      </section>
    </article>
  );
}
