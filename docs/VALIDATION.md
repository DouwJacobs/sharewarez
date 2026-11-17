# Fast validation and release checks

Run `PYTHON_BIN=python3.12 bash scripts/quality-gate.sh` from the repository.
Node, Docker and the development requirements must be installed. On WSL with
Windows Node, set `NODE_BIN='/mnt/c/Program Files/nodejs/node.exe'`.

The normal path selects regressions for changes since the merge base with
`origin/main`, including staged, unstaged, and new files. Use `--base REF` when
reviewing another baseline. Inspect the selection without starting a database:

```sh
python scripts/validate.py --plan --base origin/main
```

Known feature changes select their related routes, permissions, persistence,
and job tests. Recognized model changes select the affected domains. Unknown
production modules, shared startup/configuration changes, unknown model changes,
dependency changes, and changes to the shared test harness fall back to the full
suite. Documentation-only changes retain the inexpensive version smoke check.
When adding a production domain, add its mapping in `scripts/validate.py`; unknown
paths must never silently skip coverage.

Modes:

| Command | Scope |
| --- | --- |
| `scripts/quality-gate.sh` | Affected Python regressions, all small JavaScript runners, lint, accessibility, focused typing, bootstrap/migration/version/Compose checks |
| `scripts/quality-gate.sh --full` | Complete retained Python suite; use for shared changes and periodic audits |
| `scripts/quality-gate.sh --release` | Normal selection plus dependency vulnerability audit and cached container build |
| `scripts/quality-gate.sh --dependencies` | Re-resolve/compare the dependency lock and audit dependencies |

The lock is also checked automatically when requirements change. An ordinary
UI/code edit does not re-resolve the dependency graph or rebuild an image.

Python modules run in separate processes and separate disposable PostgreSQL
databases, four at a time by default (`--workers 1` through `8`). The local test
server binds only to loopback and uses temporary memory-backed storage. Each
worker drops only its own generated database; the container is removed on exit.
This preserves isolation for destructive migration fixtures and existing tests
without recreating a container or starting every module serially.

Per-module timings, logs, JUnit results and the exact selection are written to
`.validation/<UTC timestamp>/`. The directory is excluded from Git and Docker
build contexts. A failing child process or missing coverage mapping cannot be
reported as a successful targeted run.

Fixture passwords still use real Argon2 hashing/verification with inexpensive
test-only work factors. The marked `password_policy` test uses production work
factors. Production password parameters are unchanged. Schema setup is no longer
repeated twice per fixture, and model cleanup uses one FK-safe truncate rather
than repeatedly truncating overlapping cascades. Source-string UI assertions
have been retired in favour of actual route/rendering, JavaScript behaviour,
accessibility checks and rendered desktop/mobile verification.

Before publishing, commit the verified source, build from that exact revision,
smoke-test the image and migrations with an isolated database, then publish the
versioned Git/Docker tags. `Dockerfile` places version metadata after dependency
layers so a version bump can reuse the expensive apt/pip cache.
