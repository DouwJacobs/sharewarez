#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")/.."
PYTHON_BIN="${PYTHON_BIN:-python3}"
full=false; release=false; dependencies=false
planner_args=()
while (($#)); do
    case "$1" in
        --full) full=true; planner_args+=(--full); shift ;;
        --release) release=true; shift ;;
        --dependencies) dependencies=true; shift ;;
        --base|--workers) planner_args+=("$1" "$2"); shift 2 ;;
        *) echo "Usage: $0 [--full] [--release] [--dependencies] [--base REF] [--workers N]" >&2; exit 2 ;;
    esac
done
scratch="$(mktemp -d)"
TEST_DB_CONTAINER="gamelibrary-quality-${$}"
started_database=false
cleanup() {
    if [[ "$started_database" == true ]]; then docker rm -f "$TEST_DB_CONTAINER" >/dev/null 2>&1 || true; fi
    rm -rf -- "$scratch"
}
trap cleanup EXIT INT TERM
"$PYTHON_BIN" scripts/validate.py --plan "${planner_args[@]}" > "$scratch/plan.json"
"$PYTHON_BIN" -c 'import json,sys; p=json.load(open(sys.argv[1])); print("Selected", len(p["modules"]), p["scope"], "test modules"); print("\n".join(p["reasons"]))' "$scratch/plan.json"
if "$PYTHON_BIN" -c 'import json,sys; p=json.load(open(sys.argv[1])); sys.exit(not any(x.startswith("requirements") for x in p["changed_files"]))' "$scratch/plan.json"; then dependencies=true; fi
if [[ "$dependencies" == true ]]; then
    echo "==> Validating changed dependency locks"
    cp requirements.txt "$scratch/requirements.txt"
    "$PYTHON_BIN" -m piptools compile --quiet --strip-extras --no-header --no-annotate requirements.in --output-file "$scratch/requirements.txt"
    grep -E '^[A-Za-z0-9_.-]+==' requirements.txt | tr -d '\r' > "$scratch/locked"
    grep -E '^[A-Za-z0-9_.-]+==' "$scratch/requirements.txt" | tr -d '\r' > "$scratch/compiled"
    cmp --silent "$scratch/locked" "$scratch/compiled" || { echo 'Dependency lock is stale; run scripts/lock-dependencies.sh' >&2; exit 1; }
fi
"$PYTHON_BIN" -m pip check
if [[ "$dependencies" == true || "$release" == true ]]; then "$PYTHON_BIN" -m pip_audit -r requirements.txt; fi
echo "==> Correctness, accessibility and type checks"
"$PYTHON_BIN" -m ruff check sharewarez tests scripts
"$PYTHON_BIN" scripts/accessibility_audit.py
"$PYTHON_BIN" -m mypy sharewarez/backups.py sharewarez/utils/migrations.py sharewarez/utils/background_jobs.py sharewarez/init_manager.py
"$PYTHON_BIN" -m compileall -q sharewarez migrations scripts
NODE_BIN="${NODE_BIN:-}"
if [[ -z "$NODE_BIN" ]]; then NODE_BIN="$(command -v node || command -v node.exe || true)"; fi
if [[ -z "$NODE_BIN" ]]; then echo 'Node is required for JavaScript regression checks; set NODE_BIN.' >&2; exit 1; fi
echo "==> JavaScript behavioural regressions"
"$NODE_BIN" --test tests/*.test.cjs
echo "==> Starting isolated PostgreSQL"
docker run -d --rm --name "$TEST_DB_CONTAINER" -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=sharewareztest \
    --tmpfs /var/lib/postgresql/data:rw,nosuid,nodev,size=1024m \
    -p "127.0.0.1:${TEST_DB_PORT:-}:5432" "${POSTGRES_IMAGE:-postgres:17.6}" >/dev/null
started_database=true
for _ in $(seq 1 60); do
    if docker exec "$TEST_DB_CONTAINER" pg_isready -h 127.0.0.1 -U postgres -d sharewareztest >/dev/null 2>&1; then break; fi
    sleep 1
done
docker exec "$TEST_DB_CONTAINER" pg_isready -h 127.0.0.1 -U postgres -d sharewareztest >/dev/null
binding="$(docker port "$TEST_DB_CONTAINER" 5432/tcp)"
export TEST_DATABASE_URL="postgresql://postgres:postgres@127.0.0.1:${binding##*:}/sharewareztest"
export DATABASE_URL="$TEST_DATABASE_URL" SECRET_KEY='quality-gate-only-secret-key-not-for-production' BACKUP_BEFORE_UPGRADE=false
# Current metadata bootstraps new installations; upgrade tests exercise old schemas separately.
"$PYTHON_BIN" -c 'from sharewarez import create_app,db; from sharewarez.utils.migrations import bootstrap_schema_extras; app=create_app(); app.app_context().push(); db.create_all(); bootstrap_schema_extras(db.engine)'
"$PYTHON_BIN" -m flask --app sharewarez:create_app db stamp head
"$PYTHON_BIN" -m flask --app sharewarez:create_app db upgrade
"$PYTHON_BIN" scripts/validate.py "${planner_args[@]}"
"$PYTHON_BIN" scripts/version.py check
DATA_FOLDER_WAREZ=/tmp POSTGRES_USER=postgres POSTGRES_PASSWORD=postgres POSTGRES_DB=sharewarez docker compose config --quiet
if [[ "$release" == true && "${SKIP_CONTAINER_BUILD:-false}" != true ]]; then
    echo "==> Building release-equivalent container"
    version="$(tr -d '\r\n' < VERSION)"
    image="${QUALITY_IMAGE_TAG:-gamelibrary:quality-gate}"
    docker build --build-arg "APP_VERSION=$version" -t "$image" .
    docker run --rm --entrypoint python "$image" -m compileall -q /app/sharewarez /app/migrations
fi
echo "==> Validation passed"
