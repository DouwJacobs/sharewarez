# Sharewarez application audit — 5 September 2026

Audited checkout: `/home/douw/sharewarez`, `main`, commit `dc73a12`, version **1.13.0**. The branch was clean and 22 commits ahead of its remote at the start. This is a findings report; application fixes were not implemented.

Remediation status and subsequent verification: [audit fixes](AUDIT_REMEDIATION_2026-09-05.md).
The findings below preserve the original audit evidence.

## Assessment

The application has substantial automated coverage and generally consistent responsive structure. Nevertheless, targeted PostgreSQL and browser probes exposed authorization, account recovery, HTML escaping, fresh-install, and download concurrency defects that the existing suite misses. Fix the P1 items before treating the current release as fully hardened.

**18 findings:** eight P1, nine P2, and one P3. P1 means high impact or a core workflow failure under the stated trigger; it does not mean every installation is currently experiencing the defect. Findings distinguish reproduced behavior from source-only observations.

## Verification and boundaries

- **1,800 Python tests passed across all 114 test modules**, each run separately against a freshly recreated disposable PostgreSQL 17.6 database, following the repository's module-isolation convention.
- **7 JavaScript live-download tests passed.** Executed with Windows Node because Node was unavailable in WSL.
- Ruff passed; focused Mypy passed for the four quality-gate modules; the accessibility scanner passed for all **85 templates**; dependency audit reported **no known vulnerabilities** in `requirements.txt` at audit time.
- A separate fixture received **41 representative GET requests** covering user pages, administrative workspaces, compatibility redirects, and global search. All returned expected 200/302/308 statuses after explicitly installing the missing search extension in that fixture. This route smoke pass did not submit application administration forms.
- Browser checks used another disposable database and the real ASGI application on port 5008. Checked approximately **41 distinct rendered mobile pages**, including Library, game details, metadata/image editors, account screens and administrative workspaces, plus **15 core desktop pages**. Widths were 390 × 844 and 1440 × 1000. Measured pages did not exceed the viewport's document width. One requested Server Status page redirected because its feature was disabled in the fixture; its actual layout was not verified.
- Browser interactions reproduced filter persistence, stale result counts, and title-based attribute injection. Browser screenshot capture repeatedly timed out, including through both available screenshot interfaces. **This is not a completed visual screenshot/contrast audit.** Geometry and accessibility-tree results do not certify visual quality, focus appearance, nested surface styling, or contrast. Other themes were not visually checked. The temporary viewport was reset.
- Performance measurements use **10,030 synthetic games**, local PostgreSQL and Flask's test client. They measure request processing and uncompressed response bodies, not browser LCP, WAN throughput, production concurrency or real archive-build speed. Test and preview processes were sharing the local machine.
- No real library database was modified, no email was sent, no release was built or published, and no real downloads were started. PostgreSQL lived in the explicitly created `sharewarez-audit-20260905` container. The dependency lock regeneration, release container build and full production gate were not run.
- A test unexpectedly deleted the installed default theme (finding A8). It was restored from `sharewarez/setup/default_theme`; recursive comparison then confirmed source and installed copies matched. Other installed themes were retained.

Evidence: [route and account probes](audits/2026-09-05/probes.json), [authorization and performance probes](audits/2026-09-05/probes2.json), [concurrency and logging probes](audits/2026-09-05/probes3.json), [test summary](audits/2026-09-05/test-summary.json). All evidence uses synthetic records.

## P1 — fix first

### A1. Ordinary users can move games between libraries

**Reproduced.** `POST /api/move_game_to_library` has `login_required` but no administrator guard. A regular active user posted a game UUID and target library UUID; the endpoint returned 200 and the database assignment changed.

Source: `sharewarez/routes_apis/game.py:61–94`.

Impact: a member can modify the shared catalogue and change the library/platform association for everyone. Hiding an action in the frontend cannot enforce authorization.

Fix: require administrator permission on the endpoint and add a negative role test that also verifies the database remains unchanged. Audit mutation endpoints through a common role/action matrix.

### A2. Disabling a user does not revoke existing Flask sessions

**Reproduced.** After setting an already signed-in member's `state=False`, the same session still received `/library` with status 200. `load_user()` returns disabled users and both `User.is_authenticated` and `User.is_active` unconditionally return true. Only the login form checks account state. The SSE authenticator already rejects disabled users, so authorization differs between transports.

Sources: `sharewarez/utils/auth.py:10–11`; `sharewarez/models.py:390–395`; compare `sharewarez/live_snapshots.py:68–89`. Direct ASGI cookie decoding at `asgi.py:382–430` also returns an ID without checking current user state.

Fix: enforce enabled-account state whenever resolving a session; use the same active-user boundary for Flask, SSE and direct downloads. Test disabling an account after login and attempting subsequent reads and mutations. Consider a session version for password-change/session revocation.

### A3. AJAX game cards permit stored HTML attribute/event-handler injection

**Reproduced in the browser without executing a malicious payload.** `createGameCardHtml()` uses jQuery `.text(...).html()` as `safeName`, then interpolates it into double-quoted attributes. This escapes HTML text delimiters but leaves quotes suitable for breaking out of an attribute. Genre/tag strings are also interpolated without contextual escaping.

A synthetic title containing `" data-audit-injected="yes" onpointerenter="void 0" data-tail="` produced five actual DOM elements with the injected marker and no-op event-handler attributes after the library's AJAX refresh. Accessible button names were truncated as well. This establishes the injection primitive; no exfiltration or harmful script was used.

Source: `sharewarez/setup/default_theme/js/library_pagination.js:482–572`, especially 483, 497, 521, and 556–568. The installed default copy contains the same code. The default CSP permits inline scripts.

Impact: imported or edited metadata containing crafted values can cross into executable page markup. Exploitability requires control over a value reaching the catalogue; this is not a claim that every regular member can edit titles.

Fix: build cards using DOM nodes and `textContent`/attribute setters, or use consistent context-aware escaping for every interpolated field. Add browser regressions for quotes, tags, ampersands and hostile genre/image strings in both initial and AJAX rendering.

### A4. Passwords and authentication material reach logs

**Password logging reproduced.** An invalid `/setup/submit` form containing a synthetic password marker caused that literal password to appear in captured stdout because the failure branch prints `form.data`.

Sources: `sharewarez/routes_setup.py:59–61`; `sharewarez/utils/smtp.py:154–166`; `sharewarez/utils/smtp_test.py:122`; `sharewarez/routes_login.py:88,219`; `sharewarez/observability.py:78–87`.

SMTP protocol debug is also enabled before login/send, which can expose encoded AUTH material and full message contents, including account links. That part is established by the sender source, not by sending an actual message. Access logging records literal paths, so `/reset_password/<token>` and `/confirm/<token>` include their bearer-like token in the log path despite query-string redaction.

Fix: remove form dumps and SMTP debug logging; log route templates or redact secret-bearing path segments. Test that synthetic password/token markers do not appear in stdout, stderr or structured logs. Review historical logs as a separate operational follow-up where these paths have been used.

### A5. Fresh installations do not bootstrap search dependencies

**Reproduced against fresh PostgreSQL.** After current-model `create_all()` and `bootstrap_schema_extras()`, only `plpgsql` was installed and there were no search-document/trigram indexes. `/api/global-search?q=audit` raised PostgreSQL `UndefinedFunction` for `similarity(...)`.

Sources: `sharewarez/utils/migrations.py:34–50`; `sharewarez/init_manager.py:124–132`; `migrations/versions/20260809_05_search_indexes.py`; `scripts/quality-gate.sh` manually creates `pg_trgm` before tests.

The startup path stamps the fresh schema at head, while the bootstrap registry installs only download-notification DDL. The search extension and indexes exist only in the historical search migration. The test gate's explicit extension creation masks the missing fresh-install dependency.

Fix: register all non-model search DDL in the fresh-schema bootstrap, idempotently, without rerunning historical table/column migrations. Verify a completely empty PostgreSQL database can serve global search after normal startup, with no test preinstallation of extensions.

### A6. Valid password-reset links fail on PostgreSQL

**Reproduced.** A recently issued reset token persisted in PostgreSQL raised `TypeError: can't compare offset-naive and offset-aware datetimes` when opening its reset page.

Sources: `sharewarez/models.py:369` uses `db.DateTime` without timezone; `sharewarez/routes_login.py:260–269` compares it with `datetime.now(timezone.utc)`.

Fix: use a consistent timestamp representation and migrate/normalize existing records deliberately. Include tests that commit, remove the session, reload the user and exercise both fresh and expired tokens. In-memory timestamp objects alone miss this problem.

### A7. Download admission can block the entire ASGI event loop

**Reproduced with a constrained disposable connection pool.** Holding the only connection, then awaiting `acquire_queued_download_slot()`, delayed an independent 10 ms timer to **300.4 ms**, exactly the configured 300 ms pool timeout, and raised `TimeoutError`.

Sources: `sharewarez/utils/download_limits.py:29–96`; `asgi.py:129–151,174`; `config.py:38–43`.

The async queue/admission function performs synchronous connection checkout and SQL. Transfer slots retain database connections for the duration of transfers. The default application pool permits only four concurrent checked-out connections (2 + 2 overflow); the normal checkout timeout is much longer than the deliberately short probe. The ASGI download handler also performs synchronous ORM work directly on the loop.

Impact: under pool pressure or slow database operations, unrelated live updates and streaming in the same worker can stall. Worker count mitigates aggregate capacity but does not make each event loop nonblocking.

Fix: move blocking database work off the event loop, bound admission, and avoid using the general application pool for long-lived lock leases without capacity planning. Keep session and lock ownership consistent. Add concurrent transfer/SSE/health tests with an intentionally saturated pool.

### A8. Theme reset deletes the working theme before replacement is safe; its test affects real assets

**Observed during the full suite.** `test_reset_default_themes_copy_failure` mocks the copy to fail but does not isolate/mock the preceding real `shutil.rmtree()`. Running that module deleted `sharewarez/static/library/themes/default`, causing the preview to lose its CSS/JS. The suite still passed.

Sources: `tests/test_routes_admin_ext_themes.py:600–614`; `sharewarez/routes_admin_ext/themes.py:395–429`.

This also exposes the production failure mode: disk/full/permission/copy failure after deletion leaves no usable default theme. The audit restored the installed default from the canonical source and verified equality.

Fix: stage and validate a replacement before swapping it into place, retain rollback on failure, and point filesystem-mutating tests at temporary directories. A disposable database alone is insufficient test isolation. Add an assertion that the prior theme survives a simulated copy failure.

## P2 — functional correctness and scalability

### B1. Mixed-case email registration produces an unusable confirmation link

**Reproduced:** registering `Mixed@Example.com` created the lowercase database email, but opening its signed confirmation token returned 404. Registration signs the original form value while confirmation performs an exact lookup.

Source: `sharewarez/routes_login.py:154–165,202`.

Fix: normalize once and use the normalized address for storage, token claims and lookups. Test mixed-case email through the entire register/confirm cycle.

### B2. Invite consumption depends on an unrelated email/logging commit

**Reproduced with SMTP disabled:** registration created a user and redirected successfully, but the invitation remained `used=False`. The user is committed before the invite fields are updated; there is no explicit commit of those fields. Some email outcomes happen to commit through event logging, while early returns do not. The code also lacks an atomic claim/lock for simultaneous redemption.

Source: `sharewarez/routes_login.py:169–192`; `sharewarez/utils/smtp.py:105–122`; `sharewarez/utils/event_logging.py:68–71`.

Fix: consume the invite and create the user in one transaction, with a guarded atomic claim. Deliver mail only after that transaction. Test disabled SMTP, rejected mail and two concurrent registrations against one token.

### B3. Password-reset mail feedback leaks account existence and can misreport delivery

**Reproduced:** with SMTP disabled, a known address received two flashes: an SMTP error and the generic success response. An unknown address received only the generic response. Thus the public responses remain distinguishable despite the route's generic-response comment.

Sources: `sharewarez/routes_login.py:217–255`; `sharewarez/utils/smtp.py:105–122,219–232`.

Registration and invite flows also announce successful delivery without checking the sender's Boolean result; users can be left with an unverified account and no usable email.

Fix: suppress user-visible SMTP diagnostics in public recovery paths, retain private operational logging, propagate delivery results where appropriate, and give account activation a rate-limited resend/recovery flow. Prefer queued delivery with explicit delivery state.

### B4. Library filter state diverges between cookies, URLs, counts and AJAX results

**Reproduced in browser:** select a library, Apply filters, reload, and click the active-filter **Clear all** link. The library/rating chips remain because the link only navigates to `/library`, where the server restores the same cookie. Individual chip links have the same problem. A fixture game without a rating displayed after AJAX while the header still said **0 games**.

Sources: `sharewarez/routes_library.py:75–93,139–150,235–236`; `sharewarez/templates/games/library_browser.html:40`; `sharewarez/setup/default_theme/js/library_pagination.js:635–664` and its response-rendering code.

A saved string rating of `"0"` becomes a server-side `rating >= 0` filter, excluding null ratings; the client treats the zero slider as effectively unfiltered. Chips display the raw library UUID rather than its name.

Fix: choose a single canonical filter state, explicitly clear cookie state when removing filters, synchronize URL/history and all result summaries, and define zero-rating/null semantics consistently. Test Apply → reload → remove one → Clear all → back/forward, including unrated games.

### B5. A malformed but valid JSON cookie can make Library unusable

**Reproduced:** `libraryFilters=%5B%5D` caused `/library` to raise `AttributeError: 'list' object has no attribute 'items'`. The parser validates JSON syntax but assumes the decoded value is a dictionary; the exception is not caught.

Source: `sharewarez/routes_library.py:21–36`.

Fix: require an object, validate allowed scalar fields and discard/reset invalid cookies. Cover arrays, null, strings and nested objects. This is primarily a per-browser reliability problem, not a cross-user denial-of-service claim.

### B6. Administrator folder browsing can escape its configured root

**Reproduced using synthetic directories only:** with root `/tmp/.../allowed`, requesting `../allowed-sibling` returned status 200 and listed a marker file in that sibling. String `startswith(base_directory)` does not establish a path boundary and also does not resolve symlinks.

Source: `sharewarez/routes_apis/browse.py:24–30`.

Fix: resolve both paths and require containment using a real path-boundary comparison, with explicit symlink policy. This endpoint is administrator-only; the finding concerns its stated filesystem boundary, not unauthenticated file access.

### B7. Global search performs full scans despite installed indexes

**Measured:** with both intended game indexes installed and the table analyzed, `EXPLAIN (ANALYZE, BUFFERS)` selected a sequential scan of all 10,030 games. SQL execution was **164.3 ms**; four endpoint measurements were **179.8, 180.5, 192.0 and 175.7 ms**.

Source: `sharewarez/routes_apis/search.py:13–32`.

The OR predicate combines full-text matching, computed similarity thresholds and an `ILIKE` against the original name, so the existing lower-name trigram index does not provide an indexable predicate for every branch. Ranking is then computed across the broad candidate set.

Fix: use index-supported candidate retrieval, combine/deduplicate bounded candidate sets and rank those results. Apply a query-length bound. Validate both selective and common terms with realistic metadata and explain plans; do not assume adding an index alone fixes the plan.

### B8. Legacy search returns an unbounded full-library result

**Measured:** `/api/search?query=%25` returned **10,030 games**, **870,236 uncompressed bytes**, and took **144–187 ms** locally. The decoded `%` is treated as a SQL wildcard. The route calls `.all()` without a result limit or pagination.

Source: `sharewarez/routes_apis/game.py:10–52`.

Fix: cap autocomplete results, introduce pagination where full search is intended, and treat wildcard characters deliberately. Project only fields required for the response instead of loading complete ORM game rows. Consolidate overlapping search endpoints where compatible.

### B9. Development startup ignores initialization failure

**Source-confirmed; not executed against the real installation.** `startweb.sh` runs a Python initializer that exits nonzero on failure, but the shell lacks `set -e` or an explicit status check. It then exports `SHAREWAREZ_MIGRATIONS_COMPLETE=true` and `SHAREWAREZ_INITIALIZATION_COMPLETE=true` and starts Uvicorn regardless.

Source: `startweb.sh:1,77–94`.

Fix: explicitly abort when initialization fails and set completion flags only after success. Add a launcher test using a stub initializer returning nonzero. This finding applies to the development launcher; it is not a claim that the container supervisor has the same behavior.

## P3 — accessibility and navigation context

### C1. Editor headings and document titles still miss the shared contract

**Browser-confirmed:** game metadata editing exposes “Edit Game Entry” as an H2 with no H1 and uses the generic `Game Library` document title. Image editing and Download Cache also use the generic title. The baseline accessibility scan passes despite these omissions.

Sources: `sharewarez/templates/admin/admin_game_identify.html:23` (Edit Game Entry heading), `sharewarez/templates/base.html` title handling, image-editor and cache-page templates.

Fix: give these routes a specific title and exactly one visible H1, and extend the accessibility gate to cover page-level semantics while accounting for inherited layouts. Verify accessible names after dynamic updates as well as in Jinja source.

## Additional improvements

1. **Reduce Library markup and repeated UI.** The administrator Library response was 186,938 bytes for 20 games and 779,243 bytes for 100 games, without artwork transfers. Warm server timings remained good (about 23–37 ms), so this is primarily a network/DOM opportunity. Render shared action menus/dialogs once and reuse the same safe card renderer for initial and subsequent results. Avoid claiming these uncompressed sizes are actual compressed transfer sizes.
2. **Parallelize or consolidate filter loading.** Library populates libraries → collections → genres → themes → tags → modes → perspectives through nested callbacks. This creates a serial request dependency chain on every initialization. Return one filter-options payload or load independent lists together; cache options with a clear invalidation policy.
3. **Reduce baseline page queries.** In the 30-game smoke fixture, typical simple pages performed 8–14 SQL statements, Library 18 and the admin dashboard 22. The shared context processor runs three separate notification counts; combine them with conditional aggregates. These counts are measurements, not evidence that every page is currently slow.
4. **Strengthen test realism.** Existing tests pass while missing committed PostgreSQL timezone behavior, fresh extension bootstrap, negative role checks, browser attribute escaping, end-to-end filter state and filesystem isolation. Add cross-layer regressions around these exact failures. Keep fixtures small, but preserve real database commit/reload and real browser parsing where those are the failure mechanism.
5. **Finish a visual/accessibility and production performance pass.** Once screenshot capture works, inspect default and contrasting themes, keyboard-only dialogs, focus restoration, reduced motion, touch controls and contrast. Measure browser LCP/INP/CLS and compressed requests on a throttled connection. Exercise actual cache builds, interruption/resume, disk pressure and simultaneous download/SSE traffic in staging. None of those results can be inferred from the passing unit suite or local synthetic timings.

## Suggested implementation order

1. Close the catalogue mutation and session-state authorization gaps; remove secret logging and fix dynamic HTML construction.
2. Repair password recovery, confirmation normalization, invite transaction boundaries and recovery feedback.
3. Correct fresh-schema search bootstrap, theme replacement atomicity/test isolation and startup failure handling.
4. Make download database operations nonblocking and search candidate retrieval bounded/indexable.
5. Unify Library state/rendering, fix page semantics and complete the screenshot-based review.

Use separate coherent changes with focused regressions. No release or deployment should be inferred from this audit report.