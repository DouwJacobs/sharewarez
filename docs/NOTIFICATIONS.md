# In-app notifications

The notification center at `/notifications` is a durable per-user inbox. It
supports unread filtering, individual read actions, mark-all-read, pagination,
and safe links back to related application pages.

Initial event producers are new games, newly discovered update files, new or
joined game requests for administrators, request status changes for active
requesters, and the standalone game-issue workflow. New issues and reporter
replies notify active administrators; public administrator replies and status
changes notify the reporter. Internal issue notes never notify the reporter.
Administrators can also opt into alerts when users cancel download
requests and when the same download request starts a second or later transfer.
Repeat-download alerts are based on transfer records, not basket creation, and
are deduplicated per request and attempt. `notifications.dedupe_key` is unique per user so scan retries and
background-job retries cannot redeliver the same logical event.

Issue email delivery is controlled by `notifyAdminIssueEmail` and
`notifyReporterIssueEmail`. Email bodies are rendered before a
`notifications.send_email` database-backed background job is queued, so SMTP
latency does not block the issue form or conversation UI. The durable in-app
notification is committed before optional email delivery and remains the
authoritative record if SMTP is unavailable.

The PWA is installable and provides offline fallback caching, an app-update
prompt, and standards-based Web Push. Push subscriptions and VAPID credentials
are stored locally; no hosted notification service is required. Push delivery
is best-effort and is emitted from newly created in-app notification records.

## Game issue workflow

Game issues are separate from game requests and live at `/issues` for reporters
and `/admin/issues` for administrators. The admin queue paginates by game so
multiple reports for the same title stay together. Supported states are open,
in progress, waiting on user, resolved, and closed. Public comments form the
shared conversation; internal notes are admin-only. Every status transition is
stored as a timeline event. Reporters can edit active reports, reply, close, and
reopen their own issues. Administrators can edit metadata, reply, add internal
notes, change state, and permanently delete an issue with its comment history.
