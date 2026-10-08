"""Cancel stale publisher runs without joining the publication queue or environment."""
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone

ACTIVE = {"queued", "in_progress", "waiting", "pending", "requested"}
MAX_AGE_SECONDS = 20 * 60


def is_stale(run, current_id, now):
    return (str(run["id"]) != str(current_id)
            and run.get("head_branch") == "main"
            and run.get("status") in ACTIVE
            and (now - datetime.fromisoformat(run["created_at"].replace("Z", "+00:00"))).total_seconds() > MAX_AGE_SECONDS)


def recover(api, current_id, now):
    # Separate filtered queries find the blocked run even behind days of cancelled runs.
    candidates = {}
    for status in sorted(ACTIVE):
        page = 1
        while True:
            result = api("GET", f"actions/workflows/update_leaderboard.yml/runs?status={status}&branch=main&per_page=100&page={page}")
            runs = result["workflow_runs"]
            candidates.update((run["id"], run) for run in runs)
            if len(runs) < 100:
                break
            page += 1
    for run_id, run in candidates.items():
        if not is_stale(run, current_id, now):
            continue
        # Recheck before cancelling: completed runs must be left alone.
        fresh = api("GET", f"actions/runs/{run_id}")
        if is_stale(fresh, current_id, now):
            print(f"Recovering stale publication run {run_id}: {fresh['status']}", flush=True)
            api("POST", f"actions/runs/{run_id}/force-cancel")


def main():
    base = os.environ.get("GITHUB_API_URL", "https://api.github.com") + "/repos/" + os.environ["GITHUB_REPOSITORY"] + "/"
    def api(method, path):
        request = urllib.request.Request(base + path, method=method, headers={
            "Authorization": "Bearer " + os.environ["GH_TOKEN"],
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                data = response.read()
                return json.loads(data) if data else {}
        except urllib.error.HTTPError as error:
            # Another concurrent recovery job can finish cancellation first.
            if method == "POST" and error.code == 409:
                return {}
            raise
    recover(api, os.environ["GITHUB_RUN_ID"], datetime.now(timezone.utc))


if __name__ == "__main__":
    main()
