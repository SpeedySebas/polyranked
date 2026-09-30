"""Fetch complete live leaderboards and build the static site for GitHub Pages."""
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import urllib.request

from power_rankings.power_ranking_system import (
    PowerRankingSystem,
    fetch_all_leaderboards,
    update_methodology_html,
)

ROOT = Path(__file__).resolve().parent
SCRAPE_AMOUNT = 1000
SITE_URL = "https://speedysebas.github.io/polyranked/"
DATA_NAMES = ("PLAYERS", "TRACK_WEIGHTS_DATA", "TRACK_DOMAINS", "TRACK_SUBGENRES", "TRACK_STYLES")


def scheduled_release_time(started_at):
    # Jobs start at :27/:57 and stage data for the :37/:07 display boundary.
    seconds = started_at.timestamp()
    build_slot = ((seconds - 27 * 60) // 1800) * 1800 + 27 * 60
    return datetime.fromtimestamp(build_slot + 600, timezone.utc)


def iso_time(value):
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def retain_current_snapshot(stage, now):
    """Carry the currently visible snapshot forward while the next one is staged."""
    def download(path):
        request = urllib.request.Request(SITE_URL + path, headers={"User-Agent": "PolyRanked-Updater", "Cache-Control": "no-cache"})
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.read()
    manifest = json.loads(download("update.json?build=" + str(int(now.timestamp()))))
    eligible = [item for item in manifest["snapshots"] if datetime.fromisoformat(item["release_at"].replace("Z", "+00:00")) <= now]
    if not eligible:
        raise ValueError("No current snapshot is available to serve before the next release")
    current = max(eligible, key=lambda item: item["generated_at"])
    if not re.fullmatch(r"snapshots/[a-f0-9]{64}\.json", current["url"]):
        raise ValueError("Invalid previous snapshot URL")
    data = download(current["url"])
    if hashlib.sha256(data).hexdigest() != current["sha256"]:
        raise ValueError("Previous snapshot failed its integrity check")
    (stage / current["url"]).write_bytes(data)
    return current


def validate_leaderboards(expected_tracks, leaderboards, totals, amount=SCRAPE_AMOUNT):
    """Refuse missing tracks, exhausted retries, and incomplete pagination."""
    if set(leaderboards) != set(expected_tracks):
        raise ValueError("The fetched track list does not match the configured tracks")
    for name in expected_tracks:
        total = totals.get(name)
        entries = leaderboards[name]
        if not isinstance(total, int) or total <= 0:
            raise ValueError(f"{name}: missing or invalid participant count")
        expected_count = min(amount, total)
        if len(entries) != expected_count:
            raise ValueError(f"{name}: received {len(entries)} of {expected_count} expected entries")
        if any(not isinstance(entry, dict) or not entry.get("userId") or not isinstance(entry.get("frames"), int) or entry["frames"] <= 0 for entry in entries):
            raise ValueError(f"{name}: malformed leaderboard entry")
        if len({entry["userId"] for entry in entries}) != len(entries):
            raise ValueError(f"{name}: duplicate accounts across leaderboard pages; retry a fresh snapshot")


def embedded_json(html, name):
    match = re.search(r"const " + re.escape(name) + r" = (.*?);\s*\n", html)
    if not match:
        raise ValueError(f"The HTML template is missing {name}")
    return json.loads(match.group(1))


def refresh_discipline_counts(html, totals):
    for domain in ("Fullspeed", "Technical"):
        count = totals[domain]
        html = re.sub(r"(" + domain + r"(?: Discipline)? \()\d+(\s*[Tt]racks)?\)", lambda match: f"{match[1]}{count}{match[2] or ''})", html)
        html = re.sub(r"\d+ " + domain + r"(?= \+| \()", f"{count} {domain}", html)
    return html


def validate_html(html, report):
    players = embedded_json(html, "PLAYERS")
    weights = embedded_json(html, "TRACK_WEIGHTS_DATA")
    if not players or len(players) != len(report["players"]):
        raise ValueError("The generated HTML does not contain the complete player dataset")
    if len(weights) != report["metadata"]["total_tracks"]:
        raise ValueError("The generated HTML does not contain all track weights")
    if report["metadata"]["generated_at"] not in html:
        raise ValueError("The generated HTML is missing the fresh update timestamp")
    if players[0]["u"] != report["players"][0]["username"]:
        raise ValueError("The generated HTML contains a stale ranking")


def save_daily_summary(source, history_dir):
    """Keep one small genuine ranking snapshot per UTC day."""
    summary = json.loads(Path(source).read_text(encoding="utf-8"))
    date = datetime.fromisoformat(summary["generated_at"].replace("Z", "+00:00")).date().isoformat()
    history_dir = Path(history_dir)
    history_dir.mkdir(parents=True, exist_ok=True)
    target = history_dir / f"{date}.json"
    if target.exists():
        return False
    target.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return True


async def build():
    started_at = datetime.now(timezone.utc)
    system = PowerRankingSystem()
    if len(system.registry.main_tracks) != 17 or len(system.registry.community_tracks) != 61:
        raise ValueError("Track metadata is missing or has changed; review the configured 78-track roster")
    print(f"Fetching fresh data for {len(system.registry.all_tracks)} tracks", flush=True)
    # No disk-cache fallback: failed fetches must never appear as a fresh update.
    leaderboards, totals = await fetch_all_leaderboards(
        system.registry.all_tracks, amount=SCRAPE_AMOUNT, rate_limit=8.0, max_concurrency=4
    )
    validate_leaderboards(system.registry.all_tracks, leaderboards, totals)
    system.registry.set_track_totals(totals)
    report = system.compute_all_rankings(leaderboards, track_totals=totals)
    if not report["players"]:
        raise ValueError("The ranking calculation produced no players")

    with tempfile.TemporaryDirectory(prefix="polyranked-build-") as staging:
        stage = Path(staging)
        index = stage / "index.html"
        index.write_bytes((ROOT / "site" / "template.html").read_bytes())
        if not update_methodology_html(report, html_path=str(index), index_path=str(index)):
            raise ValueError("The HTML update failed; deployment cancelled")
        html = refresh_discipline_counts(index.read_text(encoding="utf-8"), report["metadata"]["discipline_totals"])
        validate_html(html, report)
        generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        release_at = scheduled_release_time(started_at) if os.environ.get("GITHUB_EVENT_NAME") == "schedule" else datetime.now(timezone.utc)
        payload = {
            "generated_at": generated_at,
            "datasets": {name: embedded_json(html, name) for name in DATA_NAMES},
            "discipline_totals": report["metadata"]["discipline_totals"],
        }
        snapshot_bytes = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
        digest = hashlib.sha256(snapshot_bytes).hexdigest()
        snapshot = {"version": digest, "sha256": digest, "url": f"snapshots/{digest}.json", "generated_at": generated_at, "release_at": iso_time(release_at)}
        (stage / "snapshots").mkdir()
        (stage / snapshot["url"]).write_bytes(snapshot_bytes)
        snapshots = []
        if release_at > datetime.now(timezone.utc):
            snapshots.append(retain_current_snapshot(stage, datetime.now(timezone.utc)))
        snapshots.append(snapshot)
        (stage / "update.json").write_text(json.dumps({"schema": 1, "snapshots": snapshots}, separators=(",", ":")) + "\n", encoding="utf-8")

        # Ship a small page shell; the browser chooses the correct released snapshot.
        client = (ROOT / "site" / "live-updates.js").read_bytes()
        shell = (ROOT / "site" / "template.html").read_text(encoding="utf-8").replace("LIVE_CLIENT_VERSION", hashlib.sha256(client).hexdigest()[:16])
        index.write_text(shell, encoding="utf-8")
        shutil.copyfile(index, stage / "methodology.html")
        (stage / "live-updates.js").write_bytes(client)
        (stage / ".nojekyll").touch()
        summary = {
            "generated_at": generated_at,
            "release_at": iso_time(release_at),
            "snapshot": snapshot["url"],
            "source_commit": os.environ.get("GITHUB_SHA", "local"),
            "tracks": len(leaderboards),
            "entries": sum(map(len, leaderboards.values())),
            "players": len(report["players"]),
            "index_sha256": hashlib.sha256(index.read_bytes()).hexdigest(),
            "top_20": [{"rank": player["gsi_rank"], "player": player["username"], "gsi": round(player["gsi"], 1)} for player in report["players"][:20]],
        }
        (stage / "status.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        destination = ROOT / "dist"
        destination.mkdir(exist_ok=True)
        shutil.copytree(stage, destination, dirs_exist_ok=True)
    print(f"Validated {summary['players']:,} players across {summary['tracks']} tracks; site ready in dist/", flush=True)


if __name__ == "__main__":
    asyncio.run(build())
