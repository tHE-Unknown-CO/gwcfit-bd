"""Publish committed notification and platform event changes across workers."""
from alembic import op

revision = "0013_live_notifications"
down_revision = "0012_platform_notifications"
branch_labels = None
depends_on = None

SOURCES = ("gym_inquiries", "gyms", "subscriptions", "invitations", "login_events")


def upgrade():
    op.execute("""
        CREATE FUNCTION pulsefit_notification_changed() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                PERFORM pg_notify('pulsefit_notifications', OLD.user_id::text);
            ELSE
                PERFORM pg_notify('pulsefit_notifications', NEW.user_id::text);
            END IF;
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER pulsefit_notification_changed
        AFTER INSERT OR DELETE OR UPDATE OF read_at, is_active ON notifications
        FOR EACH ROW EXECUTE FUNCTION pulsefit_notification_changed();
        CREATE FUNCTION pulsefit_platform_changed() RETURNS trigger AS $$
        BEGIN
            PERFORM pg_notify('pulsefit_platform_events', 'sync');
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;
    """)
    for table in SOURCES:
        op.execute(f"CREATE TRIGGER pulsefit_platform_changed AFTER INSERT OR UPDATE OR DELETE ON {table} "
                   "FOR EACH STATEMENT EXECUTE FUNCTION pulsefit_platform_changed()")


def downgrade():
    for table in SOURCES:
        op.execute(f"DROP TRIGGER IF EXISTS pulsefit_platform_changed ON {table}")
    op.execute("DROP FUNCTION IF EXISTS pulsefit_platform_changed()")
    op.execute("DROP TRIGGER IF EXISTS pulsefit_notification_changed ON notifications")
    op.execute("DROP FUNCTION IF EXISTS pulsefit_notification_changed()")
