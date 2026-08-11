# System email templates

Administrators manage transactional email content at `/admin/email-templates`. The editor stores only customized overrides; built-in defaults remain available in the application and take effect automatically when an override is reset or absent.

## Managed templates

| Template | Trigger | Template-specific variables |
| --- | --- | --- |
| Account confirmation | Registration | `user_name`, `confirm_url`, `expires_in` |
| Password reset | Password-reset request | `user_name`, `reset_url`, `expires_in` |
| User invitation | User invitation | `inviter_name`, `recipient_email`, `invite_url`, `expires_in` |
| New request for administrators | New game or update request | `request_type`, `game_name`, `requester_name`, `admin_url` |
| Request status update | Request status change | `user_name`, `game_name`, `status`, `response`, `game_url` |

Every template may also use `site_title` and `site_url`. Variables use Jinja syntax, for example `{{ user_name }}`. The renderer uses a sandbox with strict undefined-variable handling and automatically escapes variable values. Basic administrator-authored HTML is supported in the body.

## Validation and rendering

- Subjects cannot be blank, exceed 255 characters, or contain line breaks.
- Bodies cannot be blank or exceed 50,000 characters.
- Unknown variables and invalid Jinja expressions are rejected before save.
- Preview rendering uses representative sample data and never sends an email.
- The shared branded email shell is applied after the managed body is rendered.
- Resetting a template removes its database override and immediately restores the built-in default.

Custom overrides are stored in `system_email_templates`, introduced by Alembic revision `20260811_07`. The defaults are intentionally not seeded into the database so application upgrades can improve untouched templates without overwriting administrator customizations.
