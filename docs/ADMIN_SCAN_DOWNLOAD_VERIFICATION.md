# T11 integrated implementation verification

Client date: 6 November 2026. Repository: `/home/douw/sharewarez`, branch
`fix/admin-scan-picker`. Original baseline: `505c1756`; T11 started at `56e96fd5`.
This records implementation acceptance, not a production release approval.
The original `ADMIN_SCAN_DOWNLOAD_HANDOFF.md` remains untouched.
Notification rules remains an admin-only search shortcut to its settings section;
the full sweep caught this compatibility gap after navigation consolidation.

## Completion audit

| Ticket | Implementation commit | Acceptance evidence |
| --- | --- | --- |
| T01 picker/submit | `6bfaf586` | Browse and native submit regressions; journey A listed two files beside a skipped broken sibling. |
| T02 target/cleanup | `cb7d6177` | Target, schedule and fingerprint tests; journey A retained offline B and the other library while deleting only eligible Missing A. |
| T03 durable worker | `e5901c28` | Failure/cancel/retry/partial tests and actual worker shutdown/crash test; journey A independently restarted web, cancelled worker-owned work and queued a fresh detail. |
| T04 manual identity | `605ac6b8` | Bounded selection, generation/path/library revalidation tests; browser independently identified equal cleaned titles. T11 also fixes the post-save image thread ownership defect. |
| T05 package/link | `eddfde4d` | Manifest/symlink/update/extra tests and PostgreSQL concurrent creation tests; browser POST reached Preparing, actual worker built nested assets, repeated initiation retained the original link. |
| T06 attempt evidence | `5c19eb31` | Distinct source/write/progress failures, first-terminal races, populated/fresh migrations; journey B observed peer_disconnect. T11 exposes UTC, range and full content/response evidence. |
| T07 stream integrity | `9976c39c` | Independent heartbeat, slow I/O, pacing, cancellation, EOF and owned-resource tests; real HTTP prefix + 206 matched SHA-256 for file and immutable ZIP. |
| T08 member state | `df01381d` | Shared HTML/live/polling/action matrix, ownership/admission races and archive policies; browser Preparing -> Ready/Resumable, recovery explanation and forced polling preserved labels. |
| T09 activity/quota | `30393afb` | Separate filtered views, bounded reconciliation, signed hide predicate, quota/second-owner/active-attempt tests; browser hiding retained the actual HTTP attempts and exact quota. |
| T10 settings | `56e96fd5` | 335 Python + 5 controller tests, stale-tab native saves and integration reloads; see SETTINGS_OWNERSHIP.md and progress record for settings readers and compatibility. |
| T11 integration | current change | Both journeys below, final presentation regressions, full independent module sweep and local static checks. Release prerequisites remain explicitly separate below. |

The ticket contracts take precedence over later design alternatives. Existing
Scan Manager navigation/actions remain Auto scan, Manual scan, Add schedule and
Start Scan. Cleanup remains explicit, and terminal scan clearing reports removed
and retained counts while preserving active/referenced details. Download statistics
are labelled completed **transfers**, not whole files or games saved by a browser.
No control was removed without its reader/compatibility audit recorded under T10.

## Journey A: actual browser forms and dedicated worker

A synthetic fixture used `gamelibrary_t11_preview_test` on the disposable
PostgreSQL 14 instance at `127.0.0.1:55439`, ASGI port 5016, and dedicated
`/tmp/gamelibrary-t01-test/t11/{storage,cache}` directories. No operator DB,
mount, configuration file or production process was used. Seeding and server
startup were separate so restarting web never rewrote source bytes/mtime.
Browser forms used CSRF; synthetic login routes existed only in the temporary
fixture. Admin and member used localhost and 127.0.0.1 respectively to isolate
cookies. Provider enrichment was disabled; no real provider request was needed.

1. Manual Browse displayed A, B and Packages, plus the warning that one broken
   sibling was skipped. Use this folder selected `.`. Files mode + A + the real
   List Games button posted `submit=ManualScan`, returned 302, and rendered
   `A/Equal Game.iso` and `A/Equal Game.zip`, both displayed as Equal Game.
2. Each Identify button retained its independent generation/path. Both files
   were saved with local identities. The first save exposed a real post-commit
   image-thread race (500 after the row had been committed). The fix captures
   the scalar game UUID and application before starting a thread, gives that
   thread its own app/session context, and never passes the request ORM object.
   A real-thread regression fails before the fix; the subsequent native save
   returned 302 with Game added successfully. Both distinct paths/identities
   were verified in SQL. The failure remains recorded rather than erased.
3. Native Create schedule posted library Journey A, Files, A, remove_missing=on.
   Root B was moved outside the configured fixture root to simulate offline
   storage. Native Run now enqueued durable job
   `fc6eb850-f5c4-4b75-9902-70436ec2e7d1`, whose payload persisted scan detail
   `40d06eb3-221d-4dc1-8b9a-8608eaf60afc` before processing.
4. The actual job_worker was held at a bounded fixture work-unit gate. Restarting
   the web process independently retained Running. Stop showed Stopping; releasing
   the unit let production cancellation finish. The durable job was cancelled,
   detail outcome cancelled, matched 1/2, removed 0, with no fingerprint saved.
5. Native Restart queued `f7f942de-e8c3-487b-b8b7-47f46fb47d1b` and fresh detail
   `71a56dcb-e498-4cc4-89d9-acf294cac2ba`. The real worker completed 2/2 matched,
   0 unmatched/failed, removed exactly 1 and persisted one fingerprint.
   SQL proved Missing A in Journey A was gone; Missing B and the other library's
   missing A remained. Browser activity displayed Completed and prior Cancelled,
   agreeing with durable result counters.

Captured native POST bodies/statuses (CSRF omitted) are in the temporary
`browser-posts.jsonl`; worker/web logs and SQL assertion scripts accompany it.
Actual worker SIGTERM/retry/SIGKILL recovery is additionally covered by
`test_scan_worker_process.py`; this journey's web restart did not stop its worker.

## Journey B: native initiation, real socket interruption and resume

The browser's bookmarked GET was a read-only confirmation. Prepare download
posted normally and displayed Preparing with connected live updates while the
worker was stopped. Starting the actual job_worker built a ZIP containing
`assets/payload.bin`, `launcher.exe`, `readme.txt`, and ordinary `metadata.json`.
Configured updates/extras were excluded. Ordinary metadata.json is deliberately
not a reserved local-metadata filename; dedicated tests cover exclusions of
`gamelibrary.json`/`sharewarez.json` and escaping symlinks.

The native browser exercised form serialization and UI state. A separately
authenticated HTTP consumer exercised the same real ASGI ingress over TCP and
retained the prefix for byte comparison; no claim is made that browser disk writes
were verified. The 32 Mbps fixture cap made interruption observable.

| Evidence | Immutable ZIP, link 1 | Direct file, link 2 |
| --- | --- | --- |
| Full length | 16,777,876 bytes | 16,777,216 bytes |
| Original response / probe | GET 200 / HEAD 200 | GET 200 / HEAD 200 |
| Retained prefix | 2,097,152 bytes | 2,097,152 bytes |
| Terminal observation | interrupted / peer_disconnect | interrupted / peer_disconnect |
| Resumed response | 206 | 206 |
| Range | 2097152-16777875/16777876 | 2097152-16777215/16777216 |
| Remaining bytes | 14,680,724 | 14,680,064 |
| Reassembled SHA-256 | 54d99dfbe437bed6cca5e1655012b2762e00ee28dc109bc304fb8f7fc014b5a4 | 341aacac661ccb210720bedaa9ead5d668fe5ea41a73532fc147c71e34040df1 |

Both hashes matched their unchanged source exactly. ZIP ETag was its immutable
SHA-256; direct-file ETag remained `"1000000-18e58536351ee195"`. Resume used the
same authenticated link with Range and If-Range. The recorded expected length
was the selected response length; HEAD introduced no attempt. ZIP attempts 1/2
were interrupted/completed under one reusable link. Admin saw the measured peer
reason and UTC evidence; member saw Ready/Resumable with browser-resume guidance.

A later native repeat confirmed reuse of link 1, then redirected into a fresh
response which the in-app browser closed (attempt 3, 0 bytes). Native direct-file
initiation likewise closed its redirected response (attempt 4, 2 MiB). These are
retained observations, not silently removed test rows. The controlled direct-file
HTTP recovery used attempts 5/6. Final fixture therefore has two links and six
attempts; the initial ZIP recovery phase had exactly one link and two attempts.
Server-sent bytes measure response writes, not confirmed browser-saved bytes.

The browser reviewed and hid the three finished link-1 attempts. All six rows
remained. Monthly reserved bytes and bytes_sent both totalled 35,652,244, with
zero unsettled differences. With quota 1,000,000,000, remaining allowance was
**964,347,756 before and after**. The member's latest attempt remained visible;
link-2 attempts stayed in admin Activity. A nonexistent username produced zero
rows. Separate unit/concurrency tests cover a second owner, active attempts,
unstarted links, shared archives and deleted-link evidence during hide operations.

Web restart closed the real SSE connections. A fixture ingress switch returned
503 to new SSE requests while ordinary polling remained available. Both screens
showed Live connection unavailable / refreshing periodically; Ready/Resumable,
latest evidence and recovery text remained consistent. At 390x844, document
scroll width was 375 with no horizontal overflow; the admin table owned its
internal scroll. Expanded attempt detail survives live fragment replacement and
focused controls defer replacement. Summary targets have 42/44 px minimum heights.

At the end there were zero active fixture transfers, zero advisory locks for the
fixture DB, and no fixture source/cache handles in web or worker `/proc/*/fd`.
The agent's fixture tabs were closed and viewport overrides reset.

## Local verification and remaining release prerequisites

Final module results: **2,182 passed across 146 modules**, after fresh-DB reruns
for final fixes; no skipped tests. The first sweep exposed three compatibility
modules (search, mobile assertion strings and isolated CSRF context), all fixed.
Two unchanged legacy expiry modules failed under the disposable cluster's inherited
Africa/Johannesburg session timezone. They passed with test-only PGOPTIONS setting
session timezone=UTC, consistent with the release image default. Their aware-to-naive
timestamp writes assume UTC database sessions; verify the deployed session zone
before release or separately normalize those legacy writes/data. No authentication
code, production timezone or historical timestamps were changed. The progress
record preserves this distinction; this is not a claim that the initial sweep was
green under every timezone. All four controller files passed `node --test` (19
runner cases, including six internal favorites cases).
Every DB-backed module uses a freshly recreated explicitly named disposable test
DB with pg_trgm and both DATABASE_URL/TEST_DATABASE_URL set. The application uses
Python 3.12.8. Standalone controller tests run with Windows Node on byte-identical
copies because its native test runner mishandles UNC path arguments.

Local checks: reproducible production lockfile (72 exact pins), pip check,
correctness Ruff, seven Mypy modules (the four required plus navigation/evidence/state helpers), compileall, 95-template accessibility,
version 1.16.2 and a single Alembic head 20261106_35. No new migration in T11.
Migration tests cover populated upgrade/downgrade and fresh non-model bootstrap.

**These implementation checks do not pass the production release gate.**
Docker is unavailable here: the PostgreSQL 17.6 gate, Compose validation, image
build and packaged smoke compilation must run with `./scripts/quality-gate.sh`
before release. The independent pip-audit reported dnspython 2.8.0,
CVE-2026-114605, fixed in 2.9.0. Review/update that transitive pin in both lockfiles
and rerun dependency/compatibility checks before release. This implementation
change does not silently refresh unrelated dependency pins.

In staging, repeat a multi-GB direct file and immutable cached ZIP through the
actual authenticated deployed proxy, interrupt and resume with Range/If-Range,
verify reassembled SHA-256, compare direct-to-app versus proxied delivery, and
capture correlated response/reason evidence. Repeat with slow storage, throttling,
web/worker replacement and changed source; verify the five-minute I/O policy and
resource release on the real mount. Change no production timeout/mount/proxy policy
without that evidence. The historical screenshot does not establish an incident
cause. Publishing, production SQL, proxy/mount changes and deployment remain
outside this implementation goal.

Browser artifacts are in the Codex task directory:
`journey-preparing-desktop.jpg`, `journey-attempt-details-desktop.jpg`,
`journey-attempt-details-mobile.jpg`, `journey-recovery-mobile.jpg`, and
`journey-history-hidden.jpg`.
