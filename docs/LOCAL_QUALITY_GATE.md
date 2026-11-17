# Local production quality gate

Run `bash scripts/quality-gate.sh` for normal development feedback. It selects
regressions for affected domains and runs them concurrently in isolated,
disposable PostgreSQL databases. Unknown production changes and shared
configuration fall back to the full suite.

```bash
python -m pip install -r requirements-dev.txt
bash scripts/quality-gate.sh                 # affected tests and shared checks
bash scripts/quality-gate.sh --full          # complete retained regression suite
bash scripts/quality-gate.sh --release       # affected checks, dependency audit, image build
bash scripts/quality-gate.sh --dependencies  # verify lock resolution and dependency audit
```

See [validation modes and isolation](VALIDATION.md) for selection rules, tooling,
reports, worker limits and exact-release publishing. Dependency lock resolution
also runs automatically when requirements change. Use
`bash scripts/lock-dependencies.sh` when intentionally refreshing dependencies,
and commit input constraints and compiled locks together.

The gate checks lint, accessibility, focused static typing, Python compilation,
all JavaScript runners, migration bootstrap, version and Compose configuration.
A fresh schema uses current models and is stamped at the active Alembic head;
historical upgrades are covered separately by migration tests and release drills.

`SKIP_CONTAINER_BUILD=true` can separate a release validation run from its image
build, but a release still requires an exact committed image build and container
smoke check before publication. The full suite is reserved for shared changes,
release audits and periodic regression checks.
