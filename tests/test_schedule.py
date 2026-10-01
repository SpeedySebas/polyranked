from datetime import datetime
import unittest

from publication_schedule import build_needed, scheduled_release_time


def at(time):
    return datetime.fromisoformat('2026-09-30T' + time + '+00:00')


def manifest(generated, release):
    return {'schema': 1, 'snapshots': [{
        'generated_at': at(generated).isoformat(), 'release_at': at(release).isoformat(),
    }]}


class ScheduleTests(unittest.TestCase):
    def test_five_minute_windows_preserve_the_target_when_a_run_is_late(self):
        for time in ['12:02:00', '12:03:00', '12:05:00', '12:06:59']:
            self.assertEqual(scheduled_release_time(at(time)), at('12:05:00'))
        self.assertEqual(scheduled_release_time(at('12:07:00')), at('12:10:00'))

    def test_missing_release_is_retried(self):
        self.assertTrue(build_needed(manifest('11:57:30', '12:00:00'), at('12:03:00')))
        self.assertTrue(build_needed(manifest('11:57:30', '12:00:00'), at('12:06:00')))

    def test_prepared_release_skips_duplicate_work(self):
        for time in ['12:03:00', '12:05:00', '12:06:00']:
            self.assertFalse(build_needed(manifest('12:02:30', '12:05:00'), at(time)))

    def test_next_window_fetches_new_data(self):
        self.assertTrue(build_needed(manifest('12:02:30', '12:05:00'), at('12:07:00')))

    def test_fresh_manual_update_also_satisfies_an_overdue_slot(self):
        self.assertFalse(build_needed(manifest('12:05:30', '12:05:30'), at('12:06:00')))

    def test_stale_or_future_generation_does_not_suppress_recovery(self):
        self.assertTrue(build_needed(manifest('12:00:00', '12:05:00'), at('12:03:00')))
        self.assertTrue(build_needed(manifest('12:04:00', '12:05:00'), at('12:03:00')))


if __name__ == '__main__':
    unittest.main()
