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

from power_rankings.power_ranking_system import (
    PowerRankingSystem,
    fetch_all_leaderboards,
    update_methodology_html,
)

ROOT = Path(__file__).resolve().parent
SCRAPE_AMOUNT = 1000


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
        index.write_text(html, encoding="utf-8")
        validate_html(html, report)
        shutil.copyfile(index, stage / "methodology.html")
        (stage / ".nojekyll").touch()
        generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        summary = {
            "generated_at": generated_at,
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
        for file in stage.iterdir():
            shutil.copyfile(file, destination / file.name)
    print(f"Validated {summary['players']:,} players across {summary['tracks']} tracks; site ready in dist/", flush=True)


if __name__ == "__main__":
    asyncio.run(build())
