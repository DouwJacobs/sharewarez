#!/bin/bash
set -Eeuo pipefail

# Docker-specific application startup script
# This script is designed to run inside the Docker container


# Parse arguments
FORCE_SETUP=false
if [[ "${1:-}" == "--force-setup" || "${1:-}" == "-fs" ]]; then
    FORCE_SETUP=true
fi

# We're already in /app directory in Docker, no need to cd

if [[ "$FORCE_SETUP" == "true" ]]; then
    echo "🔄 Force setup mode - resetting database..."

    # Load environment for standalone execution
    python3 -c "
from dotenv import load_dotenv
load_dotenv()

from sharewarez import create_app, db
from sharewarez.utils.setup import reset_setup_state

# Create app and reset database
app = create_app()
with app.app_context():
    print('Dropping all tables...')
    db.drop_all()
    print('Recreating all tables...')
    db.create_all()
    print('Database reset complete.')

    reset_setup_state()
    print('Setup state reset - setup wizard will run on next startup')

print('Database reset complete. Restart the container to start the server.')
"
    exit 0
fi

echo "Starting application with uvicorn in Docker container..."

# Run complete startup initialization once before starting workers
python3 -c "
from sharewarez.init_manager import run_complete_startup_initialization
import sys

print('🚀 Starting application initialization...')
if not run_complete_startup_initialization():
    print('❌ Startup initialization failed!')
    sys.exit(1)
print('✅ Initialization completed - starting workers...')
"

# Ensure environment variables are set for worker processes
export SHAREWAREZ_MIGRATIONS_COMPLETE=true
export SHAREWAREZ_INITIALIZATION_COMPLETE=true

# Two workers balance concurrent browsing/streaming with the memory footprint of
# a full Flask application per worker. Operators can tune this for their host.
WEB_WORKERS="${WEB_WORKERS:-2}"
if ! [[ "$WEB_WORKERS" =~ ^[1-9][0-9]*$ ]]; then
    echo "Invalid WEB_WORKERS value '$WEB_WORKERS'; expected a positive integer."
    exit 1
fi

web_pid=''
job_pid=''

stop_children() {
    trap - TERM INT
    [[ -n "$web_pid" ]] && kill -TERM "$web_pid" 2>/dev/null || true
    [[ -n "$job_pid" ]] && kill -TERM "$job_pid" 2>/dev/null || true
    [[ -n "$web_pid" ]] && wait "$web_pid" 2>/dev/null || true
    [[ -n "$job_pid" ]] && wait "$job_pid" 2>/dev/null || true
}

handle_shutdown() {
    echo "Stopping web and background-job processes..."
    stop_children
    exit 0
}

trap handle_shutdown TERM INT

echo "Starting persistent background-job processor..."
python3 -m sharewarez.job_worker &
job_pid=$!

echo "Starting ${WEB_WORKERS} web worker(s)..."
uvicorn asgi:asgi_app --host 0.0.0.0 --port 5006 --workers "$WEB_WORKERS" &
web_pid=$!

# The two processes form one application unit. If either exits unexpectedly,
# stop its sibling and fail the container so Docker can restart both cleanly.
set +e
wait -n "$web_pid" "$job_pid"
child_status=$?
set -e

if kill -0 "$web_pid" 2>/dev/null; then
    echo "Background-job processor exited unexpectedly (status ${child_status})."
else
    echo "Web server exited unexpectedly (status ${child_status})."
fi
stop_children
[[ "$child_status" -ne 0 ]] && exit "$child_status"
exit 1
