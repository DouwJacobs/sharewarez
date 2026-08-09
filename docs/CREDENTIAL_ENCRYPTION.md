# Integration credential encryption

Discord webhook URLs, SMTP passwords, and IGDB client secrets are encrypted in
PostgreSQL with authenticated Fernet encryption. Application code continues to
read and assign plaintext values through the model; ciphertext is stored with
an `enc:v1:` marker.

## Upgrade migration

Before upgrading, keep the existing `SECRET_KEY` unchanged and take a verified
backup. Migration `20260809_02` widens the three columns and encrypts existing
plaintext values. Verify integrations after startup.

For stronger key separation, set a random `CREDENTIAL_ENCRYPTION_KEY` on both
the app and worker before the migration. The value may be any high-entropy
secret; GameLibrary derives the Fernet key from it. When unset, the required
`SECRET_KEY` is used as key material for compatibility.

```bash
python -c 'import secrets; print(secrets.token_urlsafe(48))'
```

Back up the key outside the database. Losing or changing the active key makes
stored credentials unreadable. Before changing either key, record the current
integration values; deploy the new key and re-enter each credential. Automated
dual-key rotation is not yet provided.

Database backups now contain ciphertext, but they still contain other sensitive
application data and must retain restricted access.
