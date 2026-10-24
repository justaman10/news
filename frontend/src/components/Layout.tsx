import { useEffect, type ReactNode } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import { jobStatus, useData } from "../lib/api";
import { dateTime } from "../lib/format";
import { orderedCategories, useUser } from "../lib/user";

const PRIMARY = [
  { to: "/", label: "Front page", short: "Today", icon: "📰", end: true },
  { to: "/edition", label: "Today's edition", short: "Edition", icon: "🗞️" },
  { to: "/archive", label: "Archive", short: "Archive", icon: "🗂️" },
  { to: "/prep", label: "Interview prep", short: "Prep", icon: "🎯" },
  { to: "/me", label: "My newspaper", short: "Me", icon: "👤" },
];

export function UpdateStatus() {
  const { data } = useData("status", jobStatus);
  const daily = data?.find((j) => j.job === "daily");
  const refresh = data?.find((j) => j.job === "refresh");
  if (!data) return null;
  return (
    <p className="update-status">
      {daily?.last_success && <>Edition published {dateTime(daily.last_success)} · </>}
      {refresh?.last_success ? <>Last update {dateTime(refresh.last_success)}</> : "Waiting for first update"}
      {" · "}<Link to="/status">System status</Link>
    </p>
  );
}

export function Layout({ children }: { children: ReactNode }) {
  const { categories, prefs, session } = useUser();
  const location = useLocation();
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [location.pathname]);
  const sections = orderedCategories(categories, prefs);

  return (
    <>
      <a className="skip" href="#main">Skip to content</a>
      <header className="topbar">
        <div className="topbar-inner">
          <Link to="/" className="brand">The Daily Brief</Link>
          <nav className="primary" aria-label="Main">
            {PRIMARY.map((p) => (
              <NavLink key={p.to} to={p.to} end={p.end}>{p.to === "/me" && session ? "My newspaper ✓" : p.label}</NavLink>
            ))}
          </nav>
        </div>
        <nav className="sections" aria-label="Sections">
          {sections.map((c) => (
            <NavLink key={c.slug} to={`/section/${c.slug}`}>{c.emoji} {c.name}</NavLink>
          ))}
        </nav>
      </header>
      <main id="main" className="page">{children}</main>
      <footer className="site-footer">
        <UpdateStatus />
        <p>Every story links to its original reporting. Summaries and analysis are written by an AI
          editor from those sources; check the originals before relying on a detail.</p>
      </footer>
      <nav className="tabbar" aria-label="App">
        {PRIMARY.map((p) => (
          <NavLink key={p.to} to={p.to} end={p.end}><span aria-hidden>{p.icon}</span>{p.short}</NavLink>
        ))}
      </nav>
    </>
  );
}
