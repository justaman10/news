import { Link } from "react-router-dom";
import { Quiz } from "../components/Quiz";
import { Scoreboard } from "../components/Scoreboard";
import { ErrorBox, LatestList, Loading, SectionHead, StoryCard } from "../components/ui";
import { editionStories, latestArticles, latestEdition, sportsEvents, useData } from "../lib/api";
import { clock, longDate } from "../lib/format";
import type { Edition, Story } from "../lib/types";
import { followTerms, orderedCategories, useUser } from "../lib/user";

export function Masthead({ edition }: { edition: Edition | null }) {
  const today = new Date().toLocaleDateString("en-CA", { timeZone: "Europe/Berlin" });
  return (
    <header className="masthead">
      <div className="dateline">
        <span>{edition ? `No. ${edition.number}` : "First edition coming"}</span>
        <span>{longDate(edition?.edition_date ?? today)}</span>
        <span>{edition ? `Published ${clock(edition.published_at)}` : "06:00 Berlin"}</span>
      </div>
      <h1 className="paper-title">The Daily Brief</h1>
      {edition && edition.edition_date !== today && (
        <p className="stale">This is the edition of {longDate(edition.edition_date)}. Today's edition will appear after 06:00.</p>
      )}
    </header>
  );
}

function pick(stories: Story[], ids: number[]) {
  const byId = new Map(stories.map((s) => [s.id, s]));
  return ids.map((id) => byId.get(id)).filter(Boolean) as Story[];
}

export function FrontPage() {
  const { categories, prefs } = useUser();
  const ed = useData("edition:latest", latestEdition);
  const edition = ed.data ?? null;
  const st = useData(`stories:${edition?.id}`, () => (edition ? editionStories(edition.id) : Promise.resolve([])), [edition?.id]);
  const sports = useData("sports", sportsEvents);
  const latest = useData("latest:all", () => latestArticles(null, 14));

  if (ed.loading && !edition) return <Loading label="Fetching today's paper…" />;
  if (ed.error && !edition) return <ErrorBox message={ed.error} />;

  if (!edition) {
    return (
      <>
        <Masthead edition={null} />
        <div className="notice">
          <h2>Your first edition is on its way</h2>
          <p>The newsroom publishes every morning at 06:00 (Berlin). Until then, here's the latest reporting as it comes in.</p>
        </div>
        <LatestList items={latest.data ?? []} />
      </>
    );
  }

  const stories = st.data ?? [];
  const front = pick(stories, edition.front_page);
  const [lead, ...top] = front;
  const frontIds = new Set(front.map((s) => s.id));
  const terms = followTerms(prefs);
  const forYou = stories
    .filter((s) => !frontIds.has(s.id) && s.category !== "interview")
    .filter((s) => terms.some((t) => `${s.headline} ${s.summary}`.toLowerCase().includes(t)))
    .slice(0, 5);
  const interview = stories.filter((s) => s.category === "interview").slice(0, 3);
  const since = (latest.data ?? []).filter((a) => (a.published_at ?? a.fetched_at) > edition.published_at).slice(0, 8);
  const sections = orderedCategories(categories, prefs).filter((c) => c.slug !== "interview" && (prefs.categories[c.slug]?.weight ?? 2) > 0);

  return (
    <>
      <Masthead edition={edition} />
      {edition.lead_note && (
        <section className="lead-note">
          <h2 className="label">The big picture</h2>
          <p>{edition.lead_note}</p>
        </section>
      )}
      {st.loading && !stories.length && <Loading />}
      {st.error && <ErrorBox message={st.error} />}

      <div className="front-grid">
        <div className="front-main">
          {lead && <StoryCard story={lead} size="lg" />}
          <div className="top-grid">
            {top.slice(0, 4).map((s) => <StoryCard key={s.id} story={s} size="md" />)}
          </div>
          <div className="top-list">
            {top.slice(4).map((s) => <StoryCard key={s.id} story={s} size="sm" />)}
          </div>
        </div>
        <aside className="front-side">
          {forYou.length > 0 && (
            <section className="box">
              <h2 className="label">For you</h2>
              {forYou.map((s) => <StoryCard key={s.id} story={s} size="sm" />)}
            </section>
          )}
          <section className="box">
            <h2 className="label">Since this morning</h2>
            <LatestList items={since} />
          </section>
          <section className="box">
            <h2 className="label"><Link to="/section/sports">Scores</Link></h2>
            <Scoreboard events={sports.data ?? []} compact />
          </section>
          {interview.length > 0 && (
            <section className="box accent">
              <h2 className="label"><Link to="/section/interview">🎯 Interview intelligence</Link></h2>
              {interview.map((s) => <StoryCard key={s.id} story={s} size="sm" showKicker={false} />)}
            </section>
          )}
        </aside>
      </div>

      <h2 className="rule-title">Explore the sections</h2>
      <div className="section-teasers">
        {sections.map((c) => {
          const items = stories.filter((s) => s.category === c.slug && !frontIds.has(s.id)).slice(0, 3);
          if (!items.length) return null;
          return (
            <section key={c.slug} className="teaser">
              <SectionHead title={`${c.emoji} ${c.name}`} to={`/section/${c.slug}`} />
              {items.map((s) => <StoryCard key={s.id} story={s} size="sm" showKicker={false} />)}
              <Link className="more" to={`/section/${c.slug}`}>More {c.name} →</Link>
            </section>
          );
        })}
      </div>

      {edition.quiz.length > 0 && (
        <section className="section">
          <SectionHead title="Daily quiz" />
          <Quiz items={edition.quiz} />
        </section>
      )}
    </>
  );
}
