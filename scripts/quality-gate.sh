#!/usr/bin/env bash
set -Eeuo pipefail

cd "$(dirname "$0")/.."

PYTHON_BIN="${PYTHON_BIN:-python3}"
POSTGRES_IMAGE="${POSTGRES_IMAGE:-postgres:17.6}"
TEST_DB_PORT="${TEST_DB_PORT:-55432}"
TEST_DB_CONTAINER="gamelibrary-quality-${$}"
IMAGE_TAG="${QUALITY_IMAGE_TAG:-gamelibrary:quality-gate}"
SKIP_CONTAINER_BUILD="${SKIP_CONTAINER_BUILD:-false}"

cleanup() {
    docker rm -f "$TEST_DB_CONTAINER" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

echo "==> Validating locked dependencies"
"$PYTHON_BIN" -m piptools compile --quiet --strip-extras --no-header --no-annotate \
    requirements.in --output-file /tmp/gamelibrary-requirements.txt
grep -E '^[A-Za-z0-9_.-]+==' requirements.txt | tr -d '\r' > /tmp/gamelibrary-locked-pins.txt
cmp --silent /tmp/gamelibrary-locked-pins.txt /tmp/gamelibrary-requirements.txt || {
    echo "requirements.txt is stale; run ./scripts/lock-dependencies.sh"
    exit 1
}
"$PYTHON_BIN" -m pip check
"$PYTHON_BIN" -m pip_audit -r requirements.txt

echo "==> Running correctness lint and focused type checks"
"$PYTHON_BIN" -m ruff check sharewarez tests scripts
"$PYTHON_BIN" scripts/accessibility_audit.py
"$PYTHON_BIN" -m mypy \
    sharewarez/backups.py \
    sharewarez/utils/migrations.py \
    sharewarez/utils/background_jobs.py \
    sharewarez/init_manager.py
"$PYTHON_BIN" -m compileall -q sharewarez migrations scripts tests

echo "==> Starting isolated PostgreSQL test database"
docker run -d --rm --name "$TEST_DB_CONTAINER" \
    -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=sharewareztest \
    -p "${TEST_DB_PORT}:5432" "$POSTGRES_IMAGE" >/dev/null
for _ in $(seq 1 30); do
    if docker exec "$TEST_DB_CONTAINER" pg_isready -U postgres -d sharewareztest >/dev/null 2>&1; then
        break
    fi
    sleep 1
done
docker exec "$TEST_DB_CONTAINER" pg_isready -U postgres -d sharewareztest >/dev/null

export TEST_DATABASE_URL="postgresql://postgres:postgres@localhost:${TEST_DB_PORT}/sharewareztest"
export DATABASE_URL="$TEST_DATABASE_URL"
export SECRET_KEY="quality-gate-only-secret-key-not-for-production"
export BACKUP_BEFORE_UPGRADE=false

echo "==> Smoke-testing the application factory"
"$PYTHON_BIN" -c "from sharewarez import create_app; app = create_app(); assert app.name == 'sharewarez'"

echo "==> Applying migrations to a freshly initialized PostgreSQL schema"
"$PYTHON_BIN" -c "from sharewarez import create_app, db; app = create_app(); app.app_context().push(); db.create_all()"
"$PYTHON_BIN" -m flask --app sharewarez:create_app db stamp 20260809_01
"$PYTHON_BIN" -m flask --app sharewarez:create_app db upgrade

echo "==> Running full test suite"
for test_module in tests/test_*.py; do
    echo "    $test_module"
    docker exec "$TEST_DB_CONTAINER" dropdb --if-exists --force -U postgres sharewareztest
    docker exec "$TEST_DB_CONTAINER" createdb -U postgres sharewareztest
    "$PYTHON_BIN" -m pytest -q "$test_module"
done

echo "==> Validating migrations, version, and Compose"
"$PYTHON_BIN" scripts/version.py check
"$PYTHON_BIN" -m flask --app sharewarez:create_app db heads
DATA_FOLDER_WAREZ=/tmp POSTGRES_USER=postgres POSTGRES_PASSWORD=postgres \
POSTGRES_DB=sharewarez docker compose config --quiet

if [[ "$SKIP_CONTAINER_BUILD" != "true" ]]; then
    echo "==> Building release-equivalent container"
    version="$(tr -d '\r\n' < VERSION)"
    docker build --build-arg "APP_VERSION=${version}" -t "$IMAGE_TAG" .
    docker run --rm --entrypoint python "$IMAGE_TAG" -m compileall -q /app/sharewarez /app/migrations
fi

echo "==> Production quality gate passed"
