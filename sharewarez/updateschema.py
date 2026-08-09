from sqlalchemy import create_engine, text
from config import Config

class DatabaseManager:
    def __init__(self):
        # Load the database configuration from Config
        self.database_uri = Config.SQLALCHEMY_DATABASE_URI
        # Create a SQLAlchemy engine
        self.engine = create_engine(self.database_uri)

    def add_column_if_not_exists(self):

        # SQL commands to add new columns and tables
        add_columns_sql = """
        -- Ensure global_settings table exists before altering it
        CREATE TABLE IF NOT EXISTS global_settings (
            id SERIAL PRIMARY KEY,
            settings TEXT,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            discord_webhook_url VARCHAR(512),
            smtp_server VARCHAR(255),
            smtp_port INTEGER,
            smtp_username VARCHAR(255),
            smtp_password VARCHAR(255),
            smtp_use_tls BOOLEAN DEFAULT TRUE,
            smtp_default_sender VARCHAR(255),
            smtp_last_tested TIMESTAMP,
            smtp_enabled BOOLEAN DEFAULT FALSE,
            discord_bot_name VARCHAR(100),
            discord_bot_avatar_url VARCHAR(512),
            enable_delete_game_on_disk BOOLEAN DEFAULT TRUE,
            igdb_client_id VARCHAR(255),
            igdb_client_secret VARCHAR(255),
            igdb_last_tested TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS background_jobs (
            id VARCHAR(36) PRIMARY KEY,
            task_name VARCHAR(100) NOT NULL,
            queue VARCHAR(50) NOT NULL DEFAULT 'default',
            status VARCHAR(20) NOT NULL DEFAULT 'queued',
            payload TEXT NOT NULL DEFAULT '{}',
            result TEXT,
            progress INTEGER NOT NULL DEFAULT 0,
            progress_message VARCHAR(255),
            attempts INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL DEFAULT 3,
            available_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            started_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            heartbeat_at TIMESTAMPTZ,
            locked_by VARCHAR(100),
            cancel_requested BOOLEAN NOT NULL DEFAULT FALSE,
            error_message TEXT,
            created_by_id INTEGER REFERENCES users(id) ON DELETE SET NULL
        );

        CREATE INDEX IF NOT EXISTS ix_background_jobs_claim
        ON background_jobs(status, available_at, created_at);

        CREATE TABLE IF NOT EXISTS library_scan_states (
            id SERIAL PRIMARY KEY,
            library_uuid VARCHAR(36) NOT NULL REFERENCES libraries(uuid) ON DELETE CASCADE,
            folder_path VARCHAR(1024) NOT NULL,
            scan_mode VARCHAR(20) NOT NULL DEFAULT 'folders',
            fingerprint VARCHAR(64) NOT NULL,
            entry_count INTEGER NOT NULL DEFAULT 0,
            total_size BIGINT NOT NULL DEFAULT 0,
            scanned_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_library_scan_state_target UNIQUE (library_uuid, folder_path, scan_mode)
        );

        CREATE TABLE IF NOT EXISTS library_scan_schedules (
            id VARCHAR(36) PRIMARY KEY,
            library_uuid VARCHAR(36) NOT NULL REFERENCES libraries(uuid) ON DELETE CASCADE,
            folder_path VARCHAR(1024) NOT NULL,
            scan_mode VARCHAR(20) NOT NULL DEFAULT 'folders',
            interval_minutes INTEGER NOT NULL DEFAULT 1440,
            options TEXT NOT NULL DEFAULT '{}',
            is_enabled BOOLEAN NOT NULL DEFAULT TRUE,
            next_run TIMESTAMPTZ NOT NULL,
            last_run TIMESTAMPTZ,
            last_job_id VARCHAR(36) REFERENCES background_jobs(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS ix_library_scan_schedules_due
        ON library_scan_schedules(is_enabled, next_run);

        ALTER TABLE collections ADD COLUMN IF NOT EXISTS is_smart BOOLEAN NOT NULL DEFAULT FALSE;
        ALTER TABLE collections ADD COLUMN IF NOT EXISTS smart_rules TEXT;
        ALTER TABLE collections ADD COLUMN IF NOT EXISTS smart_sort VARCHAR(30) NOT NULL DEFAULT 'name';
        ALTER TABLE collections ADD COLUMN IF NOT EXISTS smart_sort_order VARCHAR(4) NOT NULL DEFAULT 'asc';
        ALTER TABLE collections ADD COLUMN IF NOT EXISTS smart_limit INTEGER NOT NULL DEFAULT 24;
        CREATE INDEX IF NOT EXISTS ix_collections_is_smart ON collections(is_smart);
        
        ALTER TABLE global_settings
        ADD COLUMN IF NOT EXISTS site_url VARCHAR(255) DEFAULT 'http://127.0.0.1:5006';

        ALTER TABLE global_settings
        ADD COLUMN IF NOT EXISTS discord_bot_name VARCHAR(255);
        
        ALTER TABLE global_settings
        ADD COLUMN IF NOT EXISTS discord_bot_avatar_url VARCHAR(255);

        ALTER TABLE global_settings
        ADD COLUMN IF NOT EXISTS igdb_client_id VARCHAR(255);

        ALTER TABLE global_settings
        ADD COLUMN IF NOT EXISTS igdb_client_secret VARCHAR(255);

        ALTER TABLE global_settings
        ADD COLUMN IF NOT EXISTS igdb_last_tested TIMESTAMP;

        -- Create allowed_file_types table if it doesn't exist
        CREATE TABLE IF NOT EXISTS allowed_file_types (
            id SERIAL PRIMARY KEY,
            value VARCHAR(10) UNIQUE NOT NULL
        );

        -- Create user_favorites table if it doesn't exist
        CREATE TABLE IF NOT EXISTS user_favorites (
            user_id INTEGER REFERENCES users(id),
            game_uuid VARCHAR(36) REFERENCES games(uuid),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, game_uuid)
        );

        -- Create user_game_status table if it doesn't exist
        CREATE TABLE IF NOT EXISTS user_game_status (
            user_id INTEGER REFERENCES users(id),
            game_uuid VARCHAR(36) REFERENCES games(uuid),
            status VARCHAR(20) NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, game_uuid)
        );

        -- Create index on user_game_status for performance
        CREATE INDEX IF NOT EXISTS idx_user_game_status_lookup ON user_game_status(user_id, game_uuid);

        -- Custom tags are reusable and are assigned to games through a
        -- many-to-many association table.
        CREATE TABLE IF NOT EXISTS game_tags (
            id SERIAL PRIMARY KEY,
            name VARCHAR(50) UNIQUE NOT NULL
        );

        CREATE TABLE IF NOT EXISTS game_tag_association (
            game_id INTEGER REFERENCES games(id) ON DELETE CASCADE,
            tag_id INTEGER REFERENCES game_tags(id) ON DELETE CASCADE,
            PRIMARY KEY (game_id, tag_id)
        );

        CREATE TABLE IF NOT EXISTS game_updates (
            id SERIAL PRIMARY KEY,
            uuid VARCHAR(36) UNIQUE NOT NULL,
            game_uuid VARCHAR(36) NOT NULL,
            times_downloaded INTEGER DEFAULT 0,
            nfo_content TEXT,
            file_path VARCHAR(255) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (game_uuid) REFERENCES games(uuid) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS game_extras (
            id SERIAL PRIMARY KEY,
            uuid VARCHAR(36) UNIQUE NOT NULL,
            game_uuid VARCHAR(36) NOT NULL,
            times_downloaded INTEGER DEFAULT 0,
            nfo_content TEXT,
            file_path VARCHAR(255) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (game_uuid) REFERENCES games(uuid) ON DELETE CASCADE
        );

        -- Create system_events table if it doesn't exist
        CREATE TABLE IF NOT EXISTS system_events (
            id SERIAL PRIMARY KEY,
            event_type VARCHAR(32) DEFAULT 'log',
            event_text VARCHAR(256) NOT NULL,
            event_level VARCHAR(32) DEFAULT 'information',
            audit_user INTEGER REFERENCES users(id),
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Ensure scan_jobs table exists before altering it
        CREATE TABLE IF NOT EXISTS scan_jobs (
            id SERIAL PRIMARY KEY,
            status VARCHAR(20),
            error_message TEXT,
            is_enabled BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        ALTER TABLE scan_jobs
        ADD COLUMN IF NOT EXISTS removed_count INTEGER DEFAULT 0;

        -- Ensure images table exists before altering it
        CREATE TABLE IF NOT EXISTS images (
            id SERIAL PRIMARY KEY,
            game_uuid VARCHAR(36),
            image_type VARCHAR(50),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        -- Add new columns to images table for optimized image downloading
        ALTER TABLE images
        ADD COLUMN IF NOT EXISTS igdb_image_id VARCHAR(255);

        ALTER TABLE images
        ADD COLUMN IF NOT EXISTS download_url VARCHAR(500);

        ALTER TABLE images
        ADD COLUMN IF NOT EXISTS is_downloaded BOOLEAN DEFAULT FALSE;

        -- Add image download settings to global_settings table
        ALTER TABLE global_settings
        ADD COLUMN IF NOT EXISTS use_turbo_image_downloads BOOLEAN DEFAULT TRUE;

        ALTER TABLE global_settings
        ADD COLUMN IF NOT EXISTS turbo_download_threads INTEGER DEFAULT 8;

        ALTER TABLE global_settings
        ADD COLUMN IF NOT EXISTS turbo_download_batch_size INTEGER DEFAULT 200;

        ALTER TABLE global_settings
        ADD COLUMN IF NOT EXISTS scan_thread_count INTEGER DEFAULT 1;

        ALTER TABLE global_settings
        ADD COLUMN IF NOT EXISTS discord_notify_manual_trigger BOOLEAN DEFAULT FALSE;

        -- Add setup state tracking columns to global_settings table
        ALTER TABLE global_settings
        ADD COLUMN IF NOT EXISTS setup_in_progress BOOLEAN DEFAULT FALSE;

        ALTER TABLE global_settings
        ADD COLUMN IF NOT EXISTS setup_current_step INTEGER DEFAULT 1;

        ALTER TABLE global_settings
        ADD COLUMN IF NOT EXISTS setup_completed BOOLEAN DEFAULT FALSE;

        -- Add setting_download_missing_images column to scan_jobs table
        ALTER TABLE scan_jobs
        ADD COLUMN IF NOT EXISTS setting_download_missing_images BOOLEAN DEFAULT FALSE;

        -- Change error_message column from varchar(512) to text for longer error messages
        ALTER TABLE scan_jobs
        ALTER COLUMN error_message TYPE TEXT;

        -- Add progress tracking columns to scan_jobs table for scan optimization
        ALTER TABLE scan_jobs
        ADD COLUMN IF NOT EXISTS current_processing VARCHAR(255);

        ALTER TABLE scan_jobs
        ADD COLUMN IF NOT EXISTS last_progress_update TIMESTAMP;

        -- Add force_updates_extras setting to scan_jobs table for enhanced scan functionality
        ALTER TABLE scan_jobs
        ADD COLUMN IF NOT EXISTS setting_force_updates_extras BOOLEAN DEFAULT FALSE;

        -- Add 'Cancelled' value to the status_enum for scan_jobs
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_enum WHERE enumlabel = 'Cancelled' AND enumtypid = (SELECT oid FROM pg_type WHERE typname = 'status_enum')) THEN
                ALTER TYPE status_enum ADD VALUE 'Cancelled';
            END IF;
        END $$;

        -- Add 'Stopping' value to the status_enum for scan_jobs
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_enum WHERE enumlabel = 'Stopping' AND enumtypid = (SELECT oid FROM pg_type WHERE typname = 'status_enum')) THEN
                ALTER TYPE status_enum ADD VALUE 'Stopping';
            END IF;
        END $$;

        -- Add unique index to prevent duplicate cover images (but allow multiple screenshots)
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE c.relname = 'unique_game_cover_image' AND n.nspname = 'public'
            ) THEN
                CREATE UNIQUE INDEX unique_game_cover_image 
                ON images (game_uuid) 
                WHERE image_type = 'cover';
            END IF;
        END $$;

        -- Rename columns in filters table from old release group terminology to scanning filter terminology
        DO $$
        BEGIN
            -- Rename rlsgroup to filter_pattern if the old column exists
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='filters' AND column_name='rlsgroup'
            ) THEN
                ALTER TABLE filters RENAME COLUMN rlsgroup TO filter_pattern;
                RAISE NOTICE 'Renamed column rlsgroup to filter_pattern in filters table';
            END IF;

            -- Rename rlsgroupcs to case_sensitive if the old column exists
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='filters' AND column_name='rlsgroupcs'
            ) THEN
                ALTER TABLE filters RENAME COLUMN rlsgroupcs TO case_sensitive;
                RAISE NOTICE 'Renamed column rlsgroupcs to case_sensitive in filters table';
            END IF;
        END $$;

        -- Add attract mode settings to global_settings table
        ALTER TABLE global_settings
        ADD COLUMN IF NOT EXISTS attract_mode_enabled BOOLEAN DEFAULT FALSE;

        ALTER TABLE global_settings
        ADD COLUMN IF NOT EXISTS attract_mode_idle_timeout INTEGER DEFAULT 60;

        ALTER TABLE global_settings
        ADD COLUMN IF NOT EXISTS attract_mode_settings TEXT;

        -- Create user_attract_mode_settings table if it doesn't exist
        CREATE TABLE IF NOT EXISTS user_attract_mode_settings (
            id SERIAL PRIMARY KEY,
            user_id VARCHAR(36) UNIQUE NOT NULL,
            has_customized BOOLEAN DEFAULT FALSE,
            filter_settings TEXT,
            autoplay_settings TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
        );

        -- Add HowLongToBeat integration fields to games table
        ALTER TABLE games
        ADD COLUMN IF NOT EXISTS hltb_id INTEGER;

        ALTER TABLE games
        ADD COLUMN IF NOT EXISTS hltb_main_story FLOAT;

        ALTER TABLE games
        ADD COLUMN IF NOT EXISTS hltb_main_extra FLOAT;

        ALTER TABLE games
        ADD COLUMN IF NOT EXISTS hltb_completionist FLOAT;

        ALTER TABLE games
        ADD COLUMN IF NOT EXISTS hltb_all_styles FLOAT;

        ALTER TABLE games
        ADD COLUMN IF NOT EXISTS hltb_last_updated TIMESTAMP;

        -- Add install instructions field to games table
        ALTER TABLE games
        ADD COLUMN IF NOT EXISTS install_instructions TEXT;

        ALTER TABLE games
        ADD COLUMN IF NOT EXISTS version VARCHAR(100);

        ALTER TABLE games
        ADD COLUMN IF NOT EXISTS edition_name VARCHAR(255);

        ALTER TABLE game_updates ADD COLUMN IF NOT EXISTS title VARCHAR(255);
        ALTER TABLE game_updates ADD COLUMN IF NOT EXISTS version VARCHAR(100);
        ALTER TABLE game_updates ADD COLUMN IF NOT EXISTS update_number INTEGER;
        ALTER TABLE game_updates ADD COLUMN IF NOT EXISTS requires_version VARCHAR(100);
        ALTER TABLE game_updates ADD COLUMN IF NOT EXISTS install_instructions TEXT;
        ALTER TABLE game_updates ADD COLUMN IF NOT EXISTS changelog TEXT;
        ALTER TABLE game_updates ADD COLUMN IF NOT EXISTS release_date DATE;
        ALTER TABLE game_updates ADD COLUMN IF NOT EXISTS is_cumulative BOOLEAN DEFAULT FALSE NOT NULL;
        ALTER TABLE game_updates ADD COLUMN IF NOT EXISTS size BIGINT DEFAULT 0 NOT NULL;
        ALTER TABLE game_updates ADD COLUMN IF NOT EXISTS metadata_managed BOOLEAN DEFAULT FALSE NOT NULL;
        CREATE INDEX IF NOT EXISTS idx_game_updates_game_path ON game_updates(game_uuid, file_path);

        -- Preserve the exact downloaded content in the administrative history.
        ALTER TABLE download_requests ADD COLUMN IF NOT EXISTS content_type VARCHAR(20) DEFAULT 'game' NOT NULL;
        ALTER TABLE download_requests ADD COLUMN IF NOT EXISTS content_title VARCHAR(255);
        ALTER TABLE download_requests ADD COLUMN IF NOT EXISTS game_update_id INTEGER REFERENCES game_updates(id) ON DELETE SET NULL;
        ALTER TABLE download_requests ADD COLUMN IF NOT EXISTS game_extra_id INTEGER REFERENCES game_extras(id) ON DELETE SET NULL;
        CREATE INDEX IF NOT EXISTS idx_download_requests_content_type ON download_requests(content_type);
        CREATE INDEX IF NOT EXISTS idx_download_requests_game_update ON download_requests(game_update_id);

        UPDATE download_requests AS request
        SET content_type = 'update',
            content_title = COALESCE(game_update.title, regexp_replace(game_update.file_path, '^.*/', '')),
            game_update_id = game_update.id
        FROM game_updates AS game_update
        WHERE request.file_location = game_update.file_path
          AND request.game_uuid = game_update.game_uuid
          AND request.game_update_id IS NULL;

        UPDATE download_requests AS request
        SET content_type = 'extra',
            content_title = regexp_replace(game_extra.file_path, '^.*/', ''),
            game_extra_id = game_extra.id
        FROM game_extras AS game_extra
        WHERE request.file_location = game_extra.file_path
          AND request.game_uuid = game_extra.game_uuid
          AND request.game_extra_id IS NULL;

        -- User-submitted, edition-aware game requests.
        CREATE TABLE IF NOT EXISTS game_requests (
            id SERIAL PRIMARY KEY,
            igdb_id INTEGER UNIQUE NOT NULL,
            parent_igdb_id INTEGER NOT NULL,
            parent_game_name VARCHAR(255) NOT NULL,
            game_name VARCHAR(255) NOT NULL,
            edition_name VARCHAR(255),
            cover_url VARCHAR(512),
            summary TEXT,
            platforms TEXT,
            first_release_date TIMESTAMP,
            status VARCHAR(32) NOT NULL DEFAULT 'pending',
            public_response TEXT,
            internal_note TEXT,
            fulfilled_game_uuid VARCHAR(36) REFERENCES games(uuid) ON DELETE SET NULL,
            handled_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            resolved_at TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_game_requests_parent ON game_requests(parent_igdb_id);
        CREATE INDEX IF NOT EXISTS idx_game_requests_status ON game_requests(status);

        ALTER TABLE game_requests ADD COLUMN IF NOT EXISTS parent_game_name VARCHAR(255);
        UPDATE game_requests SET parent_game_name = game_name WHERE parent_game_name IS NULL;
        ALTER TABLE game_requests ALTER COLUMN parent_game_name SET NOT NULL;

        CREATE TABLE IF NOT EXISTS game_request_users (
            id SERIAL PRIMARY KEY,
            request_id INTEGER NOT NULL REFERENCES game_requests(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            requester_note TEXT,
            accept_any_edition BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            withdrawn_at TIMESTAMP,
            satisfied_at TIMESTAMP,
            satisfied_by_game_uuid VARCHAR(36) REFERENCES games(uuid) ON DELETE SET NULL,
            last_notified_status VARCHAR(32),
            CONSTRAINT uq_game_request_user UNIQUE (request_id, user_id)
        );

        CREATE INDEX IF NOT EXISTS idx_game_request_users_request ON game_request_users(request_id);
        CREATE INDEX IF NOT EXISTS idx_game_request_users_user ON game_request_users(user_id);
        ALTER TABLE game_request_users ADD COLUMN IF NOT EXISTS satisfied_at TIMESTAMP;
        ALTER TABLE game_request_users ADD COLUMN IF NOT EXISTS satisfied_by_game_uuid VARCHAR(36) REFERENCES games(uuid) ON DELETE SET NULL;

        -- Update request feature: add request_type and source_game_uuid columns
        ALTER TABLE game_requests ADD COLUMN IF NOT EXISTS request_type VARCHAR(16) NOT NULL DEFAULT 'new_game';
        ALTER TABLE game_requests ADD COLUMN IF NOT EXISTS source_game_uuid VARCHAR(36) REFERENCES games(uuid) ON DELETE SET NULL;
        CREATE INDEX IF NOT EXISTS idx_game_requests_type ON game_requests(request_type);
        CREATE INDEX IF NOT EXISTS idx_game_requests_source ON game_requests(source_game_uuid);

        -- Make igdb_id nullable and drop the unique constraint for update requests
        ALTER TABLE game_requests ALTER COLUMN igdb_id DROP NOT NULL;
        ALTER TABLE game_requests ALTER COLUMN parent_igdb_id DROP NOT NULL;
        ALTER TABLE game_requests ALTER COLUMN parent_game_name DROP NOT NULL;
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'game_requests_igdb_id_key'
                  AND conrelid = 'game_requests'::regclass
            ) THEN
                ALTER TABLE game_requests DROP CONSTRAINT game_requests_igdb_id_key;
            END IF;
        END $$;

        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT igdb_id FROM game_requests
                WHERE request_type = 'new_game' GROUP BY igdb_id HAVING COUNT(*) > 1
            ) THEN
                CREATE UNIQUE INDEX IF NOT EXISTS uq_game_requests_new_game_igdb
                    ON game_requests(igdb_id) WHERE request_type = 'new_game';
            ELSE
                RAISE NOTICE 'Skipped new-game request uniqueness index because duplicates already exist';
            END IF;
            IF NOT EXISTS (
                SELECT source_game_uuid FROM game_requests
                WHERE request_type = 'update'
                  AND status NOT IN ('fulfilled', 'not_planned', 'cancelled')
                GROUP BY source_game_uuid HAVING COUNT(*) > 1
            ) THEN
                CREATE UNIQUE INDEX IF NOT EXISTS uq_game_requests_active_update
                    ON game_requests(source_game_uuid)
                    WHERE request_type = 'update'
                      AND status NOT IN ('fulfilled', 'not_planned', 'cancelled');
            ELSE
                RAISE NOTICE 'Skipped active-update request uniqueness index because duplicates already exist';
            END IF;
        END $$;

        -- Add HowLongToBeat settings to global_settings table
        ALTER TABLE global_settings
        ADD COLUMN IF NOT EXISTS enable_hltb_integration BOOLEAN DEFAULT TRUE;

        ALTER TABLE global_settings
        ADD COLUMN IF NOT EXISTS hltb_rate_limit_delay FLOAT DEFAULT 2.0;

        -- Add Local Metadata & Image Override settings to global_settings table
        ALTER TABLE global_settings
        ADD COLUMN IF NOT EXISTS use_local_metadata BOOLEAN DEFAULT FALSE;

        ALTER TABLE global_settings
        ADD COLUMN IF NOT EXISTS write_local_metadata BOOLEAN DEFAULT FALSE;

        ALTER TABLE global_settings
        ADD COLUMN IF NOT EXISTS use_local_images BOOLEAN DEFAULT FALSE;

        ALTER TABLE global_settings
        ADD COLUMN IF NOT EXISTS local_metadata_filename VARCHAR(50) DEFAULT 'sharewarez.json';

        -- Remove unused library_name column from games table (replaced by library relationship via library_uuid)
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='games' AND column_name='library_name'
            ) THEN
                ALTER TABLE games DROP COLUMN library_name;
                RAISE NOTICE 'Dropped unused library_name column from games table';
            END IF;
        END $$;

        """
        print("Upgrading database to the latest schema")
        try:
            # Execute the SQL commands in a transaction
            with self.engine.begin() as connection:
                # Parse SQL into proper statements, respecting DO $$ ... END $$ blocks
                statements = self._parse_sql_statements(add_columns_sql)
                for statement in statements:
                    if statement.strip():
                        try:
                            connection.execute(text(statement))
                        except Exception as stmt_error:
                            print(f"Warning: Failed to execute statement: {statement[:100]}...")
                            print(f"Error: {stmt_error}")
                            # Continue with other statements instead of failing completely
                            continue

            # Clean up duplicate discovery sections
            self.cleanup_duplicate_discovery_sections()

            print("Database schema update completed successfully.")
        except Exception as e:
            print(f"An error occurred during schema update: {e}")
            # Don't raise the exception - let the application continue
            print("Application will continue with existing schema...")
        finally:
            # Close the database connection
            self.engine.dispose()

    def cleanup_duplicate_discovery_sections(self):
        """
        Clean up duplicate discovery sections created by conflicting initialization code.
        Removes outdated sections with wrong identifiers (latest, random, popular).
        """
        cleanup_sql = """
        -- Delete outdated discovery sections with wrong identifiers
        DELETE FROM discovery_sections
        WHERE identifier IN ('latest', 'random', 'popular');

        -- Log what was done
        DO $$
        DECLARE
            deleted_count INTEGER;
        BEGIN
            GET DIAGNOSTICS deleted_count = ROW_COUNT;
            IF deleted_count > 0 THEN
                RAISE NOTICE 'Removed % outdated discovery sections', deleted_count;
            END IF;
        END $$;
        """

        print("Cleaning up duplicate discovery sections...")
        try:
            with self.engine.begin() as connection:
                connection.execute(text(cleanup_sql))
                print("Discovery sections cleanup completed successfully.")
        except Exception as e:
            print(f"Warning: Discovery sections cleanup failed: {e}")
            print("Application will continue...")

    def _parse_sql_statements(self, sql_text):
        """
        Parse SQL text into individual statements, properly handling PostgreSQL 
        dollar-quoted blocks like DO $$ ... END $$;
        """
        statements = []
        current_statement = ""
        in_dollar_quote = False
        dollar_tag = ""
        
        lines = sql_text.split('\n')
        
        for line in lines:
            stripped_line = line.strip()
            
            # Skip empty lines and comments
            if not stripped_line or stripped_line.startswith('--'):
                current_statement += line + '\n'
                continue
                
            # Check for start of dollar-quoted block
            if not in_dollar_quote:
                # Look for DO $$ or DO $tag$
                if 'DO $' in stripped_line.upper():
                    # Extract the dollar tag (e.g., $$ or $tag$)
                    import re
                    match = re.search(r'DO\s+(\$[^$]*\$)', stripped_line.upper())
                    if match:
                        dollar_tag = match.group(1)
                        in_dollar_quote = True
                        
            current_statement += line + '\n'
            
            # Check for end of dollar-quoted block
            if in_dollar_quote:
                if dollar_tag in stripped_line and stripped_line.endswith(';'):
                    in_dollar_quote = False
                    dollar_tag = ""
                    # End of DO block, add as complete statement
                    statements.append(current_statement.strip())
                    current_statement = ""
            else:
                # Regular statement ending with semicolon
                if stripped_line.endswith(';'):
                    statements.append(current_statement.strip())
                    current_statement = ""
        
        # Add any remaining statement
        if current_statement.strip():
            statements.append(current_statement.strip())
            
        return [stmt for stmt in statements if stmt.strip()]

# Example of how to use the class
# db_manager = DatabaseManager()
# db_manager.add_column_if_not_exists()
