# The Daily Brief

A newspaper made for one reader. Every morning it pulls the topics you chose from
RSS feeds, has Claude pick the stories that matter, and writes each one up at the
depth you asked for. Along the way it builds up an interview-prep notebook.

**Each edition has:**

- **The big picture**: a short opener that ties the day's main threads together.
- **Sections for your topics**, each at its own depth:
  - `headlines`: one-line summaries you can scan in 30 seconds
  - `brief`: a summary, why it matters, and one interview question
  - `deep`: context, key terms, 2–3 interview questions with answer outlines,
    and a talking point you can use
- **Concept of the day** for every section: a framework or idea worth knowing well,
  with an example and a practice question.
- **Daily quiz**: multiple-choice questions on today's stories, to check you understood them.

**Across editions:**

- **Archive**: every past edition, kept in `editions/` as JSON.
- **Interview prep**: every question, concept, term and talking point the paper
  has ever produced, all on one page. You can search it, filter by topic, shuffle
  it into flashcards, and mark cards as "I know this" (saved in your browser).

## Set up (about 5 minutes)

1. **Add your API key.** On GitHub, go to *Settings → Secrets and variables → Actions →
   New repository secret*. Set the name to `ANTHROPIC_API_KEY` and paste a key from
   [console.anthropic.com](https://console.anthropic.com).
2. **Turn on GitHub Pages.** Go to *Settings → Pages → Build and deployment → Source*
   and choose **GitHub Actions**.
3. **Make sure the code is on `main`.** The schedule only runs on the default branch.
4. **Run it once.** Go to *Actions → Daily edition → Run workflow*. When it finishes,
   the paper is at `https://<your-username>.github.io/<repo>/`. Bookmark it.

After that it runs every day at 00:30 UTC (06:00 IST). You can change the time in
`.github/workflows/daily.yml`.

## Make it yours

Everything is in [`config.yaml`](config.yaml):

| Setting | What it does |
|---|---|
| `reader.goal`, `background`, `target_roles` | Tells the editor who you are. This decides which stories get picked and what the interview questions ask. |
| `topics[].depth` | `headlines`, `brief` or `deep`, set per topic |
| `topics[].max_stories` | How many stories that section gets |
| `topics[].keywords` / `exclude` | Push stories you care about up the list; drop stories you never want |
| `topics[].interview_focus` | The angle the questions take, e.g. "system design" or "case interview" |
| `topics[].feeds` | Any RSS or Atom URLs |
| `paper.timezone` | Which day counts as "today" |
| `ai.effort` | `low`, `medium` or `high`. Higher takes more care and costs more. |

Commit a change to `main` and the site re-renders automatically. That doesn't
re-write today's edition or cost anything. To regenerate today with the new
settings, use *Run workflow* with **force** ticked.

Cost: about 6 Claude calls a day (one per section, plus one for the front page),
typically a few dollars a month at the default settings. Without an API key, the
paper still builds as a plain headline digest.

## Run locally

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
python -m newspaper            # builds today's edition into editions/ and the site into site/
open site/index.html

python -m newspaper --no-ai    # headline digest, no API calls
python -m newspaper --force    # rebuild today's edition
python -m newspaper --render-only
python -m unittest discover tests
```

## How it works

```
feeds ──▶ fetch.py ──▶ editor.py (Claude) ──▶ editions/DATE.json ──▶ render.py ──▶ site/
          rank, dedupe,   choose stories,        kept in git as          today, archive,
          skip repeats    write at your depth,   your archive            prep notebook
                          interview prep, quiz
```

- Stories that ran in the last few editions aren't repeated, and a story covered
  by two feeds shows up only once.
- The editor is told to stick to what the sources say and not invent figures.
  Every story links to its original, so check the original before you quote a
  number in an interview.
- If Claude is unavailable, or a request fails or is declined, that section falls
  back to the plain feed digest. The paper still comes out.
