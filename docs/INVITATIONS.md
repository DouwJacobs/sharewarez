# Invitation-led onboarding

Sharewarez provisions ordinary accounts through one-time invitations. The
normal administrator workflow never asks an administrator to choose or handle a
member's password.

## User journeys

Administrators create invitations under **Administration → Invitations**. A
share-link invitation has no reserved address; its recipient supplies their own
email address. An email invitation is reserved for the normalized destination
address and is delivered through the configured SMTP integration. Both flows
let the recipient choose their own username and password on `/join/<token>`.

Accounts are not pre-created. The `User` row and password hash are written only
when a valid pending invitation is accepted. New accounts use the `user` role,
are enabled but unverified, and must complete the existing email-confirmation
flow before signing in. Administrators may promote an accepted account later.

The User Management page links to this workflow. Its direct create-user API is
retained only for compatibility and emergency administration; it is not exposed
as the normal interface.

## Credential and lifecycle contract

- Raw credentials are generated with `secrets.token_urlsafe(32)` and shown only
  in the creation or replacement response.
- The database stores only the SHA-256 digest in
  `invite_tokens.token_digest`. Raw credentials must never be logged or added to
  audit events, templates rendered after creation, or database history.
- Invitations are pending, accepted, expired, or revoked. The visible status is
  derived from `used`, `used_at`, `expires_at`, and `revoked_at` rather than a
  separate mutable status field.
- Acceptance locks the pending invitation and creates the user and consumption
  record in one transaction. A concurrent second claim must not create another
  user.
- The default lifetime is seven days; administrator-created invitations may use
  1–30 days. Expired and revoked invitations do not consume member allowance.
- Replacing or resending rotates the credential and revokes the earlier
  invitation. A stored credential cannot be recovered for later copying.

Revision `20260923_30` hashes existing stored credentials before removing the
legacy plaintext column. Links already delivered before the upgrade continue to
work because the application hashes their raw URL credential before lookup.

## Public and administrator controls

Invitation creation, revocation, replacement, and allowance changes require an
authenticated administrator and CSRF validation. Member revocation is limited
to invitations created by that member. Public acceptance POSTs are limited to
five attempts per minute and use the same response for expired, revoked,
accepted, and unknown credentials.

Audit records identify invitation and user IDs but not raw credentials. Request
logging must continue using route patterns so `/join/<token>` values are not
written to access logs.

## Verification

Focused coverage lives in `tests/test_invitation_onboarding.py`,
`tests/test_account_recovery_audit.py`,
`tests/test_routes_admin_ext_invites.py`, and `tests/test_migrations.py`.
Changes must also run the accessibility audit, relevant UI contract tests,
desktop and 390 × 844 rendered checks, Ruff, and `git diff --check`.
