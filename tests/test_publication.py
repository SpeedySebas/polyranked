import json
import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from build_site import fetch_complete_leaderboards, refresh_discipline_counts, retain_current_snapshot, save_daily_summary, scheduled_release_time, validate_html, validate_leaderboards


class FetchRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_retries_only_inconsistent_tracks(self):
        good = [{'userId': 'one', 'frames': 100}, {'userId': 'two', 'frames': 101}]
        duplicate = [good[0], good[0]]
        with patch('build_site.fetch_all_leaderboards', new_callable=AsyncMock) as fetch, patch('build_site.asyncio.sleep', new_callable=AsyncMock):
            fetch.side_effect = [({'A': good, 'B': duplicate}, {'A': 2, 'B': 2}), ({'B': good}, {'B': 2})]
            boards, totals = await fetch_complete_leaderboards({'A': 'a', 'B': 'b'})
            self.assertEqual(fetch.await_args_list[1].args[0], {'B': 'b'})
            self.assertEqual(boards, {'A': good, 'B': good})
            self.assertEqual(totals, {'A': 2, 'B': 2})

    async def test_persistent_inconsistency_still_prevents_publication(self):
        duplicate = [{'userId': 'one', 'frames': 100}] * 2
        with patch('build_site.fetch_all_leaderboards', new_callable=AsyncMock, return_value=({'A': duplicate}, {'A': 2})) as fetch, patch('build_site.asyncio.sleep', new_callable=AsyncMock):
            with self.assertRaisesRegex(ValueError, 'duplicate'):
                await fetch_complete_leaderboards({'A': 'a'})
            self.assertEqual(fetch.await_count, 3)


class PublicationSafetyTests(unittest.TestCase):
    def test_staging_keeps_the_released_snapshot_until_the_boundary(self):
        data = b'{"complete":"previous snapshot"}'
        digest = hashlib.sha256(data).hexdigest()
        previous = {"url": f"snapshots/{digest}.json", "sha256": digest, "generated_at": "2026-09-30T12:01:00Z", "release_at": "2026-09-30T12:07:00Z"}
        pending = dict(previous, generated_at="2026-09-30T12:28:00Z", release_at="2026-09-30T12:37:00Z")
        manifest = json.dumps({"snapshots": [previous, pending]}).encode()
        with tempfile.TemporaryDirectory() as temporary:
            stage = Path(temporary)
            (stage / "snapshots").mkdir()
            with patch('build_site.urllib.request.urlopen', side_effect=[io.BytesIO(manifest), io.BytesIO(data)]):
                retained = retain_current_snapshot(stage, datetime(2026, 9, 30, 12, 30, tzinfo=timezone.utc))
            self.assertEqual(retained, previous)
            self.assertEqual((stage / previous['url']).read_bytes(), data)

    def test_staging_rejects_a_corrupt_previous_snapshot(self):
        descriptor = {"url": "snapshots/" + "a" * 64 + ".json", "sha256": "a" * 64, "generated_at": "2026-09-30T12:01:00Z", "release_at": "2026-09-30T12:07:00Z"}
        manifest = json.dumps({"snapshots": [descriptor]}).encode()
        with tempfile.TemporaryDirectory() as temporary, patch('build_site.urllib.request.urlopen', side_effect=[io.BytesIO(manifest), io.BytesIO(b'corrupt')]):
            with self.assertRaisesRegex(ValueError, 'integrity'):
                retain_current_snapshot(Path(temporary), datetime(2026, 9, 30, 12, 30, tzinfo=timezone.utc))

    def test_scheduled_build_prepares_the_next_boundary_and_preserves_late_target(self):
        for start, expected in [('2026-09-30T12:27:00', '2026-09-30T12:37:00'), ('2026-09-30T12:40:00', '2026-09-30T12:37:00'), ('2026-09-30T23:58:00', '2026-10-01T00:07:00')]:
            with self.subTest(start=start):
                self.assertEqual(scheduled_release_time(datetime.fromisoformat(start).replace(tzinfo=timezone.utc)), datetime.fromisoformat(expected).replace(tzinfo=timezone.utc))

    def test_complete_small_track_is_accepted(self):
        validate_leaderboards({"A": "id"}, {"A": [{"userId": "one", "frames": 100}]}, {"A": 1})

    def test_missing_track_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "track list"):
            validate_leaderboards({"A": "id", "B": "id2"}, {"A": []}, {"A": 1000})

    def test_partial_second_page_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "500 of 1000"):
            validate_leaderboards({"A": "id"}, {"A": [{}] * 500}, {"A": 100000})

    def test_duplicate_pagination_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            validate_leaderboards({"A": "id"}, {"A": [{"userId": "one", "frames": 100}] * 2}, {"A": 2})

    def test_invalid_entry_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "malformed"):
            validate_leaderboards({"A": "id"}, {"A": [{"userId": "one", "frames": 0}]}, {"A": 1})

    def test_old_or_unreplaced_html_is_rejected(self):
        report = {"players": [{"username": "new leader"}], "metadata": {"total_tracks": 1, "generated_at": "today"}}
        for html in ('const PLAYERS = [];\nconst TRACK_WEIGHTS_DATA = [{}];\ntoday', 'const PLAYERS = [{"u":"old leader"}];\nconst TRACK_WEIGHTS_DATA = [{}];\ntoday'):
            with self.subTest(html=html), self.assertRaises(ValueError):
                validate_html(html, report)

    def test_daily_history_is_written_once(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            status = root / "status.json"
            status.write_text(json.dumps({"generated_at": "2026-09-30T12:07:00Z", "players": 42}), encoding="utf-8")
            self.assertTrue(save_daily_summary(status, root / "history"))
            first = (root / "history" / "2026-09-30.json").read_bytes()
            status.write_text(json.dumps({"generated_at": "2026-09-30T12:37:00Z", "players": 43}), encoding="utf-8")
            self.assertFalse(save_daily_summary(status, root / "history"))
            self.assertEqual((root / "history" / "2026-09-30.json").read_bytes(), first)

    def test_discipline_labels_follow_the_current_roster(self):
        original = '36 Fullspeed + 42 Technical (78 Pool); Fullspeed Discipline (36 tracks); Technical Discipline (42 Tracks); Fullspeed (36)'
        updated = refresh_discipline_counts(original, {"Fullspeed": 35, "Technical": 43})
        self.assertEqual(updated, '35 Fullspeed + 43 Technical (78 Pool); Fullspeed Discipline (35 tracks); Technical Discipline (43 Tracks); Fullspeed (35)')


if __name__ == "__main__":
    unittest.main()
