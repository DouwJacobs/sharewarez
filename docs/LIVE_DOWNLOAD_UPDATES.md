# Live download updates

The member Downloads page, administrator transfer monitor and cache inventory use
authenticated Server-Sent Events at `/api/live/downloads`. The ordinary Flask/Jinja
pages and CSRF-protected actions remain authoritative. There is no Redis, WebSocket
server or additional service container.

## Deployment and recovery

- Apply migration `20260904_24` through the normal startup migration workflow.
  It signals committed changes to download requests, transfers, archives and
  archive-build jobs. Rollbacks and unrelated jobs do not notify.
  Fresh metadata-created databases install the same non-model trigger objects
  through `bootstrap_schema_extras()` before being stamped at the current head.
- Budget one additional PostgreSQL connection per web process for LISTEN.
  Notifications are topic-only hints; snapshots are read from PostgreSQL.
- Disable proxy response buffering/caching for `/api/live/downloads`, and allow
  idle connections for longer than the 16-second heartbeat interval (60 seconds
  is a reasonable minimum). The endpoint sends `X-Accel-Buffering: no` and
  `Cache-Control: no-store`. Do not enable wildcard credentialed CORS.
  Forwarded host/protocol values are trusted only according to the existing
  `TRUST_PROXY_COUNT` setting, matching Flask's proxy policy. The default remains
  zero; do not increase it unless all traffic passes through those trusted hops.
- The browser falls back to polling if the initial SSE snapshot fails to arrive
  within five seconds, the stream fails, or no snapshot arrives for 25 seconds.
  It attempts SSE again after 30 seconds. Hidden tabs stop network work and return
  with a fresh snapshot; browser back/forward restoration reconnects too.
- Every snapshot verifies the signed session and current account state/role.
  Member streams always filter by owner, including when an admin visits Downloads.
  Activity and cache streams require admin permission. Revocation closes a stream.
- Default limits are 100 admitted streams and four per user **per web process**,
  with at most 16 concurrent initializations. Multiply per-process limits by the
  configured web-worker count. Slow sends time out after ten seconds.
- The supplied web launchers give Uvicorn 30 seconds for graceful shutdown, then
  cancel remaining streams/download responses. Interrupted downloads retain the
  existing resumable range behavior. Uvicorn owns signals; ASGI lifecycle cleanup
  closes the LISTEN connection instead of replacing server signal handlers.
- The existing single job process retires stale transfers and expires links every
  15 seconds independently of long-running scans/builds. Run it alongside the web
  server for local testing. Do not start a second job process against the same DB.

## Bounded work and freshness

Signals coalesce into three topic flags, one scheduled event-loop callback and
one dirty bit per subscriber. Snapshots are limited to once per second and also
sent periodically as heartbeats/resynchronization. No client-side offset is used
to infer download resume positions.

Identical data queries are shared for up to 0.8 seconds within one web process,
with 32 LRU entries. Authorization is never cached: it runs before every access.
Member data keys include the owner ID and visible request IDs; admin datasets are
shared only after verifying the admin role. Background-thread cache misses are
serialized to avoid a query burst. No database session remains open while sending
an SSE response or waiting for the next signal.

Transfer snapshots cap at 1,000 active attempts and flag truncation; the paginated
admin transfer-history table remains available for the complete records. Cache
and member subscriptions accept at most 100 visible row IDs. Inventory rows stay
in place, with an explicit refresh hint when the inventory count changes, rather
than silently reordering a page with unsaved controls.

Current speed uses roughly eight seconds of server-send samples; average speed
belongs to the current HTTP attempt, including a new resumed attempt. ETA is
omitted when total size or current speed is unknown/stalled. These are **not**
browser disk-write confirmation or guaranteed WAN throughput measurements.

## Representative local measurements (2026-09-04)

`tests/test_live_performance.py` measured a fresh disposable PostgreSQL database
with 10 distinct administrator viewers, 100 active transfers and 2,000 archives.
Python's `tracemalloc` measured peak temporary Python allocations. These are single
local sample rounds, not production capacity estimates or network benchmarks.

| Sample | Queries | Elapsed | Peak Python allocation |
| --- | ---: | ---: | ---: |
| Ten unshared activity snapshots | 20 | 135.87 ms | 1,412.5 KiB |
| Ten shared activity snapshots | 11 | 38.83 ms | 305.4 KiB |
| Previous inventory pattern: load rows, sum in Python | 1 | 43.91 ms | 4,706.2 KiB |
| SQL-aggregated inventory, including policy/health work | 3 | 15.12 ms | 207.2 KiB |

The activity comparison isolates snapshot sharing, not the entire old HTTP
polling stack. It uses a 60-second cache TTL solely to keep one measured sample
round stable on slower test machines; production uses 0.8 seconds. The inventory
baseline is the previous row-loading/summing pattern; its minimal version excludes
policy/health work, so the aggregate comparison includes more work, not less.

Healthy SSE replaces repeating monitor HTTP requests with one open connection and
approximately one-second changes. Idle snapshots happen about every 16 seconds
instead of the old admin monitor's two-second polls. Active refresh frequency is
higher, so a single busy viewer can perform more database work than before; shared
queries reduce duplication with multiple viewers. Measure under your own archive
and transfer workload before increasing worker/connection limits.

## Verification status

Focused tests cover database notification commit/rollback, multiple listeners,
listener reconnect, bounded bursts, authentication and ownership, slow clients,
session revocation, snapshot sharing, lifecycle cleanup and fallback behavior.
Synthetic authenticated desktop/mobile previews have verified the three screens.
`tests/test_live_workers.py` additionally starts two independent Uvicorn processes,
opens authenticated HTTP streams, commits a progress update and observes it in
both processes. It verifies ordinary HTTP requests remain responsive, terminates
one worker, and checks a replacement worker's initial snapshot against current
database state. Fresh-install notification DDL has its own bootstrap test.
The complete local quality gate passed on 2026-09-04 using Python 3.12, including
all isolated PostgreSQL test modules, the migration and Compose checks, and the
release-equivalent `gamelibrary:quality-gate` container build. The separate
browser-client transport suite also passed. This is implementation verification,
not production deployment approval; perform the staging checks listed below.

### Acceptance evidence map

| Requirement | Implementation | Verification |
| --- | --- | --- |
| Owner-only member data, admin views, account revocation | `live_snapshots.py`, `live_sse.py` | `test_live_sse.py`: boundary, owner/admin, revocation and uncached authorization tests |
| Nonblocking connections, bounded work, slow-client cleanup | `live_sse.py`, `live_events.py` | SSE timeout/disconnect tests, event burst/limit tests, independent-process HTTP test |
| Cross-process changes and restart recovery | PostgreSQL revision `20260904_24`, LISTEN thread | `test_live_events.py` commit/rollback and reconnect tests; `test_live_workers.py` two live web processes and replacement |
| Fresh-install and upgrade support | `bootstrap_schema_extras`, initialization manager | `test_live_bootstrap.py`, migration up/down/up test, quality-gate fresh schema initialization |
| Current/average rate, readable time, conditional ETA | `transfer_rates.py`, shared transfer payload, frontend formatters | `test_transfer_rates.py`, `download_live.test.cjs`, admin rendered preview |
| Worker-owned cleanup without monitor writes | `job_worker.py` maintenance thread | `test_download_maintenance.py`, download route regressions |
| Stable rows, form/focus preservation, live ready/actions | Three download screen clients and shared SSE client | Desktop/mobile previews recorded in `UI_AUDIT.md`; member form/no-reload test and snapshot route tests |
| Reconnect, hidden tabs and polling fallback | `download_live.js` | `download_live.test.cjs` fake transport/timer tests |
| Resume, limits, cancellation and cache safety preserved | Existing delivery/cache implementation | `test_download_ranges.py`, `test_download_limits.py`, `test_download_cache.py` and delivery route tests |
| Representative performance comparison | Shared snapshot cache and SQL summary | `test_live_performance.py`; measurements and limitations above |

Run the Python suite through `scripts/quality-gate.sh` with the documented project
Python environment. Run the supplementary browser-client tests with
`node tests/download_live.test.cjs`; they do not require a running browser or DB.
The browser previews use synthetic transfer metadata, not a 50 GB download.
Real WAN interruptions, the production reverse proxy and custom/light themes
still require staging checks before deployment. No image publication or remote
source push is part of this implementation verification.
