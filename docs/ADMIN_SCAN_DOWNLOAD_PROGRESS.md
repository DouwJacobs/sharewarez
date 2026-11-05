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

### Continue with T02

T02–T11 remain open. Next implement the shared mode-aware target resolver,
restricted cleanup boundary, incomplete-enumeration handling and typed schedule
options. Individual-file automatic scans still need the T02 fingerprint work.
Manual candidate identity/session size belongs to T04; worker outcomes and
restart/cancellation ownership belong to T03. Do not infer those are fixed by T01.

No release, deployment, production SQL or proxy changes were performed.
