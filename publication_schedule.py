"""Schedule and deduplicate the free cloud publisher's retry opportunities."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import urllib.request

SITE_URL = "https://speedysebas.github.io/polyranked/"


def scheduled_release_time(started_at):
    # Start at :02/:07/... and prepare the :05/:10/... display boundary.
    seconds = started_at.timestamp()
    build_slot = ((seconds - 2 * 60) // 300) * 300 + 2 * 60
    return datetime.fromtimestamp(build_slot + 180, timezone.utc)


def build_needed(manifest, now):
    target = scheduled_release_time(now)
    window_start = target.timestamp() - 180
    if manifest.get("schema") != 1:
        return True
    for item in manifest.get("snapshots", []):
        release = datetime.fromisoformat(item["release_at"].replace("Z", "+00:00"))
        generated = datetime.fromisoformat(item["generated_at"].replace("Z", "+00:00"))
        if release >= target and window_start <= generated.timestamp() <= now.timestamp():
            return False
    return True


def check_schedule():
    needed = True
    now = datetime.now(timezone.utc)
    if os.environ.get("GITHUB_EVENT_NAME") in ("schedule", "workflow_dispatch"):
        try:
            request = urllib.request.Request(
                SITE_URL + "update.json?check=" + str(int(now.timestamp())),
                headers={"User-Agent": "PolyRanked-Updater", "Cache-Control": "no-cache"},
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                needed = build_needed(json.load(response), now)
        except (OSError, ValueError, KeyError, TypeError) as error:
            # A failed freshness check must not suppress a recovery attempt.
            print(f"Could not check published data; rebuilding: {error}")
    with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
        output.write(f"needed={'true' if needed else 'false'}\n")
    print("Fresh snapshot needed" if needed else "This update is already published or prepared; skipping duplicate build")


if __name__ == "__main__":
    check_schedule()
