import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ErrorBox, Loading } from "../components/ui";
import { prepMaterial, useData } from "../lib/api";
import { shortDate } from "../lib/format";
import { useUser } from "../lib/user";

interface Card {
  key: string;
  kind: "Question" | "Concept" | "Term" | "Talking point";
  category: string;
  date: string;
  prompt: string;
  answer: string;
  context: string;
  storyId?: number;
}

const KINDS: Card["kind"][] = ["Question", "Concept", "Term", "Talking point"];

export function PrepPage() {
  const { categories, known, toggleKnown } = useUser();
  const { data, error, loading } = useData("prep", prepMaterial);
  const [q, setQ] = useState("");
  const [cat, setCat] = useState("");
  const [kind, setKind] = useState("");
  const [hideKnown, setHideKnown] = useState(false);
  const [seed, setSeed] = useState(0);

  const cards = useMemo(() => {
    const out: Card[] = [];
    for (const s of data?.stories ?? []) {
      const date = s.edition?.edition_date ?? "";
      s.interview.forEach((it) => out.push({ key: `q:${s.id}:${it.question}`, kind: "Question", category: s.category, date, prompt: it.question, answer: it.answer, context: s.headline, storyId: s.id }));
      if (s.talking_point) out.push({ key: `t:${s.id}`, kind: "Talking point", category: s.category, date, prompt: s.headline, answer: s.talking_point, context: s.summary, storyId: s.id });
      s.key_terms.forEach((t) => out.push({ key: `k:${t.term.toLowerCase()}`, kind: "Term", category: s.category, date, prompt: t.term, answer: t.definition, context: s.headline, storyId: s.id }));
    }
    for (const sec of data?.sections ?? []) {
      const c = sec.concept!;
      const date = sec.edition?.edition_date ?? "";
      out.push({ key: `c:${c.name.toLowerCase()}`, kind: "Concept", category: sec.category, date, prompt: c.name, answer: `${c.explanation}${c.example ? `\n\nExample: ${c.example}` : ""}`, context: "" });
      if (c.question) out.push({ key: `cq:${c.name.toLowerCase()}`, kind: "Question", category: sec.category, date, prompt: c.question, answer: c.answer, context: `Concept: ${c.name}` });
    }
    const unique = [...new Map(out.map((c) => [c.key, c])).values()];
    if (seed) unique.sort((a, b) => ((hash(a.key + seed) - hash(b.key + seed))));
    return unique;
  }, [data, seed]);

  const shown = cards.filter((c) =>
    (!cat || c.category === cat) && (!kind || c.kind === kind) && (!hideKnown || !known.has(c.key)) &&
    (!q || `${c.prompt} ${c.answer} ${c.context}`.toLowerCase().includes(q.toLowerCase())));

  return (
    <>
      <header className="section-masthead">
        <h1>Interview prep</h1>
        <p className="muted">{cards.length} questions, concepts, terms and talking points from every edition. Answer out loud before you reveal.
          {known.size > 0 && ` You've marked ${known.size} as known.`}</p>
      </header>
      <div className="filters">
        <input type="search" placeholder="Search…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search prep" />
        <select value={cat} onChange={(e) => setCat(e.target.value)} aria-label="Section">
          <option value="">All sections</option>
          {categories.map((c) => <option key={c.slug} value={c.slug}>{c.emoji} {c.name}</option>)}
        </select>
        <select value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Type">
          <option value="">Everything</option>
          {KINDS.map((k) => <option key={k}>{k}</option>)}
        </select>
        <button type="button" className="button" onClick={() => setSeed(Date.now())}>Shuffle</button>
        <label className="check"><input type="checkbox" checked={hideKnown} onChange={(e) => setHideKnown(e.target.checked)} /> Hide known</label>
      </div>
      {loading && !data && <Loading />}
      {error && <ErrorBox message={error} />}
      <p className="meta">{shown.length} shown</p>
      <ol className="prep-grid">
        {shown.slice(0, 150).map((c) => (
          <li key={c.key} className={`prep-card ${known.has(c.key) ? "known" : ""}`}>
            <div className="prep-meta"><span className="chip">{c.kind}</span>
              <span>{categories.find((x) => x.slug === c.category)?.name ?? c.category}{c.date && ` · ${shortDate(c.date)}`}</span></div>
            <p className="prep-prompt">{c.prompt}</p>
            {c.context && <p className="muted small">{c.context}</p>}
            <details className="qa"><summary>Reveal</summary><p>{c.answer}</p>
              {c.storyId && <Link to={`/story/${c.storyId}`}>Open the story →</Link>}</details>
            <button type="button" className="chip-btn" onClick={() => toggleKnown(c.key)}>{known.has(c.key) ? "✓ Known" : "I know this"}</button>
          </li>
        ))}
      </ol>
    </>
  );
}

function hash(s: string) {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (Math.imul(31, h) + s.charCodeAt(i)) | 0;
  return h;
}
