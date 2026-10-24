import { Link, useParams } from "react-router-dom";
import { Scoreboard } from "../components/Scoreboard";
import { ErrorBox, LatestList, Loading, SectionHead, StoryCard } from "../components/ui";
import {
  editionSections, editionStories, latestArticles, latestEdition, sectionHistory, sportsEvents, useData,
} from "../lib/api";
import { shortDate } from "../lib/format";
import { useUser } from "../lib/user";
import { ConceptBox, EditionStory } from "./Edition";

export function SectionPage() {
  const { slug = "" } = useParams();
  const { categories } = useUser();
  const cat = categories.find((c) => c.slug === slug);
  const ed = useData("edition:latest", latestEdition);
  const edition = ed.data ?? null;
  const st = useData(`stories:${edition?.id}`, () => (edition ? editionStories(edition.id) : Promise.resolve([])), [edition?.id]);
  const secs = useData(`sections:${edition?.id}`, () => (edition ? editionSections(edition.id) : Promise.resolve([])), [edition?.id]);
  const latest = useData(`latest:${slug}`, () => latestArticles(cat?.derived ? null : slug, 25), [slug, cat?.derived]);
  const earlier = useData(`history:${slug}:${edition?.id}`, () => sectionHistory(slug, edition?.id), [slug, edition?.id]);
  const sports = useData("sports", sportsEvents, []);

  if (ed.loading && !edition) return <Loading />;
  if (ed.error) return <ErrorBox message={ed.error} />;

  const stories = (st.data ?? []).filter((s) => s.category === slug);
  const sec = (secs.data ?? []).find((s) => s.category === slug);

  return (
    <>
      <header className="section-masthead">
        <h1>{cat ? `${cat.emoji} ${cat.name}` : slug}</h1>
        {cat?.focus && <p className="muted">{cat.focus}</p>}
      </header>

      {slug === "sports" && (
        <section className="section">
          <SectionHead title="Scores & fixtures" />
          <Scoreboard events={sports.data ?? []} />
        </section>
      )}

      <div className="section-grid">
        <div>
          <SectionHead title={edition ? `In today's edition (${shortDate(edition.edition_date)})` : "Today's edition"} />
          {sec?.intro && <p className="intro">{sec.intro}</p>}
          {!stories.length && !st.loading && <p className="muted">No stories from this section in the latest edition.</p>}
          {stories.map((s) => <EditionStory key={s.id} s={s} reading="standard" />)}
          {sec?.concept && <ConceptBox concept={sec.concept} />}

          {(earlier.data ?? []).length > 0 && (
            <>
              <SectionHead title="Earlier this week" />
              <div className="top-list">
                {(earlier.data ?? []).map((s) => (
                  <div key={s.id} className="earlier">
                    <span className="meta">{s.edition ? shortDate(s.edition.edition_date) : ""}</span>
                    <StoryCard story={s} size="sm" showKicker={false} />
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
        <aside>
          <section className="box">
            <h2 className="label">{cat?.derived ? "Latest reporting" : "Latest from our sources"}</h2>
            <p className="meta">Updated every 30 minutes, straight from the publishers.</p>
            <LatestList items={latest.data ?? []} />
          </section>
          {slug === "interview" && (
            <section className="box accent">
              <h2 className="label">Revise</h2>
              <p>Every question, concept and talking point is collected in your <Link to="/prep">interview prep notebook</Link>.</p>
            </section>
          )}
        </aside>
      </div>
    </>
  );
}
