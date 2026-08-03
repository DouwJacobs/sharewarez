#!/bin/bash


# Parse arguments
FORCE_SETUP=false
RELOAD_MODE="auto"
for arg in "$@"; do
    case "$arg" in
        --force-setup|-fs) FORCE_SETUP=true ;;
        --reload) RELOAD_MODE="true" ;;
        --no-reload|--production) RELOAD_MODE="false" ;;
        *)
            echo "❌ Unknown argument: $arg"
            echo "Usage: ./startweb.sh [--force-setup] [--reload|--no-reload]"
            exit 1
            ;;
    esac
done

cd "$(dirname "$0")"

# Respect an already activated pyenv/virtualenv environment. Fall back to the
# legacy project-local venv when present.
if [ -f venv/bin/activate ]; then
    source venv/bin/activate
elif [ -z "$VIRTUAL_ENV" ]; then
    echo "❌ No Python environment is active. Run: pyenv activate sharewarez"
    exit 1
fi

# Load .env file and export variables to shell environment
if [ -f .env ]; then
    echo "📌 Loading environment variables from .env..."
    set -a  # automatically export all variables
    source .env
    set +a  # turn off automatic export

    # Debug: Verify DATABASE_URL is loaded
    if [ -n "$DATABASE_URL" ]; then
        echo "✅ DATABASE_URL loaded from .env"
    else
        echo "❌ WARNING: DATABASE_URL not found in environment!"
    fi
else
    echo "⚠️  Warning: .env file not found in $(pwd)"
fi

if [[ "$FORCE_SETUP" == "true" ]]; then
    echo "🔄 Force setup mode - resetting database..."

    # Environment variables are already loaded from .env file above
    python3 -c "
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

print('Database reset complete. Run ./startweb.sh to start the server.')
"
    exit 0
fi

if [[ "$RELOAD_MODE" == "auto" ]]; then
    RELOAD_MODE="${HOT_RELOAD:-${DEV_MODE:-false}}"
fi
RELOAD_MODE="$(printf '%s' "$RELOAD_MODE" | tr '[:upper:]' '[:lower:]')"

echo "Starting SharewareZ with uvicorn..."

# Run complete startup initialization once before starting workers
python3 -c "
from sharewarez.init_manager import run_complete_startup_initialization
import sys

print('🚀 Starting SharewareZ initialization...')
if not run_complete_startup_initialization():
    print('❌ Startup initialization failed!')
    sys.exit(1)
print('✅ Initialization completed - starting workers...')
"

# Ensure environment variables are set for worker processes
export SHAREWAREZ_MIGRATIONS_COMPLETE=true
export SHAREWAREZ_INITIALIZATION_COMPLETE=true

# Set port for uvicorn (default 5006, can be overridden by PORT env var)
export PORT=${PORT:-5006}

# Uvicorn cannot combine multiple workers with its reload supervisor. In
# development, watch Python, templates, and source theme assets. Production
# keeps the multi-worker configuration and can be selected with --no-reload.
if [[ "$RELOAD_MODE" == "true" || "$RELOAD_MODE" == "1" || "$RELOAD_MODE" == "yes" ]]; then
    echo "🔥 Hot reload enabled (single development worker)"
    export SHAREWAREZ_HOT_RELOAD=true
    uvicorn asgi:asgi_app \
        --host 0.0.0.0 \
        --port "$PORT" \
        --reload \
        --reload-dir . \
        --reload-include '*.py' \
        --reload-include '*.html' \
        --reload-include '*.css' \
        --reload-include '*.js' \
        --reload-include '*.json'
else
    echo "🚀 Hot reload disabled (${WEB_WORKERS:-4} workers)"
    uvicorn asgi:asgi_app --host 0.0.0.0 --port "$PORT" --workers "${WEB_WORKERS:-4}"
fi
