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
