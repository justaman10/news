# The Daily Brief

A personal daily newspaper that publishes itself. Every morning at 06:00 (Berlin) a new
edition is waiting. It's built from real reporting by named outlets, organised into
sections, explained in depth, and tuned to your interests and your interview prep.
News and scores refresh every 30 minutes.

**→ First time? Follow [SETUP.md](SETUP.md).**

## What you get

- **Front page**: date and edition number, a lead story, the 8–12 most important headlines
  across sections, publisher images, "The big picture" overview, latest updates, scores,
  and the "For you" picks.
- **Today's edition**: every section in your order, with Quick / Standard / Full reading
  depth, a concept of the day per section, and a daily quiz.
- **Sections**: World 🌍, India 🇮🇳, Germany 🇩🇪 (incl. Koblenz/Vallendar), Politics 🏛️,
  Sports ⚽ (live scores and fixtures), Business 💼, Technology 🤖, Science 🔬,
  Entertainment 🎬, and Interview Intelligence 🎯. Each has its own page with today's
  stories, a live feed straight from the publishers, and earlier coverage.
- **Deep dives**: what happened (reported), background, why it matters, perspectives,
  implications, what to watch, a timeline, key terms, interview questions, and every
  original source. Reporting and analysis are always labelled apart.
- **My newspaper**: section weights and depth, followed countries, industries, teams,
  leagues and target roles, plus bookmarks and reading history. All of it syncs across
  devices when you're signed in.
- **Archive**: every edition by date, with full-text search.
- **Interview prep**: every question, concept, term and talking point ever published, as
  flashcards. Your "known" progress syncs.
- **Installable PWA**: add it to your iPhone home screen. The last edition you opened stays
  readable offline.

## How it works

```
             every 30 min                           06:00 Berlin
 ┌──────────────────────────────┐   ┌────────────────────────────────────────────┐
 │ GitHub Actions: refresh      │   │ GitHub Actions: daily edition              │
 │  • 60+ RSS feeds (cond. GET) │   │  • cluster duplicate reports across outlets│
 │  • football-data, F1, NBA,   │   │  • rank by coverage, freshness, your prefs │
 │    NFL, IPL, cricket scores  │   │  • Claude edits each section at your depth │
 │  • developing-story updates  │   │  • front page, quiz, web-researched dives  │
 └──────────────┬───────────────┘   └──────────────────┬─────────────────────────┘
                ▼                                      ▼
        ┌────────────────────────────────────────────────────────┐
        │ Supabase Postgres: articles, editions, stories, sports, │
        │ job runs · Auth · profiles, bookmarks, history (RLS)    │
        └───────────────────────────┬────────────────────────────┘
                                    ▼  (REST, read-only for content)
        ┌────────────────────────────────────────────────────────┐
        │ React PWA on GitHub Pages: justaman10.github.io/news   │
        └────────────────────────────────────────────────────────┘
```

| Part | Tech | Where |
|---|---|---|
| Frontend | React 18, TypeScript, Vite, PWA (Workbox) | `frontend/` → GitHub Pages |
| Worker | Python 3.12, feedparser, psycopg, Anthropic SDK | `backend/` → GitHub Actions cron |
| Database & auth | Postgres + Row Level Security, Supabase Auth | Supabase |
| Sources & defaults | `backend/config/sources.yaml` | |

**Grounded, not invented.** The worker stores only each item's headline, the publisher's
own short description, the link, and the image from the publisher's feed. It never stores
full articles. Claude only sees that reporting, grouped by development. Every story it
writes must point at a real cluster, and any link it cites is checked against URLs we
actually fetched or found through search. Anything that fails falls back to an unedited
digest of the source headlines.

**Reliability.** Each source is independent, so a dead feed doesn't stop the paper. Feeds
are fetched with conditional GET, and every job is recorded in `job_runs` (see the
site's **System status** page). Publishing is idempotent, and there are backup runs if
GitHub's scheduler is late. A monthly keep-alive commit stops GitHub from pausing the
schedule.

## Developing

```bash
# backend: tests run against a real Postgres
cd backend && pip install -r requirements.txt
TEST_DATABASE_URL=postgresql://postgres@localhost/postgres python -m unittest discover tests
python -m newspaper check-sources          # test every feed and sports API, no DB needed
DATABASE_URL=... python -m newspaper refresh
DATABASE_URL=... python -m newspaper daily --force

# frontend
cd frontend && npm install
VITE_SUPABASE_URL=... VITE_SUPABASE_ANON_KEY=... npm run dev
```

To add or swap a source, edit `backend/config/sources.yaml`, push, and the **Check
sources** workflow reports whether each feed works from GitHub's network.

## Roadmap

- Push notification for the morning edition and big breaking stories
- AI-written refresh of the lead story when it develops significantly during the day
- Weekly "week in review" and spaced-repetition scheduling for prep cards
- Optional custom domain
