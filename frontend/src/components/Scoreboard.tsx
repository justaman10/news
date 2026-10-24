import { useMemo, useState } from "react";
import { clock, dateTime } from "../lib/format";
import type { SportsEvent } from "../lib/types";
import { useUser } from "../lib/user";

function follows(e: SportsEvent, terms: string[]) {
  const text = `${e.home} ${e.away} ${e.competition} ${e.sport}`.toLowerCase();
  return terms.some((t) => text.includes(t));
}

function Row({ e, followed }: { e: SportsEvent; followed: boolean }) {
  const when = e.status === "scheduled" ? dateTime(e.starts_at) : e.status === "live" ? "LIVE" : clock(e.starts_at);
  const body = e.away ? (
    <>
      <span className="team">{e.home}</span>
      <span className="score">{e.home_score ?? ""}{e.status !== "scheduled" ? " – " : " v "}{e.away_score ?? ""}</span>
      <span className="team away">{e.away}</span>
    </>
  ) : (
    <span className="team wide">{e.home}</span>
  );
  return (
    <li className={`fixture ${e.status} ${followed ? "followed" : ""}`}>
      <span className={`when ${e.status}`}>{when}</span>
      {e.url ? <a className="match" href={e.url} target="_blank" rel="noopener noreferrer">{body}</a> : <span className="match">{body}</span>}
      {e.detail && <span className="detail">{e.detail}</span>}
    </li>
  );
}

export function Scoreboard({ events, compact }: { events: SportsEvent[]; compact?: boolean }) {
  const { prefs } = useUser();
  const [tab, setTab] = useState<"results" | "upcoming">("results");
  const terms = useMemo(
    () => [...prefs.teams, ...prefs.leagues, ...prefs.sports].map((t) => t.replace(/\(.*?\)/g, "").trim().toLowerCase()).filter(Boolean),
    [prefs],
  );
  const now = Date.now();
  const list = events
    .filter((e) => (tab === "results"
      ? e.status === "finished" || e.status === "live" || (e.status !== "scheduled" && new Date(e.starts_at).getTime() < now)
      : e.status === "scheduled" && new Date(e.starts_at).getTime() >= now - 3 * 3600e3))
    .sort((a, b) => {
      const f = Number(follows(b, terms)) - Number(follows(a, terms));
      if (f) return f;
      const t = new Date(a.starts_at).getTime() - new Date(b.starts_at).getTime();
      return tab === "results" ? -t : t;
    });
  const shown = compact ? list.slice(0, 8) : list;
  const groups = new Map<string, SportsEvent[]>();
  for (const e of shown) groups.set(e.competition, [...(groups.get(e.competition) ?? []), e]);
  const updated = events.reduce((m, e) => (e.updated_at > m ? e.updated_at : m), "");

  return (
    <div className="scoreboard">
      <div className="tabs" role="tablist">
        <button role="tab" aria-selected={tab === "results"} onClick={() => setTab("results")}>Results & live</button>
        <button role="tab" aria-selected={tab === "upcoming"} onClick={() => setTab("upcoming")}>Fixtures</button>
      </div>
      {shown.length === 0 && <p className="muted">No {tab === "results" ? "recent results" : "upcoming fixtures"} from the score feeds.</p>}
      {[...groups.entries()].map(([comp, evs]) => (
        <section key={comp}>
          <h4>{comp}</h4>
          <ul>{evs.map((e) => <Row key={e.id} e={e} followed={follows(e, terms)} />)}</ul>
        </section>
      ))}
      {updated && <p className="meta">Scores updated {dateTime(updated)}</p>}
    </div>
  );
}
