import json
from pathlib import Path
import tempfile
import unittest

from build_site import refresh_discipline_counts, save_daily_summary, validate_html, validate_leaderboards


class PublicationSafetyTests(unittest.TestCase):
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
