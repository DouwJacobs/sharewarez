#!/bin/bash

echo "🚀 SharewareZ container starting up..."


# Extract database connection info from DATABASE_URL if available
if [[ -n "$DATABASE_URL" ]]; then
    # Parse DATABASE_URL for connection details
    # Format: postgresql://user:password@host:port/database
    DB_HOST=$(echo $DATABASE_URL | sed -n 's/.*@\([^:]*\):.*/\1/p')
    DB_USER=$(echo $DATABASE_URL | sed -n 's/.*:\/\/\([^:]*\):.*/\1/p')
    DB_PORT=$(echo $DATABASE_URL | sed -n 's/.*:\([0-9]*\)\/.*/\1/p')
else
    # Fall back to individual environment variables
    DB_HOST=${DATABASE_HOST:-db}
    DB_USER=${POSTGRES_USER:-postgres}
    DB_PORT=${DATABASE_PORT:-5432}
fi

# Function to check if PostgreSQL is ready using Python
wait_for_postgres() {
    echo "🔄 Waiting for PostgreSQL at ${DB_HOST}:${DB_PORT}..."

    until python3 -c "
import psycopg2
import sys
import os
from urllib.parse import urlparse

try:
    # Use DATABASE_URL if available, otherwise construct from parts
    if os.environ.get('DATABASE_URL'):
        url = urlparse(os.environ['DATABASE_URL'])
        conn = psycopg2.connect(
            host=url.hostname,
            port=url.port,
            user=url.username,
            password=url.password,
            database=url.path[1:],
            connect_timeout=5
        )
    else:
        conn = psycopg2.connect(
            host='${DB_HOST}',
            port=${DB_PORT},
            user='${DB_USER}',
            password=os.environ.get('POSTGRES_PASSWORD', 'postgres'),
            database=os.environ.get('POSTGRES_DB', 'sharewarez'),
            connect_timeout=5
        )
    conn.close()
    print('✅ PostgreSQL connection successful')
except Exception as e:
    print(f'❌ Connection failed: {e}')
    sys.exit(1)
" 2>/dev/null; do
        echo "⏳ PostgreSQL not ready yet, waiting 5 seconds..."
        sleep 5
    done
    echo "✅ PostgreSQL is now available!"
}

# Wait for PostgreSQL to come online
wait_for_postgres

echo "🎮 Starting SharewareZ Docker container..."

if [[ "${1:-}" == "worker" ]]; then
    shift
    echo "Starting persistent background worker..."
    exec python3 -m sharewarez.job_worker "$@"
fi

# Pass all arguments through to startweb-docker.sh
exec /app/startweb-docker.sh "$@"
