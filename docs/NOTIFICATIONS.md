# In-app notifications

The notification center at `/notifications` is a durable per-user inbox. It
supports unread filtering, individual read actions, mark-all-read, pagination,
and safe links back to related application pages.

Canonical event producers are new games, newly discovered update files, new or
joined game requests for administrators, request status changes for active
requesters, and the standalone game-issue workflow. New issues and reporter
replies notify active administrators; public administrator replies and status
changes notify the reporter. Internal issue notes never notify the reporter.
Administrators can also opt into alerts when users cancel download
requests and when the same download request starts a second or later transfer.
Repeat-download alerts are based on transfer records, not basket creation, and
are deduplicated per request and attempt. Each logical event is stored once in
`notification_events`; inbox rows retain a per-user dedupe constraint.

`publish_event()` is the only fan-out boundary. It stages the canonical event,
inbox rows, rendered email jobs, browser-push jobs, Discord jobs, and subscribed
generic webhook deliveries in one transaction. Callers that pass `commit=False`
can include that staging in their surrounding source transaction. Network work
is owned by the existing background worker.

Administrators configure event/channel availability in **Application Settings →
Notification rules**. Members choose per-event inbox, email, and browser delivery
in **Settings**. Administrator policy is authoritative; a disabled channel cannot
be enabled by an account. Existing category and global settings are migrated to
explicit values without enabling a new delivery path.

The PWA is installable and provides offline fallback caching, an app-update
prompt, and standards-based Web Push. Push subscriptions and VAPID credentials
are stored locally; no hosted notification service is required. Push delivery is
best-effort and independent of whether the inbox channel is enabled. Generic
webhooks are documented in [OUTBOUND_WEBHOOKS.md](OUTBOUND_WEBHOOKS.md).

## Game issue workflow

Game issues are separate from game requests and live at `/issues` for reporters
and `/admin/issues` for administrators. The admin queue paginates by game so
multiple reports for the same title stay together. Supported states are open,
in progress, waiting on user, resolved, and closed. Public comments form the
shared conversation; internal notes are admin-only. Every status transition is
stored as a timeline event. Reporters can edit active reports, reply, close, and
reopen their own issues. Administrators can edit metadata, reply, add internal
notes, change state, and permanently delete an issue with its comment history.
