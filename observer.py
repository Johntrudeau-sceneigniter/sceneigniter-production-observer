"""Read-only production checks. Output contains an allowlist of health results only."""
import argparse
import datetime as dt
import json
from pathlib import Path
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

BASE = 'https://www.scene-igniter.com'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch(path, body=None, timeout=10):
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(BASE + path, data=data, headers={
        'User-Agent': 'SceneIgniterProductionObserver/1.0',
        'Content-Type': 'application/json',
    })
    try:
        response = urllib.request.build_opener(NoRedirect).open(request, timeout=timeout)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        raw = response.read(8_000_001)
        if len(raw) > 8_000_000:
            raise ValueError('response size limit')
        try:
            payload = json.loads(raw)
        except (ValueError, UnicodeError):
            payload = None
        return response.status, response.headers.get('Location', ''), payload


def timestamp(value):
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return parsed if parsed.tzinfo else None
    except ValueError:
        return None


def operations(payload, expected=''):
    if not isinstance(payload, dict):
        return {'valid_response': False}
    summary = payload.get('canonical_crawler_summary') or {}
    runs = payload.get('recent_runs') or []
    unresolved = 0
    for failed in runs:
        if failed.get('status') != 'failed' and not failed.get('failed_phases'):
            continue
        started = timestamp(failed.get('started_at'))
        recovered = any(
            run.get('workflow_name') == failed.get('workflow_name')
            and run.get('status') == 'success'
            and started is not None
            and timestamp(run.get('started_at')) is not None
            and timestamp(run['started_at']) > started
            for run in runs
        )
        unresolved += not recovered
    total = summary.get('total')
    return {
        'endpoint_healthy': payload.get('status') == 'ok',
        'established_regions_present': isinstance(total, int) and total >= 11,
        'no_crawlers_need_attention': summary.get('needs_attention') == 0,
        'no_unrecovered_failures': unresolved == 0,
        'api_worker_commits_match': (payload.get('running_commit') or {}).get('status') == 'ok',
        'expected_commit_matches': not expected or payload.get('deployed_commit') == expected,
    }


def collect(fetcher=fetch, sleep=time.sleep, now=None, expected=''):
    if expected and not re.fullmatch(r'[a-f0-9]{40}', expected):
        raise ValueError('expected commit must be a full lowercase SHA')
    now = now or dt.datetime.now(dt.timezone.utc)
    result = {'checked_at': now.isoformat(), 'healthy': False, 'checks': {}, 'crawler_day': {}}

    def check(name, path, predicate, body=None):
        try:
            status, location, payload = fetcher(path, body)
            passed = bool(predicate(status, location, payload))
        except Exception:
            passed = False
        result['checks'][name] = passed

    check('api_database', '/api/health', lambda s, _, p:
          s == 200 and isinstance(p, dict) and p.get('status') == 'ok' and p.get('database') == 'connected')
    for name, entity in [('public_profiles', 'Profile'), ('public_events', 'Event')]:
        check(name, f'/api/entities/{entity}/query', lambda s, _, p:
              s == 200 and isinstance(p, list) and len(p) > 0,
              {'query': {}, 'sort': '-created_date', 'limit': 1, 'skip': 0})
    check('google_auth_redirect', '/api/auth/google?returnTo=%2F', lambda s, loc, _:
          s in (301, 302, 303, 307, 308) and urllib.parse.urlsplit(loc).scheme == 'https'
          and urllib.parse.urlsplit(loc).hostname == 'accounts.google.com')

    # Keep collecting diagnostics even if the public-site checks fail.
    result['operations'] = {'valid_response': False}
    for attempt in range(4):
        try:
            status, _, payload = fetcher('/api/health/workflows')
            result['operations'] = operations(payload, expected) if status == 200 else {'reachable': False}
        except Exception:
            result['operations'] = {'reachable': False}
        if all(result['operations'].values()):
            break
        # Operational failures are evidence, not a reason to repeat expensive work.
        if result['operations'].get('endpoint_healthy') and not expected:
            break
        if attempt < 3:
            sleep(15)

    # Preserve previous/current Eastern day capture. Ledger unavailability is a
    # warning, as in the former private workflow, not a replacement health signal.
    today = now.astimezone(ZoneInfo('America/New_York')).date()
    for day in (today - dt.timedelta(days=1), today):
        try:
            status, _, payload = fetcher(f'/api/health/crawler-day?date={day.isoformat()}', timeout=60)
            available = status == 200 and isinstance(payload, dict)
            closed = payload.get('closed') is True if available else False
        except Exception:
            available, closed = False, False
        result['crawler_day'][day.isoformat()] = {'available': available, 'closed': closed}
    result['healthy'] = all(result['checks'].values()) and all(result['operations'].values())
    return result


def write_report(result, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    # Never log endpoint response bodies, redirect URLs, artist data or exceptions.
    print(json.dumps(result, indent=2))


def unavailable_report(now=None):
    return {'checked_at': (now or dt.datetime.now(dt.timezone.utc)).isoformat(),
            'healthy': False, 'error': 'observer_did_not_complete'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=Path('status/latest.json'))
    parser.add_argument('--expected-commit', default='')
    parser.add_argument('--mark-unavailable', action='store_true')
    args = parser.parse_args()
    snapshot = unavailable_report() if args.mark_unavailable else collect(expected=args.expected_commit)
    write_report(snapshot, args.output)
    raise SystemExit(0 if snapshot['healthy'] else 1)
