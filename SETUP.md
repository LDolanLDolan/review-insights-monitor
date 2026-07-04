# Setup — GitHub Actions Fringe Review Tracker

This replaces the PythonAnywhere + Google Sheets version. Everything below
happens once. After that, GitHub runs the checks automatically and you
never need to touch a terminal.

## 1. Add these files to your `review-insights-monitor` repo

Copy in:
- `fringe_tracker.py`
- `.github/workflows/track-reviews.yml`
- `data/shows.json`, `data/reviews.json`, `data/status.json`
- `dashboard_page.py`

If you already have a `requirements.txt` in the repo for the Streamlit app,
just add this one line to it rather than replacing the file:
```
requests>=2.28.0
```

## 2. Get free Google Custom Search credentials

(Same free tier as before — 100 searches/day, no card required.)

1. Go to https://console.cloud.google.com → create a project
2. **APIs & Services → Library** → search "Custom Search API" → Enable
3. **APIs & Services → Credentials** → Create Credentials → API Key → copy it
4. Go to https://programmablesearchengine.google.com → **Add**
5. Under "Sites to search" enter `*` → Create
6. Click **Customise** on the new engine → copy the **Search engine ID**

## 3. Add those as GitHub Secrets (not committed to the repo — private)

In your repo: **Settings → Secrets and variables → Actions → New repository secret**

Add two secrets:
- `GOOGLE_SEARCH_API_KEY` → the API key from step 2
- `GOOGLE_SEARCH_CX` → the Search engine ID from step 2

## 4. Show list — already done

`data/shows.json` is already filled in with all 217 shows from the C
venues 2026 programme (C aurora, C aquila, C alto and C digital), each
tagged with its venue, e.g.:
```json
{"title": "Locusts", "company": "", "venue": "C aquila"}
```
The `company` field is blank for all of them — the venue listing doesn't
give performer/company names, only show titles and venues. Fill those in
by hand if you want them showing up in the dashboard, but it's optional;
the tracker only needs `title` to search.

If C venues adds or drops shows before/during the festival, update
`data/shows.json` directly and commit the change — there's no live sync
back to the booking site, by design, since it renders with JavaScript
and isn't reliably scrapeable.

## 5. Turn it on

Go to the **Actions** tab in your repo. You should see "Track Fringe
Reviews" listed. Click it, then **Run workflow** to trigger it manually
the first time and check it works. After that it runs on its own at
08:00 and 18:00 UTC daily — no PythonAnywhere account needed.

## 6. Checking it's alive (your "is it working" check)

- **Fastest check:** open `data/status.json` in GitHub. It shows the last
  run time and how many reviews it found. This updates every run, so a
  recent timestamp means it's working.
- **Second check:** the repo's commit history — each successful run adds
  a commit titled "Update review data [automated]". A row of these
  appearing on schedule is proof of life.
- **In the app:** add `dashboard_page.py`'s content as a page in your
  Streamlit app — it shows the same status info plus the actual reviews
  and a "shows with no reviews yet" gap list.

## Adjusting the schedule

Open `.github/workflows/track-reviews.yml` and edit the two `cron` lines.
Times are in UTC. For example, to run once a day at 9am UTC instead of
twice, delete one line and change the other to `"0 9 * * *"`.

## Adding or removing review sites

Open `fringe_tracker.py` and edit the `REVIEW_SITES` list near the top.
