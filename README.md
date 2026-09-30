# PolyRanked

PolyTrack player rankings, refreshed automatically on GitHub's servers and hosted on GitHub Pages.

- Website: https://speedysebas.github.io/polyranked/
- Update status and manual runs: https://github.com/SpeedySebas/polyranked/actions
- Machine-readable freshness: https://speedysebas.github.io/polyranked/status.json

The workflow runs at minutes **7 and 37 every hour (UTC)**, on source changes to `main`, and when manually requested in the Actions tab. GitHub can delay or occasionally skip scheduled runs. No personal computer, personal access token, paid runner, or paid hosting plan is needed for ongoing operation. Keep this repository public to use the free public-repository runner and Pages plans.

## How it works

`build_site.py` fetches the top 1,000 raw entries from each of the 78 configured tracks, applies the existing ranking engine, and fills `site/template.html`. It publishes only the contents of `dist/`. Both `/` and `/methodology.html` serve the rankings. It does not publish the Python source or internal files as website assets, and it does not commit the generated HTML or large raw JSON exports.

All tracks and pages must be present, the ranking tests must pass, and the generated page must contain a complete fresh dataset before deployment. A failed run leaves the previous successful deployment online. API requests are limited to four concurrent requests and eight requests per second, with the engine's existing retry/backoff behavior. Public leaderboard reads do not require a PolyTrack account token.

After a successful deployment, the workflow commits one small ranking snapshot per UTC day in `history/`. This provides ranking history and ongoing repository activity for GitHub's 60-day scheduled-workflow inactivity rule. The workflow uses its automatically supplied `GITHUB_TOKEN`, which GitHub rotates per job; it does not depend on the setup token.

## Update the site

- Ranking rules, alternate accounts, and bans: `power_rankings/power_ranking_system.py`.
- Track metadata: the two CSV files in `power_rankings/`.
- Website layout and client-side behavior: `site/template.html`.
- Update schedule: `.github/workflows/update_leaderboard.yml`.

Push changes to `main` to rebuild and publish. To run on demand, open **Actions → Update and publish rankings → Run workflow**. GitHub Pages' publishing source must remain **GitHub Actions**.

## Run locally

Use Python 3.11, then run from this repository's directory:

```sh
python -m pip install -r requirements.txt
python -m unittest discover -s power_rankings -p 'test_*.py'
python -m unittest discover -s tests -p 'test_*.py'
python build_site.py
python -m http.server 8000 --directory dist
```

Open http://localhost:8000. `site/template.html` has empty embedded datasets by design; build before viewing.

The original standalone script is also included. The scheduled site uses the stricter build entry point above, without cache fallback or large research exports. See `power_rankings/METHODOLOGY.md` for the ranking methodology.

## Free-plan limits

GitHub Pages has a 1 GB site limit and a 100 GB/month soft bandwidth limit. Pages deployment artifacts are retained for only one day. If a run fails, inspect its Actions log; the public `status.json` records the last successful site's generation time and source revision.
