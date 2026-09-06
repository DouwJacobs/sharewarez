# Audit remediation — 5 September 2026

This tracks the fixes for [the full audit](FULL_AUDIT_2026-09-05.md). The audit
remains the original evidence record. An item is only marked verified for the
scope of the checks recorded here; completed full-suite and browser verification are recorded below.

| Finding | Status | Implementation and evidence |
| --- | --- | --- |
| A1: member catalogue mutation | Fixed; focused tests pass | Administrator guard on move endpoint; member denial preserves library assignment. |
| A2: disabled sessions | Fixed; focused tests pass | Flask loader and user authentication state reject disabled records; direct downloads use SSE account validation in a thread. Existing-session read/mutation and direct-download regressions pass. |
| A3: AJAX attribute injection | Fixed; focused tests pass | Shared autoescaped Jinja card fragment replaces JavaScript string renderer. Hostile attribute/HTML payload regressions pass. |
| A4: sensitive logs | Fixed; focused tests pass | Removed form/token dumps and SMTP protocol debugging. Request logs use route patterns, including a safe unmatched-route marker. Synthetic password/path token regressions pass. |
| A5: fresh search bootstrap | Fixed; focused tests pass | Revision 25 repairs omitted extension/index DDL; fresh bootstrap includes it. Fresh and already-stamped PostgreSQL regressions pass. |
| A6: reset timestamps | Fixed; focused tests pass | Normalize legacy UTC timestamps; missing/expired tokens rejected and successful resets invalidate the token. |
| A7: blocking download admission | Fixed; focused tests pass | Dedicated bounded lease pool; threaded admission, ORM and filesystem preparation; cancellation-safe ownership. Saturated request-pool timer, late-acquisition cancellation, real ZIP/range/resume and concurrent ROM/SSE/health regressions pass. |
| A8: theme replacement/isolation | Fixed; focused tests pass | Stage and validate all packaged themes, serialize resets, roll back failed publication, retain originals if rollback fails. 43 theme route tests and 2 recovery tests pass using temporary assets. |
| B1: email normalization | Fixed; focused tests pass | Normalize stored and signed registration addresses; legacy mixed-case confirmation links resolve. |
| B2: invite transaction | Fixed; focused tests pass | Lock the invitation row and commit redemption with the new user. Concurrent redemption creates exactly one account with SMTP disabled. |
| B3: recovery/delivery feedback | Fixed; focused tests pass | Silent public recovery responses; rate-limited activation resend and repaired confirmation links; registration/invites report failed delivery accurately. |
| B4: Library state | Fixed; focused tests pass | Canonical URL/cookie filters, explicit persistent clear, consistent zero-rating semantics, AJAX count/chips/history updates and named Library chips. |
| B5: malformed cookie | Fixed; focused tests pass | Require an object, allowlisted scalar keys and bounded values; discard malformed and zero-rating filters. |
| B6: folder boundary | Fixed; focused tests pass | Canonical paths plus common-path containment reject sibling, parent, absolute and symlink escapes. Tests use actual temporary directories. |
| B7: indexed candidate search | Fixed; focused tests pass | Bounded full-text/substring candidates plus GiST nearest title/word candidates. 10,002 games: selective SQL 9.9 ms, common SQL 16.0 ms; index use verified. |
| B8: unbounded legacy search | Fixed; focused tests pass | Autocomplete selects only id/UUID/name, escapes wildcards, orders deterministically and caps at 20. |
| B9: startup failure | Fixed; focused tests pass | Strict shell error handling; stub initializer exit 17 prevents Uvicorn launch. |
| C1: page semantics | Fixed; focused tests pass | Added metadata-edit H1 and metadata/image/cache page titles; desktop/mobile route visuals checked. |

## Verification so far

The initial 71 focused tests passed across audit security, filesystem browser, game API,
authentication utilities and observability. Ruff passed before the final
verification run. Tests use the explicitly disposable PostgreSQL database
`sharewarezfixestest` in container `sharewarez-fixes-test` on port 55439.

## Improvement work covered by the follow-up

- Shared safe Library card/menu rendering reduces duplicated markup.
- Independent filter options load concurrently; notification counts use one aggregate.
- PostgreSQL, browser and concurrency regressions cover the reproduced findings.
- Visual/accessibility checks are recorded below; final isolated-module verification follows.
- Revised search/Library measurements and real disposable archive, interruption,
  disk-pressure and concurrent-stream checks are recorded with production/WAN limits.
Subsequent isolated checks passed for model behavior (32), API tokens (4), SSE
(15), download ranges (18), HTTP security (3), SMTP diagnostics (31), SMTP sending
(28), the expanded audit security module (10), container layout (2), quality-gate
contracts (1), theme routes (43), and theme rollback recovery (2). Older tests
that expected unconditional active state or SMTP protocol debugging were updated
to assert the corrected security contract.

Account remediation: 7 PostgreSQL regressions, 28 SMTP tests and 12 email-template tests pass. Activation resend visually checked on the running app at desktop and 390 × 844: no horizontal overflow, 44 px mobile controls. Full-suite verification remains pending.

Search checks: 7 global-search, 28 game API, 2 search/bootstrap/performance and 1 live bootstrap tests pass. Corrected a missing newline in the earlier game API administrator fixture, exposed by isolated module execution. Query plans are saved in `docs/audits/2026-09-05/search-remediation.json`.

Library verification: 29 Library route, 9 audit, 6 experience, 2 hover, 4 accessibility
contract and 3 notification tests pass. Desktop/mobile Library screenshots, AJAX
pagination, applying/removing a named filter, action-menu opening and Escape focus
return verified on port 5006. Menus are rendered on demand (one per Library), seven
filter requests run concurrently, and unread notification badges use one aggregate.
20-game HTML: 130,715 bytes / 17.6 ms warm; 100 games: 492,981 bytes / 22.9 ms.


## Final remediation follow-up — 6 September 2026

All 18 identified findings are fixed and the full quality gate passed.

Download preparation and admission run outside the ASGI event loop. Admission
and archive leases use a separate pool capped at 32 connections per process,
with no overflow, 100 ms checkout timeout, 3 second connection timeout and
2 second SQL timeout. These connections are additional to the normal request
pool: size PostgreSQL connection capacity for the number of web workers and
background workers. A cached transfer normally holds two leases; a direct file
holds one. Saturation rejects admission rather than blocking the event loop. A cached-archive
lease checkout timeout returns a retryable 503 and releases the transfer slot.
Cancellation reclaims late acquisitions, disconnected waiters remove their queue
entries, and failed unlocks invalidate the physical connection. Queue expiry is
the recovery fallback if cleanup cannot reach PostgreSQL.

Local measurements: a 10 ms timer under request-pool pressure fired after
14.7 ms (original audit: 300.4 ms); SSE snapshot plus health completed in 15.8 ms
while two streams were active. Evidence: `docs/audits/2026-09-05/download-remediation.json`.

Four PostgreSQL admission/integration regressions cover a saturated request
pool, cancellation, an actual 4 MiB ZIP with byte ranges and resume, and two
simultaneous real file streams alongside SSE and health requests. Seven archive
cache tests include ENOSPC during writing: no partial or completed ZIP remains,
the archive is failed, and source bytes remain intact. Seven JavaScript live
update/reconnection tests pass.

The metadata editor now uses flat field groups within one shared surface and
one primary Save action. Switching Library cards restores the previous card's
controls and cancels stale menu requests. Changing Library layout immediately
updates the URL used by saved views.

Visual verification succeeded on the running app for Library, activation resend,
metadata editing, image editing and Download Cache at desktop and 390 × 844.
Mobile ordinary editor actions measure 44 px; checked pages have no horizontal
overflow. Library pagination, filter addition/removal, menu focus/Escape and
specific page titles were checked. A disposable Ember-theme Library passed
desktop/mobile review and initial/AJAX hostile-title/genre checks with zero
injected attributes or event handlers. Test data was isolated from the real library.

Search migration 25 was applied to the development database after a verified
PostgreSQL dump, retained at
`/home/douw/sharewarez-audit-backups/20260906/gamelibrary-20260906T052554214040Z-audit-search-index-upgrade.dump`
with its manifest. The development server remains on port 5006.

Measurements are local synthetic SQL/request timings and integration checks.
They do not establish production throughput, WAN download speed, field
LCP/INP/CLS, every theme's contrast, or an exhaustive absence of future bugs. The browser automation environment
does not expose `performance.getEntriesByType`; no browser-vitals values are claimed.
The separate application-plus-database production topology is retained.

A final quality-gate retry exposed a PostgreSQL container readiness race:
`pg_isready` could accept the temporary initdb socket server before its restart.
The gate now waits for the final TCP listener, with a 60 second startup window.


## Completed final quality gate

- **1,835 Python tests passed across all 120 modules**, each against a freshly
  recreated disposable PostgreSQL 17.6 database; **zero skipped**.
- **7 JavaScript live-update tests passed** using Windows Node. Changed Library
  scripts passed syntax checks; menu replacement and layout URL state were
  verified in the browser, then the original Grid layout was restored.
- Locked dependencies match; `pip check` passed and `pip-audit` found no known
  vulnerabilities. Ruff, focused Mypy (4 modules), accessibility (88 templates),
  compilation, fresh schema/bootstrap/migrations, version and Compose checks passed.
- The release-equivalent `sharewarez:audit-fixes-check` container built successfully;
  packaged application/migration code compiled successfully.
- After the final archive-capacity response refinement, all 4 admission/integration
  tests and 18 range tests were rerun and passed. Final lint and whitespace checks passed.
- Development health endpoint returned 200. No release was pushed or deployed.

Machine-readable final evidence: `docs/audits/2026-09-05/final-verification.json`.
The original audit report remains the baseline; this ledger supersedes its open
finding statuses. All identified fixes and the additional measured improvements
are committed. Browser-vitals and production/WAN validation limits remain as
explicitly described above.
