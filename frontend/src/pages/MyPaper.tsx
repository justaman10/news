import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { dateTime, shortDate } from "../lib/format";
import type { Depth, Prefs } from "../lib/types";
import { useUser } from "../lib/user";

const WEIGHTS = [
  { v: 0, label: "Hide" }, { v: 1, label: "Less" }, { v: 2, label: "Normal" }, { v: 3, label: "More" },
];
const DEPTHS: { v: Depth; label: string }[] = [
  { v: "headlines", label: "Headlines" }, { v: "brief", label: "Brief" }, { v: "deep", label: "Deep" },
];

function Account() {
  const { session, signIn, signUp, signOut, syncError } = useUser();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (session) {
    return (
      <section className="box">
        <h2 className="label">Account</h2>
        <p>Signed in as <strong>{session.user.email}</strong>. Your preferences, bookmarks, reading history and prep progress sync across all your devices.</p>
        {syncError && <p className="error-text">Sync problem: {syncError}</p>}
        <button type="button" className="button secondary" onClick={signOut}>Sign out</button>
      </section>
    );
  }
  const run = async (fn: typeof signIn) => {
    setBusy(true);
    setMessage(await fn(email, password));
    setBusy(false);
  };
  return (
    <section className="box">
      <h2 className="label">Sign in to sync across devices</h2>
      <p className="muted">Without an account, your settings stay on this device only.</p>
      <form className="auth" onSubmit={(e) => { e.preventDefault(); run(signIn); }}>
        <input type="email" autoComplete="email" required placeholder="Email" value={email} onChange={(e) => setEmail(e.target.value)} aria-label="Email" />
        <input type="password" autoComplete="current-password" required minLength={8} placeholder="Password (8+ characters)" value={password} onChange={(e) => setPassword(e.target.value)} aria-label="Password" />
        <div className="row">
          <button type="submit" className="button" disabled={busy}>Sign in</button>
          <button type="button" className="button secondary" disabled={busy} onClick={() => run(signUp)}>Create account</button>
        </div>
        {message && <p className="muted">{message}</p>}
      </form>
    </section>
  );
}

function ListInput({ label, hint, value, onChange }: { label: string; hint: string; value: string[]; onChange: (v: string[]) => void }) {
  const [text, setText] = useState("");
  const add = () => {
    const t = text.trim();
    if (t && !value.includes(t)) onChange([...value, t]);
    setText("");
  };
  return (
    <div className="field">
      <label>{label}</label>
      <div className="chips">
        {value.map((v) => (
          <span key={v} className="chip removable">{v}<button type="button" aria-label={`Remove ${v}`} onClick={() => onChange(value.filter((x) => x !== v))}>×</button></span>
        ))}
        <input value={text} placeholder={hint} onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" || e.key === ",") { e.preventDefault(); add(); } }} onBlur={add} aria-label={`Add to ${label}`} />
      </div>
    </div>
  );
}

function Preferences() {
  const { categories, prefs, savePrefs, session } = useUser();
  const [draft, setDraft] = useState<Prefs>(prefs);
  const [state, setState] = useState<"idle" | "saving" | "saved" | string>("idle");
  useEffect(() => {
    setDraft(prefs);
  }, [prefs]);
  const dirty = JSON.stringify(draft) !== JSON.stringify(prefs);

  const setCat = (slug: string, patch: Partial<Prefs["categories"][string]>) =>
    setDraft({ ...draft, categories: { ...draft.categories, [slug]: { ...{ weight: 2, depth: "brief" as Depth }, ...draft.categories[slug], ...patch } } });
  const save = async () => {
    setState("saving");
    try {
      await savePrefs(draft);
      setState("saved");
    } catch (e) {
      setState((e as Error).message);
    }
  };

  return (
    <section className="box">
      <h2 className="label">Your newspaper</h2>
      <p className="muted">These settings choose what tomorrow's 06:00 edition covers and how deeply. Major world developments are always included, whatever you choose.
        {!session && " Sign in so the newsroom can use them."}</p>
      <table className="prefs-table">
        <thead><tr><th>Section</th><th>Attention</th><th>Depth</th></tr></thead>
        <tbody>
          {categories.map((c) => {
            const cfg = draft.categories[c.slug] ?? { weight: 2, depth: "brief" as Depth };
            return (
              <tr key={c.slug}>
                <th scope="row">{c.emoji} {c.name}</th>
                <td>
                  <div className="segmented small" role="radiogroup" aria-label={`${c.name} attention`}>
                    {WEIGHTS.map((w) => <button key={w.v} type="button" role="radio" aria-checked={cfg.weight === w.v} onClick={() => setCat(c.slug, { weight: w.v })}>{w.label}</button>)}
                  </div>
                </td>
                <td>
                  <div className="segmented small" role="radiogroup" aria-label={`${c.name} depth`}>
                    {DEPTHS.map((d) => <button key={d.v} type="button" role="radio" aria-checked={cfg.depth === d.v} disabled={c.slug === "interview"} onClick={() => setCat(c.slug, { depth: d.v })}>{d.label}</button>)}
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <ListInput label="Countries & regions to follow" hint="e.g. Japan" value={draft.countries} onChange={(v) => setDraft({ ...draft, countries: v })} />
      <ListInput label="Industries" hint="e.g. Semiconductors" value={draft.industries} onChange={(v) => setDraft({ ...draft, industries: v })} />
      <ListInput label="Sports" hint="e.g. Badminton" value={draft.sports} onChange={(v) => setDraft({ ...draft, sports: v })} />
      <ListInput label="Favourite teams & players" hint="e.g. Borussia Dortmund" value={draft.teams} onChange={(v) => setDraft({ ...draft, teams: v })} />
      <ListInput label="Leagues & competitions" hint="e.g. Champions League" value={draft.leagues} onChange={(v) => setDraft({ ...draft, leagues: v })} />
      <ListInput label="Roles you're preparing for" hint="e.g. Strategy consultant" value={draft.interview_roles} onChange={(v) => setDraft({ ...draft, interview_roles: v })} />
      <div className="field">
        <label htmlFor="extra">Anything else the editor should know</label>
        <textarea id="extra" rows={3} value={draft.extra_interests} placeholder="e.g. I have a McKinsey case interview in March; I'm interested in the energy transition."
          onChange={(e) => setDraft({ ...draft, extra_interests: e.target.value })} />
      </div>
      <div className="row">
        <button type="button" className="button" disabled={!dirty || state === "saving"} onClick={save}>Save preferences</button>
        {state === "saved" && !dirty && <span className="muted">Saved{session ? " to your account" : " on this device"}.</span>}
        {!["idle", "saving", "saved"].includes(state) && <span className="error-text">{state}</span>}
      </div>
    </section>
  );
}

function SavedLists() {
  const { bookmarks, history } = useUser();
  return (
    <div className="two-col">
      <section className="box">
        <h2 className="label">Bookmarks ({bookmarks.length})</h2>
        {!bookmarks.length && <p className="muted">Tap ☆ on any story to save it here.</p>}
        <ul className="latest">
          {bookmarks.map((b) => (
            <li key={b.story_id}>
              <Link to={`/story/${b.story_id}`}>{b.story?.headline ?? `Story #${b.story_id}`}</Link>
              <span className="meta">{b.story?.edition ? shortDate(b.story.edition.edition_date) : ""} · saved {dateTime(b.created_at)}</span>
            </li>
          ))}
        </ul>
      </section>
      <section className="box">
        <h2 className="label">Reading history</h2>
        {!history.length && <p className="muted">Stories you open appear here.</p>}
        <ul className="latest">
          {history.slice(0, 40).map((h) => (
            <li key={h.story_id}>
              <Link to={`/story/${h.story_id}`}>{h.story?.headline ?? `Story #${h.story_id}`}</Link>
              <span className="meta">read {dateTime(h.read_at)}</span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

export function MyPaper() {
  const standalone = typeof window !== "undefined" && window.matchMedia?.("(display-mode: standalone)").matches;
  return (
    <>
      <header className="section-masthead">
        <h1>My newspaper</h1>
      </header>
      <Account />
      {!standalone && (
        <section className="box">
          <h2 className="label">Put it on your home screen</h2>
          <p><strong>iPhone/iPad:</strong> open this site in Safari, tap the Share button, then “Add to Home Screen”.
            <br /><strong>Android/Chrome:</strong> menu ⋮ → “Install app”. <strong>Laptop:</strong> the install icon in the address bar.</p>
          <p className="muted small">The app opens straight to today's edition and keeps the last edition you opened available offline.</p>
        </section>
      )}
      <Preferences />
      <SavedLists />
    </>
  );
}
