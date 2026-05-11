# Ward signals — deliverables for the prototype repo

This bundle adds **automated public signals** to the Ward Intelligence App
prototype. It pulls FixMyStreet reports, Reddit conversation from r/croydon,
and Inside Croydon news mentions per ward — refreshed every 6 hours by a
scheduled GitHub Action — and serves the result as a JSON file that the
prototype reads on load.

## What's in this bundle

```
signals-deliverables/
├── scripts/
│   └── fetch_signals.py            ← Python fetcher
├── .github/
│   └── workflows/
│       └── refresh-signals.yml     ← Actions workflow (runs every 6 hours)
├── data/
│   └── ward-signals.json           ← Initial placeholder (will be regenerated)
└── README.md                        ← this file
```

## Where these files go in your repo

Drop them into the same `croydon-ward-app` repo that hosts the prototype's
`index.html`. The final structure should look like:

```
croydon-ward-app/
├── index.html                       ← the prototype (already there)
├── README.md
├── scripts/
│   └── fetch_signals.py
├── data/
│   └── ward-signals.json
└── .github/
    └── workflows/
        └── refresh-signals.yml
```

## Setup steps (browser only, no CLI required)

1. Open your `croydon-ward-app` repo on GitHub.
2. Click **Add file → Upload files**.
3. Drag the `scripts`, `data`, and `.github` folders from this bundle in.
   GitHub will preserve the folder structure.
4. Commit at the bottom of the page.

5. **Enable Actions.** Go to **Settings → Actions → General**. Under
   "Actions permissions," choose *Allow all actions and reusable workflows*.
   Save.

6. **Allow Actions to push.** Still in **Settings → Actions → General**, scroll
   to "Workflow permissions." Choose *Read and write permissions*. Save.

7. **First manual run.** Click the **Actions** tab. In the left sidebar pick
   *Refresh ward signals*. Click **Run workflow → Run workflow**. Wait ~30
   seconds for it to finish.

8. **Check the result.** The workflow run should show green. Go back to your
   repo's file list — `data/ward-signals.json` should now contain real signal
   data. Reload the prototype in your browser and the "Public signals from this
   ward" section will populate for every ward.

From then on, the workflow runs automatically every 6 hours (00:00, 06:00,
12:00, 18:00 UTC). Each run commits the refreshed JSON back to the repo,
which GitHub Pages serves immediately.

## What gets collected

For each of the 28 Croydon wards, **metadata only** — no body content:

- **FixMyStreet** — up to 10 most recent reports in the last 30 days, with
  title, URL, date, and best-guess category.
- **Reddit** — up to 5 highest-scoring r/croydon posts from the last 30 days
  matching the ward name as a phrase, with title, URL, date, score, and
  comment count.
- **Inside Croydon** — up to 5 recent articles mentioning the ward by name in
  the title, summary, or post tags. Date and publisher attribution included.

The fetcher reads about 50-60 URLs per run (1 Inside Croydon front feed across
4 pages + 1 FixMyStreet feed and 1 Reddit search per ward). Total wall time
per run is around 1-2 minutes. Well within Actions' free monthly quota.

## What this does *not* do

- Does not access **Nextdoor** (no public API).
- Does not access **private Facebook groups** (inaccessible to non-members).
- Does not include **MyLondon** in this iteration — straightforward to add
  later by extending `fetch_news_*` in `fetch_signals.py`.
- Does not store post body content, comments, or media — by design, to keep
  the GDPR posture simple.

## Adjusting cadence or limits

Edit `.github/workflows/refresh-signals.yml`:
- Change `cron: '0 */6 * * *'` to e.g. `'0 */3 * * *'` for every 3 hours.

Edit `scripts/fetch_signals.py`:
- `TIME_WINDOW_DAYS` — default 30; change to widen or tighten.
- `MAX_FIXMYSTREET`, `MAX_REDDIT`, `MAX_NEWS` — per-source caps per ward.

After editing, commit and the next run uses the new settings.

## Troubleshooting

**Workflow run fails with "Permission denied" on push.** Check Settings →
Actions → General → Workflow permissions. Must be set to *Read and write*.

**No data appearing in the prototype.** Open
`https://your-username.github.io/croydon-ward-app/data/ward-signals.json`
directly in the browser. If you see real data there, the prototype should
display it on reload (force refresh with Ctrl+Shift+R or Cmd+Shift+R). If you
see a 404 or the placeholder JSON, the workflow either hasn't run yet or
failed — check the Actions tab.

**Sparse signals for a ward.** Expected and honest. FixMyStreet has low
Croydon volume (Croydon Council prefers Love Clean Streets). Some wards have
limited Reddit and Inside Croydon coverage. This is the partial picture
flagged in the original scoping note — Nextdoor and private groups are
invisible.

**Sensitive content surfacing.** Officer triage is mandatory. The prototype
prefix-notes this in the section header. For beta, integrate with the
council's safeguarding workflow.

## Contact

Vindy Hansra, Head of Digital & Data Transformation, Croydon Council.

This is an alpha prototype, not a production service. Beta will move hosting
to Azure Static Web Apps with Azure Functions handling the scheduled refresh
on the council's tenancy.
