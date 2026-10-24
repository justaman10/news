export function NotConfigured() {
  return (
    <main className="page">
      <header className="masthead">
        <h1 className="paper-title">The Daily Brief</h1>
      </header>
      <div className="notice">
        <h2>Almost there — the newsroom isn't connected yet</h2>
        <p>This site was built without its database settings. Add the repository variables
          <code> SUPABASE_URL</code> and <code>SUPABASE_ANON_KEY</code> on GitHub
          (Settings → Secrets and variables → Actions → Variables), then re-run the
          “Deploy website” workflow. Full steps are in <code>SETUP.md</code>.</p>
      </div>
    </main>
  );
}
