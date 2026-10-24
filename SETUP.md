# Setting up your newspaper (about 20 minutes, once)

You'll create two free accounts (Supabase for the database, Google AI Studio for the AI editor),
paste a few values into GitHub, and click "Run". After that everything runs on its own,
forever, whether or not you open the site.

Your site will live at **https://justaman10.github.io/news/**

---

## 1. Database: Supabase (free)

1. Sign up at **https://supabase.com** and click **New project**.
   - Name: `daily-brief`; **Region: Central EU (Frankfurt)** (closest to you)
   - Set a **database password** and keep it somewhere safe.
2. When it's ready, open **Project Settings → API** (or **Connect → App frameworks**) and copy:
   - **Project URL**, which looks like `https://abcdxyz.supabase.co`
   - The **anon / public** key, a long `eyJ…` string. It's designed to be public: database
     security rules decide what it can read.
3. Click **Connect** (top bar) → **Connection string** → **Session pooler**, and copy the URI.
   Replace `[YOUR-PASSWORD]` with your database password. It looks like
   `postgresql://postgres.abcdxyz:PASSWORD@aws-0-eu-central-1.pooler.supabase.com:5432/postgres`
   (use the *pooler* string, because GitHub's servers can't reach the direct IPv6 address).
4. **Authentication → URL Configuration**: set **Site URL** to
   `https://justaman10.github.io/news/`. Confirmation emails then link back to your site.

You don't need to create any tables. The backend sets up the database automatically on its first run.

## 2. AI editor: Google Gemini (free, no card)

1. Go to **https://aistudio.google.com** and sign in with any Google account.
2. Click **Get API key** → **Create API key** (let it create a project if asked) → copy the key (`AIza…`).

That's it. The free tier allows roughly 10 requests a minute and a few hundred a day.
The paper needs about 20 a day and paces itself. Note: on the free tier Google may use
what's sent (public headlines and your stated interests) to improve its products.

*Optional, paid:* to use Claude instead (it also researches the deep dives on the web),
add an `ANTHROPIC_API_KEY` from console.anthropic.com. When both keys exist, Claude is used.
It costs about $1–2.50 a day, capped by `daily_budget_usd` in `backend/config/sources.yaml`.

## 3. Optional: richer scores (both free)

- **Football** (Premier League, Bundesliga, Champions League, La Liga, Serie A, Ligue 1, Euros, World Cup):
  register at **https://www.football-data.org/client/register** → you'll get an API token by email.
- **Cricket** (live international and IPL scores): register at **https://cricketdata.org** → copy your API key.

F1, NBA, NFL, IPL and ISL fixtures work without any key. Tennis and badminton are covered
through the sports news feeds.

## 4. Put the values into GitHub

Open **https://github.com/justaman10/news/settings/secrets/actions**.

**Secrets** tab → *New repository secret* for each:

| Name | Value |
|---|---|
| `DATABASE_URL` | the Session pooler URI from step 1.3 |
| `GEMINI_API_KEY` | `AIza…` from step 2 |
| `FOOTBALL_DATA_TOKEN` | *(optional)* football-data.org token |
| `CRICKET_API_KEY` | *(optional)* cricketdata.org key |

**Variables** tab → *New repository variable* for each:

| Name | Value |
|---|---|
| `SUPABASE_URL` | Project URL from step 1.2 |
| `SUPABASE_ANON_KEY` | anon key from step 1.2 |
| `OWNER_EMAIL` | the email you'll sign in to the site with |

Secrets are encrypted and never appear in logs or in the website. The two variables are
public by design.

## 5. Turn on the website

**https://github.com/justaman10/news/settings/pages** → **Build and deployment → Source: GitHub Actions**.

## 6. Start it

Go to **https://github.com/justaman10/news/actions** and run these three workflows once, in
this order (select each one → **Run workflow**):

1. **Deploy website**: publishes the site (about 1 minute)
2. **Refresh news & scores**: fills the database with the latest reporting (about 1 minute)
3. **Daily edition**: builds your first edition with the AI editor (about 5–10 minutes)

## 7. Make it yours

1. Open **https://justaman10.github.io/news/** → **My newspaper** → **Create account** with the
   `OWNER_EMAIL` address, confirm the email, then sign in.
2. Set how much attention and depth each section gets, and add your teams, countries,
   industries and the roles you're preparing for. **Save**. The next morning's edition follows them.
3. Keep the site private to you: in Supabase, go to **Authentication → Sign In / Providers** and turn off
   **Allow new users to sign up**.
4. **iPhone:** open the site in Safari → Share → **Add to Home Screen**. On a laptop, use the install icon
   in the address bar. Sign in once on each device and everything stays in sync.

---

## What runs automatically

| When | What |
|---|---|
| Every day, 06:00 Berlin | **Daily edition**: fetch everything, remove duplicates, pick the stories that matter, write summaries, deep dives, interview prep and a quiz, publish |
| Every 30 minutes | **Refresh**: new reporting from every source, scores and fixtures, "developing story" updates on today's edition |
| Each run | The database schema is upgraded if needed, and the site's status line updates |

If a run fails, GitHub emails you, and the **System status** page shows what happened.
If a source is down, the others carry on. If the AI is unavailable, the edition is still
published as a plain headline digest from the sources.
