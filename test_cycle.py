"""Pace a bounded cloud integration test without depending on cron delivery."""
from datetime import datetime, timezone
import os
from pathlib import Path
import time


def begin_cycle():
    end = datetime.fromisoformat(os.environ['RANKING_TEST_UNTIL'].replace('Z', '+00:00')).timestamp()
    last = float(os.environ.get('LAST_TEST_BUILD_STARTED', '0'))
    wait = max(0, last + 60 - time.time())
    if time.time() + wait < end:
        time.sleep(wait)
    needed = time.time() < end
    with Path(os.environ['GITHUB_OUTPUT']).open('a') as output:
        output.write(f"needed={'true' if needed else 'false'}\n")
    if needed:
        with Path(os.environ['GITHUB_ENV']).open('a') as output:
            output.write(f'LAST_TEST_BUILD_STARTED={time.time()}\n')
        print('Fetching a new one-minute test snapshot', datetime.now(timezone.utc).isoformat())
    else:
        print('Test window finished; skipping remaining cycles')


if __name__ == '__main__':
    begin_cycle()
