# Local production quality gate

GameLibrary release validation runs locally and does not depend on GitHub CI.
Install the compiled development environment, then run the single gate:

```bash
python -m pip install -r requirements-dev.txt
./scripts/quality-gate.sh
```

The gate verifies that the production lockfile is current, audits dependencies,
runs correctness lint and focused static typing, compiles Python sources, starts
an isolated PostgreSQL 17.6 database, runs every test module against a freshly
recreated database to prevent legacy state leakage, checks the single
Alembic head and authoritative version, validates Compose, builds the production
container, and smoke-compiles the packaged application.

Set `SKIP_CONTAINER_BUILD=true` only for fast development feedback. It is not a
valid release result. `TEST_DB_PORT` and `QUALITY_IMAGE_TAG` may be overridden
when their defaults conflict with local services.

## Updating dependencies

Edit `requirements.in` or `requirements-dev.in`, then run:

```bash
./scripts/lock-dependencies.sh
python -m pip install -r requirements-dev.txt
./scripts/quality-gate.sh
```

Commit input and compiled lockfiles together. Review version changes and audit
results rather than accepting automated upgrades blindly.
