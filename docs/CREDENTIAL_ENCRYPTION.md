# Integration credential encryption

Discord webhook URLs, SMTP passwords, and IGDB client secrets are encrypted in
PostgreSQL with authenticated Fernet encryption. Application code continues to
read and assign plaintext values through the model; ciphertext is stored with
an `enc:v1:` marker.

## Upgrade migration

Before upgrading, keep the existing `SECRET_KEY` unchanged and take a verified
backup. Migration `20260809_02` widens the three columns and encrypts existing
plaintext values. Verify integrations after startup.

For stronger key separation, set a random `CREDENTIAL_ENCRYPTION_KEY` on the
app before the migration. The value may be any high-entropy
secret; GameLibrary derives the Fernet key from it. When unset, the required
`SECRET_KEY` is used as key material for compatibility.

```bash
python -c 'import secrets; print(secrets.token_urlsafe(48))'
```

Back up the key outside the database. Losing or changing the active key makes
stored credentials unreadable.

## Rotate the encryption key

Take a verified backup and stop the application service so no credential can
be changed during rotation. Keep the database running, then execute the atomic
rotation using the old and new values only in the one-off process environment:

```bash
docker compose stop app
read -rsp 'Current credential key: ' OLD_CREDENTIAL_ENCRYPTION_KEY && echo
read -rsp 'Replacement credential key: ' NEW_CREDENTIAL_ENCRYPTION_KEY && echo
export OLD_CREDENTIAL_ENCRYPTION_KEY NEW_CREDENTIAL_ENCRYPTION_KEY
docker compose run --rm --no-deps \
  -e OLD_CREDENTIAL_ENCRYPTION_KEY \
  -e NEW_CREDENTIAL_ENCRYPTION_KEY \
  --entrypoint python app -m sharewarez.credentials
unset OLD_CREDENTIAL_ENCRYPTION_KEY NEW_CREDENTIAL_ENCRYPTION_KEY
```

If any value cannot be decrypted, the entire transaction rolls back. After a
successful command, replace `CREDENTIAL_ENCRYPTION_KEY` in `.env` with the new
value and restart the app. If the dedicated key was previously unset,
use the current `SECRET_KEY` as the old value. Never change the configured key
before rotation.

Database backups now contain ciphertext, but they still contain other sensitive
application data and must retain restricted access.
