import copy
from contextlib import redirect_stdout
import datetime as dt
import io
import json
from pathlib import Path
import tempfile
import unittest
from observer import collect, operations, write_report


def good_ops():
    return {'status': 'ok', 'deployed_commit': 'a' * 40,
            'running_commit': {'status': 'ok'},
            'canonical_crawler_summary': {'total': 12, 'needs_attention': 0},
            'recent_runs': []}


class Fixture:
    def __init__(self):
        self.calls = []
        self.ops = good_ops()
        self.api_fails = False
        self.ledger_fails = False
        self.google_location = 'https://accounts.google.com/o/oauth2/auth?state=DO_NOT_PUBLISH'

    def __call__(self, path, body=None, timeout=10):
        self.calls.append((path, body, timeout))
        if path == '/api/health':
            if self.api_fails:
                raise OSError('DO_NOT_PUBLISH_PRIVATE_EXCEPTION')
            return 200, '', {'status': 'ok', 'database': 'connected'}
        if '/entities/' in path:
            return 200, '', [{'email': 'DO_NOT_PUBLISH@example.test', 'name': 'DO_NOT_PUBLISH'}]
        if '/auth/google' in path:
            return 302, self.google_location, None
        if path == '/api/health/workflows':
            return 200, '', copy.deepcopy(self.ops)
        if 'crawler-day' in path:
            if self.ledger_fails:
                raise OSError('DO_NOT_PUBLISH')
            return 200, '', {'closed': True, 'summary': {'private': 'DO_NOT_PUBLISH'}}
        raise AssertionError('unexpected endpoint')


class ObserverTests(unittest.TestCase):
    def test_healthy_observer_is_read_only_and_redacted(self):
        fixture = Fixture()
        result = collect(fixture, sleep=lambda _: self.fail('no healthy retries'),
                         now=dt.datetime(2026, 10, 21, 5, 30, tzinfo=dt.timezone.utc))
        self.assertTrue(result['healthy'])
        self.assertEqual(set(result['crawler_day']), {'2026-10-20', '2026-10-21'})
        self.assertNotIn('DO_NOT_PUBLISH', json.dumps(result))
        posts = [call for call in fixture.calls if call[1] is not None]
        self.assertEqual(len(posts), 2)
        self.assertTrue(all('/query' in call[0] and call[1]['limit'] == 1 for call in posts))

    def test_site_failure_still_captures_operations_and_both_ledgers(self):
        fixture = Fixture()
        fixture.api_fails = True
        result = collect(fixture, sleep=lambda _: None)
        self.assertFalse(result['healthy'])
        self.assertTrue(result['operations']['endpoint_healthy'])
        self.assertEqual(len(result['crawler_day']), 2)
        self.assertNotIn('DO_NOT_PUBLISH', json.dumps(result))

    def test_failed_phase_requires_a_later_success_of_the_same_workflow(self):
        payload = good_ops()
        failed = {'workflow_name': 'region', 'status': 'success', 'failed_phases': ['phase'],
                  'started_at': '2026-10-20T10:00:00Z'}
        payload['recent_runs'] = [failed]
        self.assertFalse(operations(payload)['no_unrecovered_failures'])
        payload['recent_runs'].append({'workflow_name': 'other', 'status': 'success',
                                      'started_at': '2026-10-20T11:00:00Z'})
        self.assertFalse(operations(payload)['no_unrecovered_failures'])
        payload['recent_runs'].append({'workflow_name': 'region', 'status': 'success',
                                      'started_at': '2026-10-20T11:00:00Z'})
        self.assertTrue(operations(payload)['no_unrecovered_failures'])

    def test_incomplete_or_unhealthy_operations_fail_closed(self):
        self.assertFalse(all(operations(None).values()))
        for field, value in [('total', 10), ('total', '12'), ('needs_attention', 1)]:
            payload = good_ops()
            payload['canonical_crawler_summary'][field] = value
            self.assertFalse(all(operations(payload).values()))
        payload = good_ops()
        payload['running_commit']['status'] = 'mismatch'
        self.assertFalse(all(operations(payload).values()))

    def test_expected_commit_is_optional_but_never_uses_the_monitor_repository_sha(self):
        self.assertTrue(operations(good_ops())['expected_commit_matches'])
        self.assertFalse(operations(good_ops(), 'b' * 40)['expected_commit_matches'])
        with self.assertRaises(ValueError):
            collect(Fixture(), expected='not-a-commit')

    def test_redirect_cannot_point_to_a_google_lookalike(self):
        fixture = Fixture()
        fixture.google_location = 'https://accounts.google.com.attacker.example/'
        self.assertFalse(collect(fixture)['checks']['google_auth_redirect'])

    def test_retries_are_bounded_and_ledger_warnings_do_not_erase_health(self):
        fixture = Fixture()
        fixture.ops['status'] = 'stale'
        sleeps = []
        result = collect(fixture, sleep=sleeps.append)
        self.assertFalse(result['healthy'])
        self.assertEqual(sleeps, [15, 15, 15])
        self.assertEqual(len([c for c in fixture.calls if c[0] == '/api/health/workflows']), 4)
        fixture = Fixture()
        fixture.ledger_fails = True
        result = collect(fixture)
        self.assertTrue(result['healthy'])
        self.assertTrue(all(not row['available'] for row in result['crawler_day'].values()))

    def test_snapshot_file_contains_only_public_allowlisted_results(self):
        result = collect(Fixture())
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'status/latest.json'
            with redirect_stdout(io.StringIO()):
                write_report(result, target)
            self.assertEqual(json.loads(target.read_text()), result)
            self.assertNotIn('DO_NOT_PUBLISH', target.read_text())


if __name__ == '__main__':
    unittest.main()
