"""Signal committed download changes across web and job processes.

Revision ID: 20260904_24
Revises: 20260902_23
"""

from alembic import op

revision = "20260904_24"
down_revision = "20260902_23"
branch_labels = None
depends_on = None

TABLE_TOPICS = {
    "download_transfers": "transfers",
    "download_requests": "downloads",
    "download_archives": "archives",
    "background_jobs": "archives",
}


def upgrade():
    op.execute("""
        CREATE FUNCTION sharewarez_signal_download_change() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'UPDATE' AND NEW IS NOT DISTINCT FROM OLD THEN
                RETURN NULL;
            END IF;
            IF TG_TABLE_NAME = 'background_jobs' THEN
                IF TG_OP = 'DELETE' THEN
                    IF OLD.task_name <> 'download.archive.build' THEN RETURN NULL; END IF;
                ELSE
                    IF NEW.task_name <> 'download.archive.build' THEN RETURN NULL; END IF;
                END IF;
            END IF;
            PERFORM pg_notify('sharewarez_download_events', TG_ARGV[0]);
            RETURN NULL;
        END;
        $$
    """)
    for table, topic in TABLE_TOPICS.items():
        op.execute(f"""
            CREATE TRIGGER live_download_change AFTER INSERT OR UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION sharewarez_signal_download_change('{topic}')
        """)


def downgrade():
    for table in TABLE_TOPICS:
        op.execute(f"DROP TRIGGER live_download_change ON {table}")
    op.execute("DROP FUNCTION sharewarez_signal_download_change()")
