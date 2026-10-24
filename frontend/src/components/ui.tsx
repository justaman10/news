import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { ago, clock, host } from "../lib/format";
import type { Story } from "../lib/types";
import { useUser } from "../lib/user";

export function Loading({ label = "Loading…" }: { label?: string }) {
  return <div className="state" role="status"><span className="spinner" aria-hidden /> {label}</div>;
}

export function ErrorBox({ message }: { message: string }) {
  return (
    <div className="state error" role="alert">
      <strong>Couldn't load this right now.</strong>
      <span>{message}</span>
      <span className="muted">If you're offline, the last copy you opened is shown where available.</span>
    </div>
  );
}

export function Img({ src, alt, credit, className }: { src: string | null; alt: string; credit?: string | null; className?: string }) {
  const [failed, setFailed] = useState(false);
  if (!src || failed) return null;
  return (
    <figure className={`img ${className ?? ""}`}>
      <img src={src} alt={alt} loading="lazy" decoding="async" referrerPolicy="no-referrer" onError={() => setFailed(true)} />
      {credit && <figcaption>Image: {credit}</figcaption>}
    </figure>
  );
}

export function SourceLine({ story }: { story: Story }) {
  const outlets = [...new Set(story.sources.map((s) => s.source))];
  return (
    <p className="meta">
      {outlets.slice(0, 3).join(" · ")}
      {outlets.length > 3 && ` +${outlets.length - 3}`}
      {story.published_at && <> · {clock(story.published_at)}</>}
    </p>
  );
}

export function Kicker({ slug }: { slug: string }) {
  const { categories } = useUser();
  const cat = categories.find((c) => c.slug === slug);
  return <Link className="kicker" to={`/section/${slug}`}>{cat ? `${cat.emoji} ${cat.name}` : slug}</Link>;
}

export function BookmarkButton({ id, compact }: { id: number; compact?: boolean }) {
  const { isBookmarked, toggleBookmark } = useUser();
  const on = isBookmarked(id);
  return (
    <button type="button" className={`icon-btn ${on ? "on" : ""}`} aria-pressed={on}
      aria-label={on ? "Remove bookmark" : "Bookmark"} onClick={(e) => { e.preventDefault(); toggleBookmark(id); }}>
      {on ? "★" : "☆"}{!compact && <span>{on ? " Saved" : " Save"}</span>}
    </button>
  );
}

export function StoryCard({ story, size = "md", showImage = true, showKicker = true }: {
  story: Story; size?: "lg" | "md" | "sm"; showImage?: boolean; showKicker?: boolean;
}) {
  const { hasRead } = useUser();
  return (
    <article className={`card card-${size} ${hasRead(story.id) ? "read" : ""}`}>
      {showImage && size !== "sm" && (
        <Link to={`/story/${story.id}`} tabIndex={-1} aria-hidden>
          <Img src={story.image_url} alt="" credit={size === "lg" ? story.image_source : null} />
        </Link>
      )}
      <div className="card-body">
        <div className="card-top">
          {showKicker && <Kicker slug={story.category} />}
          <BookmarkButton id={story.id} compact />
        </div>
        <h3><Link to={`/story/${story.id}`}>{story.headline}</Link></h3>
        {size !== "sm" && story.summary && <p className="summary">{story.summary}</p>}
        {size === "lg" && story.why_it_matters && (
          <p className="why"><strong>Why it matters.</strong> {story.why_it_matters}</p>
        )}
        <SourceLine story={story} />
        {size === "lg" && (
          <Link className="more" to={`/story/${story.id}`}>{story.has_dive ? "Read the deep dive →" : "Read more →"}</Link>
        )}
      </div>
    </article>
  );
}

export function Reveal({ question, answer }: { question: string; answer: string }) {
  return (
    <details className="qa">
      <summary>{question}</summary>
      <p>{answer}</p>
    </details>
  );
}

export function SectionHead({ title, children, to }: { title: ReactNode; children?: ReactNode; to?: string }) {
  return (
    <header className="section-head">
      <h2>{to ? <Link to={to}>{title}</Link> : title}</h2>
      {children}
    </header>
  );
}

export function ExternalLink({ url, children }: { url: string; children: ReactNode }) {
  return <a href={url} target="_blank" rel="noopener noreferrer">{children}</a>;
}

export function LatestList({ items }: { items: { id: number; url: string; title: string; source: string; published_at: string | null; fetched_at: string }[] }) {
  if (!items.length) return <p className="muted">Nothing new yet.</p>;
  return (
    <ul className="latest">
      {items.map((a) => (
        <li key={a.id}>
          <ExternalLink url={a.url}>{a.title}</ExternalLink>
          <span className="meta">{a.source || host(a.url)} · {ago(a.published_at || a.fetched_at)}</span>
        </li>
      ))}
    </ul>
  );
}
