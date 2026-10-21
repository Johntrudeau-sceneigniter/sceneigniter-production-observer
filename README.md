# Scene Igniter production observer

Public availability monitor for
`Johntrudeau-sceneigniter/sceneigniter-production-observer`. The application repository stays private.

This is an independent, read-only monitor for Scene Igniter's public endpoints.
It needs no app source, customer records, API credentials, server login or paid
service. It runs on standard GitHub-hosted Linux compute, which is free for
public repositories. There is no paid fallback. Changing the repository to
private skips the job rather than starting billed compute. Skipped or stale
results are not successful monitoring.

## Coverage

- API and database health, public Profile and Event query availability.
- Google sign-in redirect, without following it or logging the OAuth state.
- Production workflow health, established crawler coverage, attention flags
  and unrecovered failures. A later success for the same workflow counts as
  recovery. API and worker revision mismatch also fails the check.
- Previous/current Eastern crawler-day ledger availability and closed status.
  Ledger unavailability remains a warning, as in the previous observer.
- Optional manual production commit verification. The monitor repository's
  own revision is never compared to the application's revision.

Public output is deliberately limited to timestamps and pass/fail results.
It contains no raw API responses, artist facts, email addresses, OAuth states,
budget amounts, crawler metrics, private app source or credentials. Full
crawler history and day ledgers remain in the existing production system.
The private application and its existing daily reports remain the place for
detailed diagnosis. This monitor does not run crawlers or paid AI jobs.

## One existing schedule, moved

The daily observer keeps its existing `05:30 UTC` time (1:30 AM Eastern during
daylight saving time and 12:30 AM Eastern during standard time). Manual runs
remain available. Remove the old private-repository observer before enabling
this schedule. Do not leave both schedules active.

Each run stores a small redacted `status/latest.json` commit, plus the normal
Actions result and summary. Meaningful daily evidence commits prevent public
repository scheduled workflows being disabled after 60 days of inactivity.
No artifact uploads, caches, new timers or paid services are used. Public
standard-runner compute is free; a larger or paid runner is not permitted.
The existing HeyCatch daily routine should treat an absent result older than
26 hours, a skipped run, or an unsuccessful run as a monitoring failure.

Failures remain failed jobs after evidence is saved. GitHub Actions provides
its normal failure notifications according to the owner's existing settings.
This does not create a separate notification service or send messages.

## Local verification

Run `python3 -m unittest -q` and `python3 observer.py --output /tmp/observer.json`.
The live command creates no account, checkout, subscription or browser visit.
Only two read-only entity queries use POST; all other requests use GET.
