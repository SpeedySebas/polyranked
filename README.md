# PolyRanked

PolyTrack player rankings, refreshed automatically on GitHub's servers and hosted on GitHub Pages.

- Website: https://speedysebas.github.io/polyranked/
- Update status and manual runs: https://github.com/SpeedySebas/polyranked/actions
- Machine-readable freshness: https://speedysebas.github.io/polyranked/status.json

The main publisher fetches fresh rankings **every five minutes**, at **:02, :07, :12, …, :57 (UTC)**. It prepares snapshots three minutes ahead of the website's **:00, :05, :10, …, :55** display updates. A freshness check skips duplicate builds when that release is already prepared or published. Source changes to `main` and manual Actions runs publish immediately. GitHub can delay or skip scheduled runs; these are target times, not an exact-time guarantee. No personal computer, personal access token, paid runner, or paid hosting plan is needed for ongoing operation. Keep this repository public to use the free public-repository runner and Pages plans.

## How it works

`build_site.py` fetches the top 1,000 raw entries from each of the 78 configured tracks and applies the existing ranking engine. It publishes a small HTML interface, an update manifest, and complete versioned ranking snapshots in `dist/`. Both `/` and `/methodology.html` serve the rankings. It does not publish Python source or internal files as website assets, and it does not commit generated datasets.

Scheduled builds carry forward the current released snapshot alongside the prepared next snapshot. Browsers download, verify, and parse the next data in the background, then update the display when the live countdown reaches zero. There is no reload or network request on that transition: searches, filters, pagination, and open player details are preserved. New visitors receive the most recent released snapshot. The last-updated label includes the data-generation date and time to the minute in UTC. Until the next data is downloaded, the timer labels its deadline as scheduled. If the next build is late or unavailable, the page keeps the existing data, displays the elapsed delay, and checks again every fifteen seconds. It applies late data automatically and never resets the timer as if an update succeeded. Connection failures are labeled as reconnecting.

All tracks and pages must be present, the ranking tests must pass, and the generated page must contain a complete fresh dataset before deployment. A failed run leaves the previous successful deployment online. API requests are limited to four concurrent requests and eight requests per second, with the engine's existing retry/backoff behavior. Public leaderboard reads do not require a PolyTrack account token.

After a successful deployment, the workflow commits one small ranking snapshot per UTC day in `history/`. This provides ranking history and ongoing repository activity for GitHub's 60-day scheduled-workflow inactivity rule. The workflow uses its automatically supplied `GITHUB_TOKEN`, which GitHub rotates per job; it does not depend on the setup token.

## Update the site

- Ranking rules, alternate accounts, and bans: `power_rankings/power_ranking_system.py`.
- Track metadata: the two CSV files in `power_rankings/`.
- Website layout and client-side behavior: `site/template.html`.
- Countdown, prefetching, and release logic: `site/live-updates.js`.
- Update schedule: `.github/workflows/update_leaderboard.yml`.

Push changes to `main` to rebuild and publish. To run on demand, open **Actions → Update and publish rankings → Run workflow**. GitHub Pages' publishing source must remain **GitHub Actions**.

## Run locally

Use Python 3.11, then run from this repository's directory:

```sh
python -m pip install -r requirements.txt
python -m unittest discover -s power_rankings -p 'test_*.py'
python -m unittest discover -s tests -p 'test_*.py'
node --test tests/live_updates.test.cjs
python build_site.py
python -m http.server 8000 --directory dist
```

Open http://localhost:8000. `site/template.html` has empty datasets by design; build and serve the entire `dist/` directory before viewing. The browser fetches `update.json` and the appropriate immutable snapshot; opening the HTML directly from disk is not supported.

The original standalone script is also included. The scheduled site uses the stricter build entry point above, without cache fallback or large research exports. See `power_rankings/METHODOLOGY.md` for the ranking methodology.

## Free-plan limits

GitHub Pages has a 1 GB site limit and a 100 GB/month soft bandwidth limit. Pages deployment artifacts are retained for only one day. If a run fails, inspect its Actions log; the public `status.json` records the last successful site's generation time and source revision.
