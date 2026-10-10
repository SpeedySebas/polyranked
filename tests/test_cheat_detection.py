import base64
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import zlib

from power_rankings.cheat_detection import decode_inputs, detect_copies, matching_half, scan_leaderboards, valid_cached_run
from power_rankings.power_ranking_system import process_raw_leaderboard


def encode(channels):
    data = bytearray()
    for channel in channels:
        data.extend(len(channel).to_bytes(3, 'little'))
        previous = 0
        for frame in channel:
            data.extend((frame - previous).to_bytes(3, 'little'))
            previous = frame
    return base64.urlsafe_b64encode(zlib.compress(data)).decode().rstrip('=')


def run(rid=1, stamp='2026-10-01T00:00:00Z', frames=1000):
    return dict(id=rid, userId=f'user{rid}', nickname=f'Player{rid}', time=stamp,
                frames=frames, inputs=[[0], [100, 120, 300, 350, 700, 800], [], [200, 240], []])


class DetectionTests(unittest.TestCase):
    def test_corrupt_cached_timelines_are_rejected(self):
        self.assertTrue(valid_cached_run(run()))
        for channels in ([], [[], [], [], [], [3, 2]], [[], [], [], [], [-1]], [[], [], [], [], ['1']]):
            self.assertFalse(valid_cached_run(dict(run(), inputs=channels)))

    def test_decode_and_simultaneous_toggle_parity(self):
        channels = [[0], [100, 100, 120], [], [200, 240], []]
        self.assertEqual(decode_inputs(encode(channels)), [[0], [120], [], [200, 240], []])

    def test_malformed_and_unknown_format(self):
        for raw in (b'\x00', b'\x00' * 16, b'\xff' * 15):
            with self.assertRaises(ValueError):
                decode_inputs(base64.urlsafe_b64encode(zlib.compress(raw)).decode())

    def test_late_tap_spam_cannot_dilute_match(self):
        original, copied = run(), run(2, '2026-10-02T00:00:00Z')
        copied['inputs'][1] = [100, 120, 300, 350] + list(range(501, 1000))
        evidence, _ = detect_copies([copied, original], [copied, original], {})
        self.assertEqual([e['userId'] for e in evidence], ['user2'])
        self.assertEqual(evidence[0]['original_recording_id'], 1)

    def test_single_frame_difference_in_first_half_rejects(self):
        a, b = run(), run(2)
        b['inputs'][1][1] += 1
        self.assertIsNone(matching_half(a, b))

    def test_midpoint_inclusive_and_both_durations(self):
        a, b = run(), run(2, frames=1200)
        b['inputs'][2] = [550]
        self.assertIsNone(matching_half(a, b))
        b = run(2)
        b['inputs'][2] = [500]
        self.assertIsNone(matching_half(a, b))
        b['inputs'][2] = [501]
        self.assertEqual(matching_half(a, b), 500)
        b['frames'] = 1001
        self.assertIsNone(matching_half(a, b))

    def test_duration_is_finish_not_last_toggle(self):
        a, b = run(), run(2)
        a['inputs'][1] = b['inputs'][1] = [100, 120]
        b['inputs'][2] = [400]
        self.assertIsNone(matching_half(a, b))

    def test_timestamp_not_id_or_rank_selects_original(self):
        a, b, c = run(100), run(1, '2026-10-02T00:00:00Z'), run(2, '2026-10-03T00:00:00Z')
        evidence, _ = detect_copies([c, b, a], [c, b, a], {})
        self.assertEqual({e['original_recording_id'] for e in evidence}, {100})
        self.assertEqual({e['userId'] for e in evidence}, {'user1', 'user2'})

    def test_missing_or_tied_dates_are_unresolved(self):
        a, b = run(), run(2)
        for stamp in ('2026-10-01T00:00:00Z', None, 'invalid'):
            b['time'] = stamp
            evidence, unresolved = detect_copies([b], [a], {})
            self.assertFalse(evidence)
            self.assertTrue(unresolved)

    def test_known_alts_not_accused(self):
        a, b = run(), run(2, '2026-10-02T00:00:00Z')
        evidence, _ = detect_copies([b], [a], {'user1': 'same', 'user2': 'same'})
        self.assertFalse(evidence)

    def test_direct_match_required_not_transitive_cluster(self):
        a, b, c = run(), run(2, '2026-10-02T00:00:00Z'), run(3, '2026-10-03T00:00:00Z')
        c['inputs'][2] = [100]
        evidence, _ = detect_copies([a, b, c], [a, b, c], {})
        self.assertEqual([e['userId'] for e in evidence], ['user2'])

    def test_micro_taps_and_slight_modifications_detected(self):
        # A run copied with injected micro-taps / slight variations (FlamBys17 pattern)
        original = dict(id=1, userId='user1', nickname='Player1', time='2026-10-01T00:00:00Z', frames=20000,
                        inputs=[[0], list(range(1000, 3000, 50)), [8000, 8868], list(range(3500, 7500, 70)), []])
        copied = dict(id=2, userId='user2', nickname='Player2', time='2026-10-02T00:00:00Z', frames=19980,
                      inputs=[
                          [0, 9123, 9151],
                          sorted(list(range(1000, 3000, 50)) + [5376, 5437]),
                          [8000, 8858],
                          sorted([2661, 2686] + list(range(3500, 7500, 70))),
                          []
                      ])
        self.assertIsNotNone(matching_half(copied, original))
        evidence, _ = detect_copies([copied, original], [copied, original], {})
        self.assertEqual([e['userId'] for e in evidence], ['user2'])
        self.assertEqual(evidence[0]['original_recording_id'], 1)

    def test_legitimate_runs_never_falsely_flagged(self):
        # Independent players sharing only incidental starting input
        a = dict(id=1, userId='user1', nickname='Player1', time='2026-10-01T00:00:00Z', frames=20000,
                 inputs=[[0], [1050, 1100, 1500], [8000, 8800], [3500, 3600], []])
        b = dict(id=2, userId='user2', nickname='Player2', time='2026-10-02T00:00:00Z', frames=20050,
                 inputs=[[0], [1040, 1120, 1520], [8020, 8810], [3510, 3590], []])
        self.assertIsNone(matching_half(b, a))
        evidence, _ = detect_copies([b, a], [b, a], {})
        self.assertFalse(evidence)

    def test_tap_spam_without_contiguous_block_never_flags(self):
        # High frequency jitter with no contiguous segment
        a = dict(id=1, userId='user1', nickname='Player1', time='2026-10-01T00:00:00Z', frames=20000,
                 inputs=[[0], [1000, 2000, 3000, 4000], [], [], []])
        b = dict(id=2, userId='user2', nickname='Player2', time='2026-10-02T00:00:00Z', frames=20000,
                 inputs=[[0], list(range(100, 10000, 100)), [], [], []])
        self.assertIsNone(matching_half(b, a))
        evidence, _ = detect_copies([b, a], [b, a], {})
        self.assertFalse(evidence)


class PersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_batch_preserves_null_slots_and_matches_correct_account(self):
        from power_rankings.cheat_detection import API_VERSION, RULE_VERSION
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            a, b, c = run(), run(2, '2026-10-02T00:00:00Z'), run(3, '2026-10-03T00:00:00Z')
            (root / 'cache.json').write_text(json.dumps({'version': API_VERSION, 'rule_version': RULE_VERSION, 'tracks': {'track': {'1': a}}}))
            response = MagicMock(status=200)
            response.json = AsyncMock(return_value=[None, {'frames': c['frames'], 'recording': encode(c['inputs'])}])
            request = MagicMock()
            request.__aenter__ = AsyncMock(return_value=response)
            session = MagicMock()
            session.get.return_value = request
            context = MagicMock()
            context.__aenter__ = AsyncMock(return_value=session)
            with patch('power_rankings.cheat_detection.aiohttp.ClientSession', return_value=context):
                bans, stats = await scan_leaderboards({'A': [a, b, c]}, {'A': 'track'}, root / 'state.json', root / 'cache.json', root / 'report.json', {})
            self.assertEqual(bans, {'user3'})
            self.assertEqual(stats['unavailable'], 1)
            self.assertEqual(session.get.call_args.kwargs['params']['ids'], '2,3')

    async def test_unavailable_recording_never_bans(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            response = MagicMock()
            response.json = AsyncMock(return_value=[None])
            request = MagicMock()
            request.__aenter__ = AsyncMock(return_value=response)
            session = MagicMock()
            session.get.return_value = request
            context = MagicMock()
            context.__aenter__ = AsyncMock(return_value=session)
            with patch('power_rankings.cheat_detection.aiohttp.ClientSession', return_value=context), patch('power_rankings.cheat_detection.asyncio.sleep', new_callable=AsyncMock):
                bans, stats = await scan_leaderboards({'A': [run()]}, {'A': 'track'}, root / 'state.json', root / 'cache.json', root / 'report.json', {})
            self.assertFalse(bans)
            self.assertEqual(stats['unavailable'], 1)
            self.assertEqual(session.get.call_count, 1)

    async def test_corrupt_ledger_does_not_silently_unban(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'state.json').write_text('{')
            with self.assertRaises(ValueError):
                await scan_leaderboards({}, {}, root / 'state.json', root / 'cache.json', root / 'report.json')

    async def test_top_ten_history_persistence_exemption_and_global_filter(self):
        from power_rankings.cheat_detection import API_VERSION, RULE_VERSION
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original, copied = run(), run(2, '2026-10-02T00:00:00Z')
            entries = [copied] * 10 + [dict(run(99), inputs=None)]
            cache = {'version': API_VERSION, 'rule_version': RULE_VERSION, 'tracks': {'track': {'1': original, '2': copied}}}
            (root / 'cache.json').write_text(json.dumps(cache))
            args = ({'A': entries}, {'A': 'track'}, root / 'state.json', root / 'cache.json', root / 'report.json', {})
            bans, _ = await scan_leaderboards(*args)
            self.assertEqual(bans, {'user2'})
            # A run on another track with an unrelated ghost is still excluded.
            other_track = [dict(copied, nickname='Renamed'), run(3)]
            cleaned = process_raw_leaderboard(other_track, alt_mappings={}, blacklisted_players=bans)
            self.assertEqual(len(cleaned), 1)
            bans, _ = await scan_leaderboards({}, {}, *args[2:])
            self.assertEqual(bans, {'user2'})
            state = json.loads((root / 'state.json').read_text())
            state['exempt_user_ids'] = ['user2']
            (root / 'state.json').write_text(json.dumps(state))
            bans, _ = await scan_leaderboards(*args)
            self.assertFalse(bans)


if __name__ == '__main__':
    unittest.main()
