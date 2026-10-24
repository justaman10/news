import { ErrorBox, Loading } from "../components/ui";
import { feedHealth, jobStatus, recentRuns, useData } from "../lib/api";
import { ago, dateTime, host } from "../lib/format";

type Run = { id: number; job: string; started_at: string; finished_at: string | null; status: string; summary: Record<string, unknown>; error: string | null };
type Feed = { feed_url: string; category: string; last_ok: string | null; last_error: string | null; last_count: number };

export function StatusPage() {
  const status = useData("status", jobStatus);
  const runs = useData("runs", recentRuns);
  const feeds = useData("feeds", feedHealth);
  if (status.loading && !status.data) return <Loading />;
  if (status.error) return <ErrorBox message={status.error} />;
  const daily = status.data?.find((j) => j.job === "daily");
  const refresh = status.data?.find((j) => j.job === "refresh");
  const feedRows = (feeds.data ?? []) as Feed[];
  const failing = feedRows.filter((f) => f.last_error);

  return (
    <>
      <header className="section-masthead">
        <h1>System status</h1>
        <p className="muted">The newsroom runs on its own: a daily edition at 06:00 Berlin time and a refresh of news and scores every 30 minutes.</p>
      </header>
      <div className="stat-grid">
        <div className="stat"><span className="label">Last edition</span><strong>{daily?.last_success ? ago(daily.last_success) : "—"}</strong><span className="meta">{dateTime(daily?.last_success)}</span></div>
        <div className="stat"><span className="label">Last refresh</span><strong>{refresh?.last_success ? ago(refresh.last_success) : "—"}</strong><span className="meta">{dateTime(refresh?.last_success)}</span></div>
        <div className="stat"><span className="label">Sources healthy</span><strong>{feedRows.length - failing.length} / {feedRows.length}</strong><span className="meta">RSS feeds</span></div>
      </div>
      <h2 className="rule-title">Recent runs</h2>
      <table className="runs">
        <thead><tr><th>Job</th><th>Started</th><th>Result</th><th>Details</th></tr></thead>
        <tbody>
          {((runs.data ?? []) as Run[]).map((r) => {
            const ai = r.summary?.ai as { estimated_usd?: number } | undefined;
            return (
              <tr key={r.id}>
                <td>{r.job}</td>
                <td>{dateTime(r.started_at)}</td>
                <td><span className={`pill ${r.status}`}>{r.status}</span></td>
                <td className="small">
                  {r.error ?? [
                    r.summary?.new_articles !== undefined && `${r.summary.new_articles} new articles`,
                    r.summary?.stories !== undefined && `${r.summary.stories} stories`,
                    r.summary?.deep_dives !== undefined && `${r.summary.deep_dives} deep dives`,
                    ai?.estimated_usd !== undefined && `AI ≈ $${ai.estimated_usd.toFixed(2)}`,
                    (r.summary?.warnings as string[] | undefined)?.length && `${(r.summary.warnings as string[]).length} warnings`,
                  ].filter(Boolean).join(" · ")}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {failing.length > 0 && (
        <>
          <h2 className="rule-title">Sources with problems</h2>
          <p className="muted small">Other sources keep the paper running; these are retried every 30 minutes.</p>
          <ul className="latest">
            {failing.map((f) => <li key={f.feed_url}><strong>{host(f.feed_url)}</strong> <span className="meta">({f.category}) {f.last_error}{f.last_ok && ` · last OK ${ago(f.last_ok)}`}</span></li>)}
          </ul>
        </>
      )}
    </>
  );
}
