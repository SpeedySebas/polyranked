import unittest
from datetime import datetime, timezone
from recover_runs import is_stale, recover

class RecoveryTests(unittest.TestCase):
    now = datetime(2026, 10, 8, 12, 30, tzinfo=timezone.utc)
    def run_data(self, **changes):
        return dict(dict(id=1, head_branch="main", status="waiting", created_at="2026-10-08T12:00:00Z"), **changes)
    def test_only_old_active_main_runs(self):
        self.assertTrue(is_stale(self.run_data(), 2, self.now))
        for changes in [dict(id=2), dict(head_branch="development"), dict(status="completed"), dict(created_at="2026-10-08T12:15:00Z")]:
            self.assertFalse(is_stale(self.run_data(**changes), 2, self.now))
    def test_recheck_and_cancel(self):
        calls = []
        def api(method, path):
            calls.append((method, path))
            if "?" in path: return {"workflow_runs": [self.run_data()]}
            return self.run_data()
        recover(api, 2, self.now)
        self.assertEqual([p for m,p in calls if m == "POST"], ["actions/runs/1/force-cancel"])
    def test_completed_during_check_is_not_cancelled(self):
        def api(method, path):
            self.assertEqual(method, "GET")
            return {"workflow_runs": [self.run_data()]} if "?" in path else self.run_data(status="completed")
        recover(api, 2, self.now)
