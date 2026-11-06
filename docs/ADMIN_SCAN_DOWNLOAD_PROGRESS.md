# Admin, scan and download implementation progress

## 5 November 2026 — T01 picker and manual submission

Implemented on `fix/admin-scan-picker`, starting at `505c1756`, from
`ADMIN_SCAN_DOWNLOAD_HANDOFF.md`. The older Windows repair checkout is untouched.

- A readable folder returns its readable children even when another child is
  broken, inaccessible or resolves outside the configured root. The API retains
  its fields/order and returns `skippedItems` and `hasErrors`. Root failures retain
  their existing 403/404 behavior. Escaping targets are omitted before statting.
- Each picker owns its navigation cursor and latest-request counter. Late success
  and error callbacks cannot overwrite a newer result. Failed navigation retains
  the typed value and existing controls. Root submits `.`; empty folders say
  “No items here” without guessing whether a remote mount is absent.
- Folder/file names use text nodes inside native buttons. Folder mode explains
  that individual files require Files mode. Up and folder navigation support the
  keyboard, and successful navigation focuses the replacement folder control.
- Auto and Manual forms carry independent hidden actions. Manual pending state
  cannot discard its action; native Enter works and repeat submission is guarded.
  Both forms retain their draft across failed POST/redirect/GET. Missing automatic
  targets return to Scan Manager. Unchecked HLTB choices survive re-rendering.
- Canonical and installed default-theme JS/CSS are synchronized. Picker rows use
  shared buttons, wrapping labels and 44 px minimum mobile targets.

### Verification

The three new API regressions failed before the fix. After implementation:

- `test_routes_apis_browse.py`: 13 passed.
- `test_scan_picker_submit.py`: 3 passed, including a real listing POST assembled
  from the rendered form's successful hidden controls, with no submitter value.
- `test_utilities.py`: 11 passed.
- `test_routes.py -k scan_management`: 4 passed.
- `scan_picker.test.cjs`: 4 passed (late success/error, failed navigation, root and
  literal filenames/file mode, independent picker state).
- Ruff, the 93-template accessibility audit and `git diff --check` passed.

Database checks used a newly created PostgreSQL 14 cluster under
`/tmp/gamelibrary-t01-test/pg`, bound to loopback port 55439, and explicitly named
test databases. This is development evidence, not the PostgreSQL 17.6 release gate.

Computer Use inspected both forms on an isolated Flask preview with synthetic
storage and accounts. Default-theme desktop and 390 × 844 checks covered root,
empty folder, broken sibling warning, literal markup names, keyboard Up, and
folder-mode file feedback. An actual keyboard List Games submission returned its
redirect and discovered games. Mobile picker buttons measured 44 px; document
client/scroll widths both measured 375 px (390 px viewport including scrollbar).
The Ember override was also inspected on desktop. Temporary viewport overrides
were reset. Light theme, production mounts, no-JS browser interaction and full
worker journeys remain unverified. The real server-side form POST without a
submitter is covered; it does not substitute for a no-JS browser run.

### Next ticket at the T01 checkpoint

T02–T11 remain open. Next implement the shared mode-aware target resolver,
restricted cleanup boundary, incomplete-enumeration handling and typed schedule
options. Individual-file automatic scans still need the T02 fingerprint work.
Manual candidate identity/session size belongs to T04; worker outcomes and
restart/cancellation ownership belong to T03. Do not infer those are fixed by T01.

No release, deployment, production SQL or proxy changes were performed.

## 5 November 2026 — T02 scan authority and cleanup boundary

Implemented after `6bfaf586` on the same branch. No model or migration change.

- Browser, Auto/Manual, legacy manual, schedule create/edit/dispatch, worker and
  legacy restart execution share `utils/scan_targets.py`. Relative inputs use the
  active configured root; legacy absolute inputs must remain under a configured
  storage root. Worker validation happens before fingerprinting or scanning.
- Directory scans enumerate direct eligible children with resolved containment
  checks. Inaccessible/broken/escaping children make enumeration incomplete. Each
  candidate is checked again before processing. Single supported files work in
  Files mode, including fingerprinting; Folders mode rejects them with guidance.
- Removal checks are restricted by library, normalized stored path, selected
  target and mode. Root B, nested records, missing historical paths and ambiguous
  file-like folder records are retained. Actual database deletion coverage proves
  that root B and its related update record survive while the missing direct
  entry under A and its update are removed.
- Cleanup requires successful, complete, nonempty enumeration. It rechecks
  candidate membership, target identity, traversal completeness and cancellation.
  Failed processing, late cancellation, shutdown and failed missing-image work
  block cleanup. Skipped cleanup records “No removals performed” and its reason.
  Failed stats/walks cannot silently produce a successful fingerprint.
- Schedule JSON writes accept only the five supported boolean options. PATCH
  validates before mutating. Dispatch drops unsupported legacy keys/values and
  records an admin warning; options cannot override target/library/mode. Invalid
  due targets queue no job, record a warning and retry on the normal cadence.
- Manual permission probes skip child symlinks and use a selected file's parent.
  The legacy manual route delegates to the shared handler and redirects to its
  normal result workspace. Operator rules are in `OPERATIONS.md` and local
  `AGENTS.md`.

### Verification

The initial new cleanup regressions failed against the prior scanner. Final
PostgreSQL runs used a fresh `gamelibrary_t02_test` database per module in the
disposable loopback PostgreSQL 14 cluster used for T01:

| Module | Passed |
| --- | ---: |
| test_scan_targets.py | 18 |
| test_scan_safety.py | 12 |
| test_scan_schedule_safety.py | 15 |
| test_routes_apis_browse.py | 13 |
| test_scan_picker_submit.py | 3 |
| test_background_jobs.py | 16 |
| test_utilities.py | 11 |
| test_provider_neutral_scanning.py | 3 |
| test_utils_scanning.py | 28 |
| test_routes_apis_scan.py | 25 |
| test_routes.py | 62 |
| test_local_metadata_provider_identity.py | 4 |
| **Total** | **210** |

The schedule tests exercise CREATE, PATCH, dispatch and durable `claim_next` /
`execute` independently. The unsafe worker target fails without invoking the
fingerprinter/scanner or storing scan state. File-task coverage verifies one file
and its exact size rather than indexing siblings. Safety fixtures cover two roots,
actual related-row survival, modes, exact files, empty trees, broken/external
links, failed processing, nested permission errors, cancellation and shutdown.
Ruff across application/tests, focused Mypy for background jobs and
`git diff --check` passed.

Computer Use verified default-theme desktop rejection of a typed file in Folders
mode, retained input after the error, and a real Files-mode POST returning exactly
the selected file. The result was inspected at 390 × 844 with equal document
client/scroll widths of 375 px. The viewport was reset. These backend changes did
not alter templates or theme assets. Light/custom themes, production mount
disconnects, proxy behavior and release/container validation were not rerun.

### Continue with T03

T03–T11 remain open. In particular, the queue still needs an explicit scanner
outcome before it saves a successful fingerprint; restarts still need durable
queue ownership and deduplication. T02 blocks destructive cleanup independently
of those remaining lifecycle fixes. T04 still owns bounded manual selection and
stale results; the preview confirmed older results can remain visible after a
rejected manual POST. Do not claim either issue is fixed by T02.

No release, deployment or production-data changes were performed.

## 6 November 2026 — T03 durable scan attempts and recovery

Implemented after `cb7d6177`. Migration: `20261105_33` (one head).

- `utils/scan_execution.py` replaces the duplicated scan loops with explicit
  terminal results, counters, bounded parallel submission and cooperative stop.
  `utilities.scan_and_add_games` remains the compatibility entry point. Provider
  non-matches count as processed only when an unmatched record was persisted.
- Every durable attempt creates a fresh linked ScanJob before processing and
  assigns a new payload dictionary containing its ID. Failed/partial/cancelled
  paths finalize details and raise to the queue. Partial work uses status Failed
  plus outcome partial. Earlier terminal attempts are preserved on retry.
- Successful fingerprint persistence and queue completion share a locked
  transaction. Configuration, unit, finalization and fingerprint-store failures
  cannot appear successful. Cancellation at the success boundary saves no state.
- Restarts now enqueue through a locked original row and replacement-job pointer.
  Simultaneous requests reuse the same pending replacement. Known legacy fields
  are reconstructed; missing HLTB overrides default false. Both cancel routes use
  the durable owner; queued work is cancellable from Scan Manager.
- Worker shutdown finalizes cancellation; forced process death is reconciled by
  the next worker, preserving the interrupted attempt and creating another detail.
  Web startup leaves running scans alone. The existing two-container topology is
  preserved. Explicit scans/restarts force work; ordinary HLTB enrichment does not
  prevent an unchanged recurring skip.
- Single and bulk history deletion lock owners/details and retain active,
  pending-replacement and unmatched-referenced rows, reporting retained counts.
- Scan activity displays queued, partial, cancelled, interrupted and skipped
  states, separate counters, reasons and job links. Labelled actions have their
  own layout rather than inheriting fixed icon widths. Polling preserves unchanged
  DOM and restores surviving focus. Canonical/served default assets match.

### Verification

The initial no-file-types regression reproduced a completed durable job and saved
fingerprint under the old code. Final focused runs used a fresh PostgreSQL 14
`gamelibrary_t03_test` database per module in the disposable loopback cluster:

| Module | Passed |
| --- | ---: |
| test_scan_lifecycle.py | 20 |
| test_scan_worker_process.py | 1 |
| test_scan_safety.py | 12 |
| test_background_jobs.py | 16 |
| test_scan_schedule_safety.py | 15 |
| test_utilities.py | 8 |
| test_routes.py | 62 |
| test_routes_apis_scan.py | 25 |
| test_migrations.py | 10 |
| test_init_manager_fresh_database.py | 1 |
| test_utils_scanning.py | 28 |
| test_provider_neutral_scanning.py | 3 |
| test_container_layout.py | 2 |
| test_scan_picker_submit.py | 3 |
| test_routes_apis_browse.py | 13 |
| test_download_cache.py | 7 |
| **Total** | **226** |

The worker-process test ran `run_worker` in separate processes against synthetic
storage: an independent web initialization left its scan Running, SIGTERM
produced a terminal cancelled attempt, retry produced a fresh successful detail,
and SIGKILL/startup produced an interrupted old attempt followed by successful
recovery. The old cancellation history remained intact. Migrations passed fresh
metadata bootstrap, populated previous-revision upgrade, downgrade/re-upgrade,
historical upgrade compatibility and a single head. Twenty lifecycle scenarios
include concurrent restarts, both cancellation routes, skipped work, persistence
errors and cancellation during cleanup (one observed removal, no further ones).
Four standalone picker JavaScript cases, Ruff, focused Mypy, the 93-template
accessibility audit and diff checks also passed.

Computer Use verified default/Ember desktop and 390 × 844 states with synthetic
data. A real Restart POST queued a replacement without changing partial history;
Stop cancelled the queued replacement; Job details opened its correct owner.
The first visual pass found labelled-action overlap and the final pass verified
the corrected controls. Mobile buttons measured 44 px; document client/scroll
widths matched at 375 px mobile and 1265 px desktop. The desktop table uses one
internal scroller. Viewport overrides were reset. A default mobile screenshot is
saved in the task's visualization folder as `scan-lifecycle-mobile.jpg`.

### Continue with T04

T04–T11 remain open. The next item is bounded path-based manual candidate state,
including equal cleaned titles, stale selections and revalidation at identify.
No production data, release tags, deployment or proxy configuration was changed.

## T04 completed: bounded manual candidate identity

Baseline: e5901c28. Manual listing now stores only the owner, library, configured
root identity, relative target, mode, options and generation in the session.
Re-enumerated pages contain 50 candidates sorted by relative path. Identify GET
and POST revalidate the generation, library, containment, eligibility and current
existence; old or tampered selections return to Manual scan with an explanation.
The selected path is read-only, and file identity includes its extension. New
listing clears legacy candidate dictionaries, including when the target fails.
Listing is read-only even when local metadata writing is enabled. Standalone and
unmatched entry points retain their original behavior.

Changed production files: utils/manual_scan.py, utilities.py, routes.py, forms.py,
routes_games_ext/add.py, admin/admin_manage_scanjobs.html and its canonical CSS.
No migration. Tests: test_manual_scan_state.py (16), test_scan_picker_submit.py
(3), test_manual_game_identity.py (1), test_routes.py (62), test_utilities.py (8):
90 passed against disposable PostgreSQL, one fresh database per module. The 650
candidate regression renders 50 per page with session JSON below 1800 bytes.
Both equal-title files are independently saved; removed files, changed roots,
libraries, generations, types and POST identity tampering are rejected.

Computer Use against isolated gamelibrary_t04_preview_test verified a real List
Games POST, Game.iso and Game.zip opening their distinct read-only paths, next
and previous pages, and an old Identify URL after relisting. Default and Ember
were inspected at desktop and 390 x 844. Rows are flat with quiet dividers;
mobile Identify buttons measure 44 px and document client/scroll widths both
measure 375 px. Viewport override reset. Evidence: manual-candidates-mobile.jpg
in the task visualization folder. Ruff and diff checks pass.

T05-T11 remain open. Next: complete package selection and transactional link reuse.## T05 completed: complete packages and transactional link reuse

Baseline: 605ac6b8. source_entries in utils/download_sources.py now owns the
shared cached/live archive inclusion policy: stable relative ordering, ordinary
notes retained, configured/default update and extra folders excluded, metadata
files excluded, symlink entries skipped, escaped entries rejected and walk/stat
failures surfaced. The direct shortcut requires exactly one significant root
file and no included nested payload. Requested updates/extras use their own
validated source. Missing sources fail before any link/counter is created.

utils/download_creation.py serializes initiation with a User row lock before
looking up links by member, game, content type, record identity (including legacy
null identity) and source. Exact legacy duplicates remain addressable; the newest
is reused and duplicate IDs are logged for review. Counters use atomic increments
only for newly created links. Game and asset routes share this transaction.
Bookmarked GET/HEAD initiation URLs render a read-only confirmation; creation is
POST with CSRF. Game Details, mobile Get game, popup Download and asset buttons
use POST forms. Delivery GET/HEAD and byte-range behavior is unchanged. Expired,
failed and cancelled reuse currently opens Downloads for the renewal/retry UI;
T08 owns the shared eligibility/action resolver across all entry points.

Changed: asgi.py, async_streaming.py, utils/download_sources.py,
utils/download_creation.py, utils/download_cache.py, utils/zipstream.py,
routes_downloads_ext/initiate.py, download_confirm.html, Game Details/popup
forms and the canonical Game Details stylesheet. No migration.

Regression baseline reproduced missing POST support, mutating bookmarked GET,
and an external file symlink included by live ZIP. Final isolated PostgreSQL
checks: test_download_package_selection.py 13, test_routes_downloads_ext_initiate.py
15, test_download_cache.py 7, test_zipstream_async.py 2, test_download_ranges.py
18, test_download_admission_audit.py 4: **59 passed**, fresh DB per module.
The new suite submits concurrent normal POSTs through independent request/app
contexts and PostgreSQL sessions, asserts one link/one count, tests asset/member/
source identity, preserved legacy duplicates, GET/HEAD read-only behavior, CSRF,
missing sources, equal cached/live exclusions and an actual built ZIP containing
launcher, assets/required.bin and release notes. Ruff and the 94-template
accessibility audit pass. Required four-module Mypy plus both new helpers pass.
An expanded optional Mypy check of ASGI/cache reports existing nullable app and
archive-writer typing issues; comparison against HEAD confirms those predate T05.

Computer Use against gamelibrary_t05_preview_test submitted desktop game/update
POSTs and mobile Get game, confirmed Preparing, then reopened via bookmarked
confirmation POST. SQL shows one game link, one update link and game count 1.
Default desktop and Ember 390 x 844 confirmation were inspected. Mobile asset
buttons now measure 44 px; its single-column table no longer inherits a 680 px
minimum or block-table shrinkage. Viewport reset, temporary tab closed. Screenshots:
download-confirm-mobile.jpg and download-assets-mobile.jpg in the task artifacts.
Manifest timing was measured independently: 5,000 files in 50 folders took 0.380 s
on local disposable storage; this is not a network-storage latency claim.

T06-T11 remain open. Next: persistent transfer reasons and attempt evidence.## T06 completed: durable transfer evidence

Baseline: eddfde4d. Additive migration 20261106_34 (after 20261105_33) adds nullable
end_reason, delivery_kind, expected_response_bytes (big integer), correlation_id,
ended_by_user_id (User FK, SET NULL) and timezone-aware last_progress_at. Existing
rows retain null evidence and display Reason unavailable. No enum conversion or
historical cause inference. Model/bootstrap and previous populated-schema paths
are covered, including downgrade/re-upgrade and one head.

reserve_transfer accepts representation evidence. Fixed responses retain their
original selected length, including 206 ranges; live ZIP response length stays
unknown. ASGI ingress validates/generates correlation IDs, returns X-Request-ID
and logs rejected requests with a route pattern and correlation, without creating
a quota row. Read, ZIP generation, downstream send and progress-store observation
boundaries assign bounded reasons. Explicit http.disconnect records peer_disconnect;
task cancellation without an observed cause remains unknown. Successful completion,
stale heartbeat and explicit administrator stop have distinct reasons. The stop
endpoint records its actor. The first conditional terminal update wins; late
finalizers reconcile streamed/accounting bytes without replacing reason or actor.
Progress timestamps advance with reported byte changes, including finalization.
Raw exception text is never used as a member-visible reason.

History renders readable reasons beside terminal states; transfer_payload exposes
status, reason/label, original expected length, representation, correlation and
progress timestamps, with the actor ID in administrator payloads. T07 still owns
independent heartbeat, cancellable waits, inactivity timeout and early-EOF checks;
T08/T09 own shared member actions and bounded terminal-row live reconciliation.

Changed: models.py, utils/download_limits.py, utils/transfer_evidence.py,
asgi.py, live_snapshots.py, routes_downloads_ext/admin.py and its template;
migration 20261106_34; new transfer evidence tests and migration assertions.
Initial regressions reproduced missing read/write reasons and terminal-reason
persistence. Final disposable PostgreSQL run (fresh DB per module):
test_transfer_evidence.py 14, test_migrations.py 12, test_download_limits.py 9,
test_download_admission_audit.py 4, test_download_ranges.py 18,
test_routes_downloads_ext_admin.py 21, test_live_sse.py 15,
test_live_snapshot_cache.py 2: **95 passed**. Tests inject actual source/send/progress
boundary failures, archive generation error and disconnect; cover concurrent
terminal decisions, actor preservation, stale cleanup, original range length,
validated and rejected correlation IDs, historical display and progress clocks.
Migration tests preserve populated old rows, an 8 GB length, actor SET NULL,
metadata-created foreign keys and idempotent upgrade. A fixture read transaction
initially held a downgrade lock; it was verified/cancelled in the disposable DB
and corrected by ending the read transaction before DDL. Final migration run passes.
Ruff, required four-module Mypy plus transfer_evidence.py, accessibility (94
templates) and diff checks pass.

Computer Use verified default desktop and Ember 390 x 844 history with distinct
source/write/admin reasons and Reason unavailable. A real stop POST completed;
SQL confirms attempt 5 is cancelled/admin_stop, actor 1, bytes/reservation 20.
The browser initially stalled during that click; a fresh tab and SQL independently
verified its result. Mobile document client/scroll widths both measure 375 px;
the history table owns its internal scroller. Viewport reset and tabs closed.
Evidence: transfer-reasons-mobile.jpg in the task visualization folder.

T07-T11 remain open. Next: stream liveness, cancellation and fixed-length integrity.## T07 completed locally: liveness, cancellation and representation integrity

Baseline: 5c19eb31. Both direct/cached files and live ZIPs now share
utils/stream_control.py: a transfer-owned heartbeat every 10 seconds, independent
of reader, pacing and downstream send, with the existing 60-second stale limit.
Heartbeat SQL only renews last_activity_at. Byte progress retains approximately
one-second cadence; last_progress_at advances only with reported bytes. A
transient heartbeat failure retries; unresolved authority loss stops before the
stale deadline. In-flight heartbeat calls never overlap for the same transfer.
A bounded four-thread bookkeeping executor keeps ownership and quota/lease/slot
cleanup available when storage-reader threads are saturated.

Each read and downstream write has an initial 300-second wait budget. Intentional
rate-limit sleep has its own budget and is sliced at 0.25 seconds. Disconnect and
authoritative stop interrupt read/send/pacing waits; stall_timeout identifies an
I/O deadline. Heartbeat and watcher tasks are cancelled and awaited in finally.
Repeated cancellation cannot abandon the complete finalizer. Late handler failure
never emits another status or a synthetic successful end-of-body after headers.

utils/stream_io.py owns a single open file for fstat, headers, seeks and body;
path replacement after headers cannot switch representations. A short promised
length raises source_read_error and never completes. Blocking calls and ZIP
iteration run off the event loop, and generators close on every exit. A kernel
read cannot be forcibly cancelled by Python: after consumer cancellation its
resource remains owned until that call returns, then closes exactly once on a
separate bounded close executor. Accounting/slot cleanup uses bookkeeping workers
and does not wait for that kernel read. Late open results are reclaimed too.
This is safe deferred ownership, not a claim that an unresponsive mount can be
interrupted by an application timeout. No production mount/proxy changes.

Live archive byte estimates now use the same safe manifest/exclusions as delivery.
Archive failure diagnostics no longer write synchronous DB logs on the ASGI loop.
HEAD, 206, 416, If-Range, cached archive ETags and owner checks remain intact.
Changed: asgi.py, async_streaming.py, utils/download_limits.py,
utils/transfer_evidence.py, utils/zipstream.py, new stream_control.py/stream_io.py;
new test_stream_liveness.py and evidence tests adjusted to disconnect after
reservation and to force the progress cadence explicitly. No migration (head
remains 20261106_34).

Initial regressions reproduced silent short EOF and headers/body reading different
path versions. Final PostgreSQL modules (fresh gamelibrary_t07_test per module):
test_stream_liveness.py 28, test_transfer_evidence.py 14,
test_download_admission_audit.py 4, test_download_ranges.py 18,
test_zipstream_async.py 2, test_download_limits.py 9,
test_download_maintenance.py 2, test_download_cache.py 7: **84 passed**.
Controllable-clock tests exercise 10/60/300-second boundaries, planned pacing
past five minutes, transient and hanging bookkeeping, and stop during every wait.
Actual direct/live paths survive simulated 70-second I/O waits with DB heartbeat
renewal and no invented byte progress, then complete or retain admin_stop. Tests
cover reader-executor starvation, late open/read cleanup, repeated cancellation,
truncated-file persistence and no second response. Real ASGI admission + cached
ZIP build tests hash interrupted prefix + 206 remainder for both a 5 MB file and
its cached ZIP, assert two attempts and exact accounting, closed descriptors,
zero queued admissions, no held slots/archive advisory leases and zero dedicated
pool checkouts. Ruff, required four-module Mypy plus new I/O/control and streaming
modules, and diff checks pass. No UI markup/style changed in this ticket.

**Before release:** repeat on a slow staging storage mount with the existing web
and worker processes. Verify a live low-rate transfer past 60 seconds stays
active, planned pacing past 300 seconds is not a stall, a genuinely blocked read
or send reaches stall_timeout, and administrator stop/disconnect releases quota
and admission promptly. Observe whether the mount's kernel I/O returns and its
retained descriptor closes. Hash prefix + resumed output for a file and cached
ZIP through the real staging ingress. Validate the initial 300-second default
there; changing production proxy/mount settings remains separate operator work.

T08-T11 remain open. Next: one shared member action/state resolver.## T08 completed: one member state/action authority

Baseline: 9976c39c. utils/download_state.py now derives member presentation and
allowed actions together. Active attempts take precedence, with bytes/progress
and no conflicting link controls or duplicate Downloading button. Expiry is
computed from the actual timestamp even before maintenance updates stored status;
expired/cancelled links expose Renew/Retry only, and fallback cannot revive them.
Preparation uses one policy path for new links, member retry and admin bulk retry:
off makes directory links available as live ZIPs; prefer prepares cache or allows
live fallback only when enabled; require/unavailable persists a recoverable failed
link. Renew validates its source before changing expiry or representation.

The HTML, download_payload/SSE, bounded polling and action handlers share that
resolver. Actual prepared paths determine resumability, including a direct file
inside a source folder and legacy file-only/completed rows. Existing healthy
cached artifacts retain their representation, including while original storage
is offline. Missing/unsafe sources offer a reason plus secondary Remove link;
known archive causes use bounded public messages once. Latest relevant attempt
and allowed actions are included in live/polled payloads. Member transfer context
is bounded to requested, owned links; shared archive ownership does not make
another member's attempt appear. Counts explicitly describe this page.

Mutations lock the User and reload the link before checking active state, expiry,
source and current policy. New HTTP admission rechecks the link and prepared
representation under that same User lock, returning a correlated 409 without a
quota row if they changed. Existing transfers can finish their open representation.
Reopening from Game Details respects the same actions and never starts another
transfer or renews an active/expired link implicitly. Legacy exact file-only paths
reuse their historical link IDs. No destructive merge or schema change.

Server forms remain in place through JS updates. Removing a link is secondary
and explicitly labelled; original files and attempt records are not deleted.
Cancelling one member's preparation does not cancel a shared archive build.
Administrative revocation/removal remains role-specific, but active attempts
block conflicting bulk operations. The legacy check_download_status wrapper keeps
its stored status field for compatibility and adds a canonical download object;
the member page uses the canonical status endpoint.

Changed: new utils/download_state.py, download_creation.py/download_limits.py,
asgi.py, member/initialization/API routes, live_snapshots.py, member template,
canonical downloads_manager.js and download stylesheet; new test_download_states.py
and strengthened live snapshot fixtures. No migration; head remains 20261106_34.
Initial regressions reproduced terminal fallback revival, active retry mutation
and cache-off retry remaining failed. Final disposable PostgreSQL runs (fresh DB
per module): state matrix 37, package selection 13, member routes 19, download API
18, SSE 15, snapshot cache 2, stream liveness 28, initiation 15, cache 7, admin
routes 21, admission 4, transfer evidence 14, ranges 18, audit security 10:
**221 Python tests passed**. Seven standalone live JavaScript checks pass. Cases
include first HTML vs SSE/polling, original source offline, expired cached links,
policy/source changes during POST, two owners, cancelled/shared/admin-stopped
builds, serialized double retry, a transfer committed while the POST waits for its
owner lock, and representation changes before quota admission. Required Mypy plus
both state/creation helpers, Ruff, 94-template accessibility and diff checks pass.

Computer Use against gamelibrary_t08_preview_test verified real Renew and Retry
POSTs retaining link IDs and moving into Preparing; direct-file resumability after
poll fallback; unknown source removal without a misleading retry; and one
Downloading label with zero actions. A synthetic attempt terminal update appeared
with its actual last-attempt reason through polling, without a reload. Default
desktop and Ember 390 x 844 were inspected; buttons measure 42/44 px and document
client/scroll widths match (1265 desktop, 375 mobile). A visual pass caught lost
status color modifiers after polling; the corrected live Ready/Failed/Preparing
classes preserve green/red/amber. Viewport reset and final tabs closed. Evidence:
member-states-mobile.jpg in the task visualization folder.

T09-T11 remain open. Next: separate administrator Activity/Links views and hide
finished attempts without changing quota accounting.
## 6 November 2026 — T09 admin delivery views and retained accounting

Implemented separate Activity (default) and Links views. A shared normalized query
contract in `utils/admin_delivery.py` owns legacy URL inference, literal username
search, view-specific filters, deterministic sorting and 10–100 row pagination.
Transfer filters win mixed legacy URLs. Tabs retain username/per-page and reset
page; View attempts carries the link ID; browser Back restores the prior query.
Activity owns one identified row per attempt, live metrics, Resumed, terminal
reason and Stop transfer. Links owns stored state, expiry, queue priority and
reusable-link actions. Bulk actions start disabled and report changed/skipped.
Navigation, dashboard destinations and the settings shortcut use Download delivery.

Migration `20261106_35` adds nullable `admin_history_hidden_at`. The retained legacy
clear URL now hides finished attempts matching the current Activity filters,
across all pages, using the same predicate for preview and update. CSRF plus an
actor-bound signed filter/count review prevents accidental widening; stale counts
roll back with 409. Active/unknown-outcome attempts are excluded. Accounting,
statistics and member latest-attempt queries continue to use the retained rows.
Single-link administrator deletion now shares the owner lock with admission so a
transfer committed while deletion waits prevents deletion.

HTML, SSE and polling share the same scoped page query. Live events re-fetch one
bounded Jinja fragment, including actual terminal outcomes and fresh reviewed hide
counts; no global active list bypasses filters. Focus, selections, checked bulk
rows and open dialogs defer replacement. Snapshot keys include normalized filters,
page, view/role and member identity where required; local commits and PostgreSQL
signals invalidate the process cache. Admin fragment requests add per-viewer work;
the September performance figures are historical. Current snapshot cost coverage
checks 30 unshared versus 12 shared queries for ten independently authorized
viewers. Production capacity remeasurement remains part of release validation.

### Verification

The two initial regressions failed on mixed link/attempt rendering and unreviewed
history deletion. Final isolated PostgreSQL verification passed **187 Python tests**
across admin routes (48), SSE (19), snapshot cache (3), download APIs (18), migrations
(13), UI contracts (20), live events (6), member routes (19), snapshot performance
(1), navigation (3) and canonical states (37). JavaScript transport checks: **8**.
Required four-file Mypy, Ruff, 95-template accessibility and diff checks passed.
Old UI assertions expecting the removed web-owned restart thread and scan progress
column were updated to the durable restart/Status contract introduced by T03.

Migration tests cover populated revision 34 upgrade, retained reservation/reason,
null default, downgrade/re-upgrade, metadata-created columns and one current head.
Filter tests cover both pagers, legacy precedence, literal wildcard input, malformed
filters, role guards, stale/tampered/missing preview data, terminal transitions and
two simultaneous filter/cache scopes. A real quota admission check returns the
same `(None, 133, 200)` before/after hiding, with a second owner and active attempt
preserved; latest member recovery evidence remains queryable. Both admin deletion
routes also retain a link when an admission commits while they await its owner lock.

Computer Use exercised the disposable ASGI fixture on 5013 and a polling-only
Flask fixture on 5014, both using `gamelibrary_t09_preview_test`. One link showed
two attempt IDs in Activity and one row in Links; View attempts/Back retained scope.
The open ASGI page reconciled an active attempt to Interrupted/peer disconnect,
while an unmatched-username tab stayed empty. The polling-only page independently
reconciled a legacy attempt to Interrupted/source-read failure. A real filtered
hide POST hid two demo-member attempts; SQL retained both rows and **580245** quota
bytes, plus the other member's **555** bytes and visible history. The native browser
confirmation required keyboard confirmation through Computer Use after the browser
API stalled; the page and SQL verified completion. No production state was used.
Default desktop and Ember 390×844 checks verified 42/44 px controls, one 12 px mobile
gutter, table-owned horizontal scrolling, bulk disabled/enabled states and a centered
link-action dialog. Temporary viewport override was reset. Artifacts:
`delivery-activity-desktop.jpg`, `delivery-activity-mobile.jpg`,
`delivery-history-hidden.jpg`, `delivery-polling-terminal.jpg` in the task directory.

T10 settings ownership and T11 integrated journeys remain. The overall goal stays
active; release/deployment and the previously recorded slow-mount staging check
remain outside this local implementation work.

## 6 November 2026 — T10 settings ownership and completion-time policy

Application Settings now posts only changed keys in the visible category, using
an explicit `{section, settings}` envelope and server allowlist. Existing flat JSON
and former-URL POST clients remain compatible. The merge reloads/locks the row;
first creation is serialized. The same lock boundary covers archive policy,
branding, site-default theme and metadata changes; theme-delete fallback reloads
before merging. Existing column mappings, zero values, notification-rule side
effects and cache invalidation are preserved. Inactive categories retain their
drafts and cannot block a save through native validation. Failed/in-flight saves
retain edits correctly. Category URLs and browser history restore the selection.

All metadata credential writes, including setup and both legacy IGDB POSTs, now
use one service. Credentials-only compatibility saves retain RAWG/provider order;
blank secrets retain stored values, and failures return a bounded message. The
Integrations controller derives every tab from its controls, accepts SMTP and
Metadata aliases, resolves Discord flash navigation centrally, and restores
Webhooks on reload. Metadata & enrichment and Metadata providers link to each
other. Configure has one Application Settings entry while notification deep links
remain valid. The manual Discord group and three delivery destinations are named
according to their actual behavior; help describes cache modes and queue timeout.

Profile now links to Account Settings instead of duplicating its five preference
fields. Returning from that editor restores Profile → Preferences. Personal
notification matrices, the existing full-page submitter and the legacy modal
response remain compatible. The modal caller inventory and runtime ownership are
documented in SETTINGS_OWNERSHIP.md; other controls were retained.

Auto, Manual and Schedule place optional overrides under Advanced scan options;
cleanup remains explicit. Both HLTB choices show inherited global availability
and are disabled when the policy is off. Execution reloads settings, and manual
identification checks the selected option and the global column again. Saved
schedule choices survive disable/re-enable; optional lookup failures preserve an
identified game. No schema migration was needed (head remains 20261106_35).

### Verification

Six initial regressions failed before the fix: nested transport fields persisted,
category boundaries were unenforced, and a stale loaded settings record overwrote
a concurrent legacy POST. Final independent PostgreSQL module runs passed **335
Python tests**: settings 44, account routes 26, navigation 3, manual selection 21,
scan lifecycle 21, provider helpers 15, IGDB compatibility 27, UI contracts 20,
notifications 3, notification delivery 8, download notifications 3, background jobs
16, scan APIs 25, setup 23, branding 6, theme routes 43 and theme utilities 31.
Five new JavaScript tests execute the real settings/tab controllers, including
zero values, hidden drafts, failed-save retry, in-flight edits and future tab
controls. Ruff, seven-file Mypy (the four required modules plus the new services),
95-template accessibility, source compilation and diff checks passed.

Concurrency coverage pins a stale settings object in one session, commits a
second administrator's site URL edit, then submits Application Settings, cache
policy, branding or site-default theme. All four retain the newer unrelated value.
HLTB coverage queues a schedule while enabled, disables policy before execution,
checks both lookup paths stay off and stored choices remain true, then re-enables
and executes the saved choices. Manual identification covers the global/per-run
truth table; all six rendered scan controls inherit availability. Existing setup,
credential, notification and conditional-navigation regressions remain green.

Computer Use verified the disposable `gamelibrary_t10_preview_test` on port 5015.
Two stale tabs submitted only the changed General site URL and Downloads zero
bandwidth/wait fields; captured JSON and SQL verified both survived. An unfinished
URL draft in General did not block a Downloads save and survived tab/back changes.
Webhooks, Email, Metadata providers and Discord retained their pane on reload;
Back and the SMTP alias worked. An actual account save retained 50 items per page
and Ember while preserving notification controls and return navigation. A dummy
provider connection test updated its tested timestamp and restored its button;
the rendered stored-secret field stayed empty. No external metadata service was
contacted and no production data was used.

Default desktop and Ember/default 390×844 checks covered category navigation,
advanced disclosures, disabled HLTB controls and prerequisite links, account/profile
handoff, three delivery destinations and guide text. Ordinary fields/actions
measure 42 px desktop and 44 px mobile; mobile client/scroll widths both measure
375 px in the 390 px viewport. Authored/served JS and CSS match. Temporary viewport
overrides were reset. Artifacts include settings-ownership-mobile.jpg,
webhooks-reload-mobile.jpg and hltb-disabled-mobile.jpg in the task directory.

T11's full scan/download journeys and completion audit remain. The goal stays
active; production release, publishing, SQL/proxy/mount changes remain excluded.
