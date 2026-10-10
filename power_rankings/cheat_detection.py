"""Detect ghost copies; persist account-wide exclusion evidence."""
import asyncio
import base64
from bisect import bisect_right
from datetime import datetime, timezone
import json
from pathlib import Path
import zlib

import aiohttp

from power_rankings.power_ranking_system import (
    API_VERSION, BASE_URL, HEADERS, TokenBucket, resolve_canonical_player,
)

RULE_VERSION = 1
MAX_BYTES = 8 * 1024 * 1024


def decode_inputs(recording):
    """Return five canonical toggle timelines, preserving simultaneous-toggle parity."""
    compressed = base64.b64decode(recording + '=' * (-len(recording) % 4), altchars=b'-_', validate=True)
    decoder = zlib.decompressobj()
    data = decoder.decompress(compressed, MAX_BYTES + 1)
    if len(data) > MAX_BYTES or not decoder.eof or decoder.unused_data:
        raise ValueError('Invalid or oversized recording')
    offset = 0

    def uint24():
        nonlocal offset
        if offset + 3 > len(data):
            raise ValueError('Truncated recording')
        value = int.from_bytes(data[offset:offset + 3], 'little')
        offset += 3
        return value

    channels = []
    for _ in range(5):
        count = uint24()
        if count > (len(data) - offset) // 3:
            raise ValueError('Invalid toggle count')
        frame, toggles = 0, []
        for _ in range(count):
            frame += uint24()
            if toggles and toggles[-1] == frame:
                toggles.pop()
            else:
                toggles.append(frame)
        channels.append(toggles)
    if offset != len(data):
        raise ValueError('Unknown recording format: trailing data')
    return channels


def upload_time(entry):
    if not isinstance(entry.get('time'), str):
        raise ValueError('Missing upload time')
    stamp = datetime.fromisoformat(entry['time'].replace('Z', '+00:00'))
    if stamp.tzinfo is None:
        raise ValueError('Upload time has no timezone')
    return stamp.astimezone(timezone.utc)


def matching_half(a, b):
    """Detect ghost copies: exact first-half prefix OR high-confidence copy.

    Covers exact prefixes through the midpoint (ceil for odd durations), as well as
    slightly modified copies that contain injected micro-taps, tap jitter, or slight
    timing adjustments (such as FlamBys17).
    Returns the frame index through which the match is evidenced, or None.
    """
    end = (max(a['frames'], b['frames']) + 1) // 2
    if end > min(a['frames'], b['frames']):
        return None

    # 1. Exact first-half prefix check
    exact = True
    for x, y in zip(a['inputs'], b['inputs']):
        if x[:bisect_right(x, end)] != y[:bisect_right(y, end)]:
            exact = False
            break
    if exact:
        return end

    # 2. Tolerant copy detection for slightly modified copies (e.g. FlamBys17)
    max_contig = 0
    common_half = 0
    common_all = 0
    min_half = 0
    total_a = 0
    total_b = 0

    for x, y in zip(a['inputs'], b['inputs']):
        total_a += len(x)
        total_b += len(y)
        min_half += min(bisect_right(x, end), bisect_right(y, end))
        i, j = 0, 0
        current_run = 0
        while i < len(x) and j < len(y):
            if x[i] == y[j]:
                val = x[i]
                common_all += 1
                if val <= end:
                    common_half += 1
                current_run += 1
                if current_run > max_contig:
                    max_contig = current_run
                i += 1
                j += 1
            elif x[i] < y[j]:
                current_run = 0
                i += 1
            else:
                current_run = 0
                j += 1

    if min_half >= 10 and (common_half / min_half) >= 0.80 and max_contig >= 10:
        return end

    min_all = min(total_a, total_b)
    if min_all >= 20 and (common_all / min_all) >= 0.75 and max_contig >= 10:
        return end

    return None


def detect_copies(current, references, alt_mappings=None):
    """Each current run needs a direct match to an earlier upload, not transitivity."""
    evidence, unresolved = [], []
    for run in current:
        matches = []
        for original in references:
            if original['id'] == run['id'] or original['userId'] == run['userId']:
                continue
            if resolve_canonical_player(run.get('nickname'), run['userId'], alt_mappings)[0] == resolve_canonical_player(original.get('nickname'), original['userId'], alt_mappings)[0]:
                continue
            midpoint = matching_half(run, original)
            if midpoint is None:
                continue
            try:
                earlier, later = upload_time(original), upload_time(run)
            except (KeyError, TypeError, ValueError):
                unresolved.append({'id': run['id'], 'other_id': original['id'], 'reason': 'missing/invalid upload time'})
                continue
            if earlier == later:
                unresolved.append({'id': run['id'], 'other_id': original['id'], 'reason': 'tied upload time'})
            elif earlier < later:
                matches.append((earlier, original['id'], original, midpoint))
        if matches:
            _, _, source, midpoint = min(matches, key=lambda item: item[:2])
            evidence.append({
                'userId': run['userId'], 'nickname': run.get('nickname', ''),
                'recording_id': run['id'], 'uploaded_at': run['time'],
                'original_userId': source['userId'], 'original_recording_id': source['id'],
                'original_uploaded_at': source['time'], 'matched_through_frame': midpoint,
                'frames': run['frames'], 'original_frames': source['frames'],
                'rule_version': RULE_VERSION,
            })
    return evidence, unresolved


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def valid_cached_run(run):
    if not isinstance(run, dict) or type(run.get('id')) is not int or type(run.get('frames')) is not int or run['frames'] <= 0:
        return False
    channels = run.get('inputs')
    if not isinstance(run.get('userId'), str) or not run['userId'] or not isinstance(channels, list) or len(channels) != 5:
        return False
    return all(isinstance(channel, list)
               and all(type(frame) is int and frame >= 0 for frame in channel)
               and all(a < b for a, b in zip(channel, channel[1:]))
               for channel in channels)


async def scan_leaderboards(leaderboards, tracks, state_path, cache_path, report_path, alt_mappings=None, progress=None):
    """Scan raw top ten, reuse historical top-ten ghosts, return durable ban IDs.

    Failure to obtain a ghost is reported as unavailable, never evidence. An
    unreadable durable ban ledger fails the build instead of silently unbanning.
    """
    state_path, cache_path = Path(state_path), Path(cache_path)
    state = json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else {'schema': 1, 'bans': {}, 'exempt_user_ids': []}
    if state.get('schema') != 1 or not isinstance(state.get('bans'), dict):
        raise ValueError('Invalid automatic blacklist ledger')
    try:
        cache = json.loads(cache_path.read_text(encoding='utf-8'))
        if cache.get('version') != API_VERSION or cache.get('rule_version') != RULE_VERSION:
            cache = {}
    except (OSError, ValueError):
        cache = {}
    raw_archive = cache.get('tracks', {})
    archive = {track: {key: run for key, run in runs.items() if valid_cached_run(run) and key == str(run['id'])}
               for track, runs in raw_archive.items() if isinstance(runs, dict)} if isinstance(raw_archive, dict) else {}
    cache['tracks'] = archive
    limiter, sem = TokenBucket(rate=1, capacity=1), asyncio.Semaphore(2)
    failures, unresolved, findings = [], [], []
    cooldown_until, completed = 0.0, 0
    timeout = aiohttp.ClientTimeout(total=25)
    async with aiohttp.ClientSession(headers=HEADERS, timeout=timeout) as session:
        async def fetch(track_id, entries):
            nonlocal cooldown_until
            current, missing = [], []
            for entry in entries:
                saved = archive.setdefault(track_id, {}).get(str(entry['id']))
                if saved and all(saved.get(k) == entry.get(k) for k in ('userId', 'frames', 'time')):
                    current.append(dict(saved, nickname=entry.get('nickname', '')))
                else:
                    missing.append(entry)
            if not missing:
                return current
            keys = ','.join(str(entry['id']) for entry in missing)
            payload = None
            for attempt in range(4):
                try:
                    async with sem:
                        await limiter.acquire()
                        delay = cooldown_until - asyncio.get_running_loop().time()
                        if delay > 0:
                            await asyncio.sleep(delay)
                        async with session.get(BASE_URL.rsplit('/', 1)[0] + '/recordings', params={'version': API_VERSION, 'ids': keys}) as response:
                            if response.status == 429:
                                try:
                                    retry_after = float(response.headers.get('Retry-After', 0))
                                except (ValueError, TypeError):
                                    retry_after = 0
                                cooldown_until = max(cooldown_until, asyncio.get_running_loop().time() + max(retry_after, 15 * 2 ** attempt))
                            response.raise_for_status()
                            payload = await response.json()
                    if not isinstance(payload, list) or len(payload) != len(missing):
                        raise ValueError('Recording batch length mismatch')
                    break
                except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as error:
                    payload = None
                    if attempt == 3:
                        failures.extend({'trackId': track_id, 'id': entry['id'], 'reason': str(error)} for entry in missing)
                    else:
                        await asyncio.sleep(2 ** attempt)
            if payload is None:
                return current
            # The game's getRecordings(ids) protocol returns one slot per ID,
            # including null for unavailable recordings; never drop null slots.
            for entry, recording in zip(missing, payload):
                try:
                    if recording['frames'] != entry['frames'] or not entry.get('userId') or type(entry['frames']) is not int or entry['frames'] <= 0:
                        raise ValueError('Recording metadata mismatch')
                    inputs = decode_inputs(recording['recording'])
                    saved = {k: entry.get(k) for k in ('id', 'userId', 'nickname', 'frames', 'time')}
                    saved['inputs'] = inputs
                    archive[track_id][str(entry['id'])] = saved
                    current.append(saved)
                except (ValueError, KeyError, TypeError, zlib.error) as error:
                    failures.append({'trackId': track_id, 'id': entry['id'], 'reason': str(error)})
            return current

        async def scan(track, entries):
            nonlocal completed
            track_id = tracks[track]
            current = await fetch(track_id, entries[:10])
            evidence, ambiguous = detect_copies(current, list(archive.get(track_id, {}).values()), alt_mappings)
            for item in evidence:
                item.update(track=track, trackId=track_id, game_version=API_VERSION)
            findings.extend(evidence)
            unresolved.extend(dict(item, track=track) for item in ambiguous)
            completed += 1
            if completed % 10 == 0 or completed == len(leaderboards):
                write_json(cache_path, dict(cache, version=API_VERSION, rule_version=RULE_VERSION))
                if progress:
                    progress(f"Ghost scan: {completed}/{len(leaderboards)} tracks; {len(findings)} matches, {len(failures)} unavailable recordings.")

        await asyncio.gather(*(scan(track, entries) for track, entries in leaderboards.items()))
    for item in sorted(findings, key=lambda e: (e['trackId'], e['recording_id'])):
        state['bans'].setdefault(item['userId'], item)
    exempt = set(state.get('exempt_user_ids', []))
    write_json(state_path, state)
    write_json(cache_path, dict(cache, version=API_VERSION, rule_version=RULE_VERSION))
    write_json(report_path, {'findings': findings, 'unresolved': unresolved, 'unavailable': failures, 'active_bans': sorted(set(state['bans']) - exempt)})
    return set(state['bans']) - exempt, {'findings': len(findings), 'unavailable': len(failures), 'unresolved': len(unresolved)}
