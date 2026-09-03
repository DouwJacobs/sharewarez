# Download delivery

The Download button on a game detail page creates or refreshes the user's
reusable download request. A single file is served immediately. A multi-file
directory is prepared once as an immutable ZIP in Sharewarez's private managed
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
  final status. Administrators can clear finished attempt history without
  deleting members' reusable links.

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

Monthly quotas use calendar months and measure bytes streamed by the application, including
resumed ranges. Administrators set an instance default in **Server Settings →
Downloads** and may give an individual user an inherited, unlimited, or custom
GB allowance from **Administration → Users**. Before a response starts, the
server reserves the expected transfer size atomically; interrupted transfers
release unused capacity and retain only their delivered-byte usage. Generated
ZIP reservations use the total size of their source files.

When changing download delivery, preserve the path and ownership checks in
`asgi.py` and run `tests/test_download_ranges.py` plus the download route tests.
