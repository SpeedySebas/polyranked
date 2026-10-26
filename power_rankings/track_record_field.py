"""Build World Record versus field statistics for each track."""
import math
from typing import Any, Dict, Iterable, List, Mapping


TOP_RUNS = 30
TAS_TIMES = {
    "Summer 2": 15.105,
    "Winter 1": 16.966,
    "Summer 1": 21.815,
    "Summer 4": 33.934,
    "Winter 3": 34.196,
    "Desert 1": 19.971,
}


def _record_field_stats(track_name: str, entries: Iterable[Mapping[str, Any]], tas_baseline: bool) -> Dict[str, Any]:
    """Calculate a track's WR z-score from its fastest 30 leaderboard times."""
    valid_entries = [
        entry for entry in entries
        if isinstance(entry.get("frames"), (int, float)) and not isinstance(entry.get("frames"), bool)
        and entry["frames"] > 0
    ]
    fastest = sorted(valid_entries, key=lambda entry: entry["frames"])[:TOP_RUNS]
    if not fastest:
        raise ValueError(f"No valid leaderboard times found for {track_name}")

    times = [
        float(entry["frames"]) / 1000.0 if entry["frames"] > 1000 else float(entry["frames"])
        for entry in fastest
    ]
    human_wr_time = times[0]
    human_wr_holder = str(fastest[0].get("nickname") or "Unknown")
    tas_time = TAS_TIMES.get(track_name) if tas_baseline else None
    measured_times = [tas_time, *times] if tas_time is not None else times
    mean = sum(measured_times) / len(measured_times)
    variance = sum((value - mean) ** 2 for value in measured_times) / len(measured_times)
    std_dev = math.sqrt(variance)
    wr_time = tas_time if tas_time is not None else human_wr_time

    return {
        "track": track_name,
        "wrHolder": "TAS (Honorary)" if tas_time is not None else human_wr_holder,
        "wrTime": wr_time,
        "topMean": mean,
        "topStdDev": std_dev,
        "zScore": (wr_time - mean) / std_dev if std_dev else 0.0,
        "totalRunsAnalyzed": len(measured_times),
        "times": times,
        "humanWrHolder": human_wr_holder,
        "humanWrTime": human_wr_time,
        "isTas": tas_time is not None,
        "tasTime": tas_time,
    }


def build_world_record_field_data(
    leaderboards: Mapping[str, List[Dict[str, Any]]],
    main_tracks: Mapping[str, str],
    community_tracks: Mapping[str, str],
) -> Dict[str, List[Dict[str, Any]]]:
    """Return human-WR and TAS-baseline z-score statistics for both track groups."""
    def rank_group(track_names: Iterable[str], tas_baseline: bool) -> List[Dict[str, Any]]:
        results = [
            _record_field_stats(name, leaderboards.get(name, []), tas_baseline)
            for name in track_names
        ]
        return sorted(results, key=lambda result: result["zScore"])

    return {
        "main_tracks": rank_group(main_tracks, False),
        "community_tracks": rank_group(community_tracks, False),
        "main_tracks_tas": rank_group(main_tracks, True),
        "community_tracks_tas": rank_group(community_tracks, True),
    }
