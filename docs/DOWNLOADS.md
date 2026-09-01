# Download delivery

The Download button on a game detail page creates or refreshes the user's
reusable download request and immediately redirects to the ASGI delivery URL.
There is no background ZIP preparation step: a single file is served directly,
while a multi-file game is converted to a ZIP as it streams. The user's
**Downloads** page remains the history/retry surface and can start the same
delivery again.

Direct file downloads support HTTP single-byte range requests. Clients can
resume an interrupted transfer by sending `Range: bytes=<offset>-`; successful
partial responses return `206 Partial Content`, `Accept-Ranges: bytes`, an
exact `Content-Range`, and the partial `Content-Length`. Invalid,
unsatisfiable, and multi-range requests return `416` with
`Content-Range: bytes */<file-size>`.

On-demand ZIP streams do not advertise byte-range support. Their output is
generated during each request and therefore has no stable random-access byte
offset. A game represented by one stable file is delivered directly and is
resumable; a multi-file directory is delivered as an on-demand ZIP and must be
restarted if interrupted.

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
to show the active user, filename, elapsed time, bytes sent, and progress.
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
