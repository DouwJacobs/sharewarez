# In-app notifications

The notification center at `/notifications` is a durable per-user inbox. It
supports unread filtering, individual read actions, mark-all-read, pagination,
and safe links back to related application pages.

Initial event producers are new games, newly discovered update files, new or
joined game requests for administrators, and request status changes for active
requesters. `notifications.dedupe_key` is unique per user so scan retries and
background-job retries cannot redeliver the same logical event.

The PWA is installable and provides offline fallback caching and an app-update
prompt. Web push is not implemented yet: there are no push subscriptions, VAPID
keys, or service-worker push handlers. The in-app event records are intended to
be the source for future per-channel delivery preferences and web push.
