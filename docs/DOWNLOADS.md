# Download delivery

The Download button on a game detail page creates or refreshes the user's
reusable download request. A single file is served immediately. A multi-file
directory is prepared once as an immutable ZIP in GameLibrary's private managed
cache, then delivered through the same ASGI file path. The user's **Downloads**
page shows preparation progress, readiness, failures, and retry controls.

Direct file downloads support HTTP single-byte range requests. Clients can
resume an interrupted transfer by sending `Range: bytes=<offset>-`; successful
partial responses return `206 Partial Content`, `Accept-Ranges: bytes`, an
exact `Content-Range`, and the partial `Content-Length`. Invalid,
unsatisfiable, and multi-range requests return `416` with
`Content-Range: bytes */<file-size>`.

Ready managed archives support the same single-byte range behavior, plus stable
`ETag` and `Last-Modified` validators for `If-Range`. Browsers and download
managers can therefore resume by requesting only the missing bytes. Users do
not select a server-side percentage; they resume from their browser's Downloads
panel or a download manager, which knows the verified local offset.

The default `prefer` policy retains on-demand ZIP streaming as an explicit
fallback. Those live ZIP streams do not advertise byte ranges and must restart
after interruption because each request generates a new byte stream. Operators
can disable caching or require resumable preparation from **Administration →
Download cache**. That page also controls capacity, minimum free space,
retention, build concurrency, fallback availability, build cancellation,
pinning, retries, and eviction. Cache builds use ZIP `STORED` (no compression)
and calculate integrity metadata while writing, so finalization does not reread
the full archive. See [`DOWNLOAD_ARCHIVE_CACHE_SPEC.md`](DOWNLOAD_ARCHIVE_CACHE_SPEC.md)
for the full lifecycle and safety contract.

Administrators can configure a per-user concurrent-transfer cap and a
per-transfer bandwidth ceiling in **Server Settings → Download delivery**.
Both direct files and generated ZIP streams pass through the same admission
control. When all of a user's slots are occupied, the server returns `429`
with `Retry-After: 5`; the slot is released when the response completes or the
client disconnects. PostgreSQL advisory locks make the cap effective across
all Uvicorn workers. A bandwidth value of `0` is unlimited; positive values
are interpreted as decimal megabits per second and preserve HTTP range
semantics.

When a user has filled their concurrent-transfer slots, new requests enter a
short PostgreSQL-backed admission queue instead of failing immediately. The
queue is shared by every web worker and orders requests by administrator-set
priority, then by arrival time. Administrators can choose low, normal, or high
priority for each request from **Administration → Downloads**. The maximum wait
is configured in **Server Settings → Downloads**; after it expires the client
receives `429` with `Retry-After: 2`. Expired or abandoned queue rows are
removed automatically.

Download links expire after the administrator-configured lifetime in **Server
Settings → Downloads** (seven days by default). A value of `0` disables
expiration. Expired requests return `410 Gone`; users can retry an expired row
to validate the source and create a fresh expiry window. Existing requests are
assigned the default seven-day window during migration.

Every active transfer persists its streamed-byte count and activity heartbeat
approximately once per second. **Administration → Downloads** polls these rows
with one non-overlapping request every two seconds to show the active user,
filename, readable elapsed time, bytes sent, and progress. The elapsed clock
advances in the browser between responses, so it remains smooth without adding
database writes. Polling pauses while the page is hidden and resumes as soon as
the administrator returns.
The member Downloads page follows the same non-overlapping pattern: active
transfers refresh every two seconds, idle transfer checks slow to ten seconds,
and polling pauses while the tab is hidden. The Download Cache summary refreshes
every three seconds during builds and every thirty seconds while idle.
Transfers without a heartbeat for 60 seconds are marked interrupted and their
unused quota reservation is released. This monitoring state is shared by all
web workers. An administrator can cancel an active transfer; the stream notices
that state on its next heartbeat and closes the response. The same page also
paginates completed, interrupted, and cancelled transfer attempts separately
from download links:

- A **download link** (`DownloadRequest`) is the reusable access record shown on
  the member's Downloads page. It owns the source, expiry, and admission-queue
  priority. Priority matters only while a delivery is waiting for a free slot.
- A **transfer attempt** (`DownloadTransfer`) is one HTTP response started from
  that link. It owns the live heartbeat, streamed bytes, start/end times, and
  final status. **Hide finished attempts** hides only finished rows matching the
  active Activity filters, across all pages. The reviewed count and filters must
  match the POST. Rows remain in PostgreSQL for quota, statistics and member
  recovery evidence; active attempts are excluded. This is not a retention purge.

Each transfer stores its own game identifier so history remains attributable
after its reusable link is deleted. Older records whose links were already
deleted before that field existed remain labelled as legacy records.

The streamed-byte counter records bytes accepted by the application's ASGI
connection. It is suitable for quota accounting and interruption diagnostics,
but it is not proof that the browser wrote every byte to disk. A buffering
reverse proxy can accept data faster than the public internet link, so elapsed
time and streamed bytes must not be presented as the member's WAN speed.
Download responses send `X-Accel-Buffering: no`; nginx-compatible proxies should
honour it, and other reverse proxies should have response buffering disabled for
the download routes.
Statistics count only completed transfer attempts; creating or refreshing a
download link is not counted as a download.

Live monitoring reports **current** server-send speed over roughly eight seconds
and **average** speed since the current HTTP attempt started. A resumed range is a
new attempt: its average does not include bytes downloaded previously. Current
speed is unknown while samples warm up; after eight seconds without activity it
becomes zero. ETA is omitted when size or rate is unknown or the transfer has
stalled. These measurements retain the server-send/proxy limitations above.

Stale attempts are closed by a maintenance thread in the existing job process,
not by opening or refreshing an admin page. It runs every 15 seconds using the
existing 60-second inactivity cutoff. The same thread expires elapsed links.
For local testing, run `python -m sharewarez.job_worker` alongside `./startweb.sh`;
the production app container already supervises both processes. Do not run a
second job process against the same database: startup recovery assumes one owner.

Monthly quotas use calendar months and measure bytes streamed by the application, including
resumed ranges. Administrators set an instance default in **Server Settings →
Downloads** and may give an individual user an inherited, unlimited, or custom
GB allowance from **Administration → Users**. Before a response starts, the
server reserves the expected transfer size atomically; interrupted transfers
release unused capacity and retain only their delivered-byte usage. Generated
ZIP reservations use the total size of their source files.

When changing download delivery, preserve the path and ownership checks in
`asgi.py` and run `tests/test_download_ranges.py` plus the download route tests.


## Download admission connection capacity

PostgreSQL transfer-slot and archive leases use a separate bounded pool of up to
32 connections per web process (no overflow), in addition to the ordinary ORM
pool. Direct-file transfers hold one lease; cached archives normally hold two.
Account for worker count and background jobs when setting database connection
capacity. Lease checkout waits at most 100 ms; connection establishment and SQL
have 3 second and 2 second limits respectively. Admission and preparation run in
worker threads so waiting cannot block SSE or other ASGI requests. Disconnected
queue entries and late acquisitions are reclaimed; expired queue rows provide
recovery if database cleanup is unavailable.

### Package selection and initiation

Game, update and extra download creation uses POST with CSRF. Bookmarked
initiation GET/HEAD URLs show a confirmation without changing download records.
Concurrent creation by a member locks that member before looking up a reusable
link. Reuse requires the same game, content type, record identity when known and
source path. Legacy duplicate URLs and attempt relationships remain intact;
duplicate IDs are logged for later review rather than merged.

Cached and live ZIPs share utils/download_sources.py inclusion rules. Ordinary
release notes are included; local metadata files, symlink entries and configured
or default updates/extras subdirectories are excluded. Enumeration errors stop
preparation. The main-game direct-file shortcut applies only to a single
significant root file with notes/metadata and no eligible nested files. A launcher
with nested assets therefore produces a complete archive. Updates and extras
are validated and packaged relative to their own source. A missing source is
reported before creating a link or incrementing the request counter.### Transfer evidence

Each new HTTP attempt records its delivery kind, original fixed response length
(or unknown for live ZIP), correlation ID and last byte-progress time. The first
terminal decision retains its reason and explicit administrator actor; later
stream finalization may reconcile additional bytes without changing that decision.
Historical attempts without evidence show **Reason unavailable**.

Reasons distinguish completed delivery, observed peer disconnect, downstream
connection write failure, source read failure, archive generation failure,
progress persistence failure, stale owner heartbeat, administrator stop, inactivity
timeout and unknown interruption. A reason records the observed boundary; it does
not establish a proxy or browser root cause. Reasons are fixed public labels and
never include raw exception text, source paths or credentials. Download ingress
validates or generates X-Request-ID and logs rejections with that ID and a route
pattern; rejected admission does not create a quota-bearing attempt.### Streaming liveness and resource ownership

Both delivery paths renew an owner heartbeat every 10 seconds, independently of
storage reads, bandwidth pacing and downstream sends. The stale-owner threshold
remains 60 seconds. Byte progress is separate and normally saved about once per
second while bytes move; a heartbeat never invents progress. Transient heartbeat
bookkeeping failure retries, and a transfer that cannot confirm ownership before
its stale deadline stops while preserving any earlier terminal reason.

The initial read/write wait limit is five minutes. Planned bandwidth sleep is
excluded, sliced into 0.25-second waits, and remains interruptible by disconnect
or administrator stop. Timeout records stall_timeout. Bookkeeping has a separate
bounded four-thread executor so blocked readers cannot starve heartbeat or quota,
slot and lease cleanup. Descriptor close work uses a separate two-thread executor.

File headers and body use one open handle and fstat. Truncation before the
promised length is a source_read_error; it never emits a successful completion.
Cancellation closes async generators and awaits ownership/watcher tasks. If a
kernel read has not returned, its resource stays owned and closes once afterward;
the application does not close/reuse its descriptor underneath a running read.
Accounting and admission cleanup can finish while that safe reclamation waits.
An application deadline cannot force an unresponsive kernel/mount operation to
return. Validate kernel I/O recovery and the five-minute default on slow staging
storage before release, with both supported processes and the real ingress.### Member link states and actions

utils/download_state.py is the shared authority for HTML, SSE, polling and link
mutations. Active attempts show progress first and suppress conflicting controls.
Expired/cancelled links require Renew/Retry; a fallback POST cannot bypass expiry.
Renew validates source eligibility and containment before changing the link.
Unknown source locations show a reason and secondary Remove link. That removes
only the reusable link; original game files and transfer accounting remain.

New preparation and retries use the same off/prefer/require cache policy. A cache
failure in require mode remains a failed link that can be retried when storage is
healthy. Existing ready cached representations remain reusable while their source
storage is offline. Resumability comes from the actual prepared file/archive,
including the sole-file shortcut inside a game directory. Cancelling one link
does not stop an archive shared with another member. Known preparation failures
use bounded public messages, with latest HTTP attempt evidence shown separately.

Actions lock the member and reload the link, then recheck active attempts, expiry,
source and policy. Delivery admission checks that its prepared representation is
still current under the same lock. A changed link is rejected before quota is
reserved. Bookmarked Game Details initiation reuses the link and follows its
current actions; it does not implicitly renew an expired or active link.
The legacy check_download_status response retains stored status for compatibility
and includes a canonical download object. The page and current status API use
canonical state/actions, and the summary badges count the current page.
## Administrative views

`/admin/manage-downloads?view=activity` shows one row per HTTP attempt; `view=links`
shows reusable links. Activity accepts username, transfer status, link ID and
`transfer_page`; Links accepts username, stored link status, content type and
`page`. Both retain `per_page` (10–100, default 25). Username is a literal substring,
including `%` and `_`. Tabs preserve username/row count and reset pagination.
View attempts carries the link ID. Back restores the full prior URL.

Legacy links without `view` infer Activity when `transfer_status` or
`transfer_page` is present, before considering link-only `status`, `content_type`
or `page`. No filters defaults to Activity. Irrelevant filters do not cross views.

Migration `20261106_35` adds nullable `admin_history_hidden_at`; historical rows
remain visible. Apply migrations before running this version. Hiding requires a
CSRF token and an actor-bound, one-hour review token for the complete normalized
filter/page and count. Missing/tampered filters are rejected; a changed count
returns 409 and requires a new review. The legacy `/clear` URL now hides rather
than deleting attempts. Permanent retention remains a separate policy decision.
