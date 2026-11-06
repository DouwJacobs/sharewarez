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

T06-T11 remain open. Next: persistent transfer reasons and attempt evidence.