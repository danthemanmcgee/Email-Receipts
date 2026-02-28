"""Add user_id to google_connections, job_runs, allowed_senders; restructure app_settings.

Revision ID: 008_user_id_isolation
Revises: 007_user_id_fk
Create Date: 2026-02-28
"""
from alembic import op
import sqlalchemy as sa

revision = "008_user_id_isolation"
down_revision = "007_user_id_fk"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- google_connections: add user_id, replace unique constraint ---
    op.add_column(
        "google_connections",
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
    )
    op.create_index("ix_google_connections_user_id", "google_connections", ["user_id"])
    op.drop_constraint("uq_google_connections_type", "google_connections", type_="unique")
    op.create_unique_constraint(
        "uq_google_connections_user_type",
        "google_connections",
        ["user_id", "connection_type"],
    )

    # --- job_runs: add user_id ---
    op.add_column(
        "job_runs",
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
    )
    op.create_index("ix_job_runs_user_id", "job_runs", ["user_id"])

    # --- allowed_senders: add user_id, replace unique constraint ---
    op.add_column(
        "allowed_senders",
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
    )
    op.create_index("ix_allowed_senders_user_id", "allowed_senders", ["user_id"])
    op.drop_constraint("uq_allowed_senders_email", "allowed_senders", type_="unique")
    op.create_unique_constraint(
        "uq_allowed_senders_user_email",
        "allowed_senders",
        ["user_id", "email"],
    )

    # --- app_settings: restructure with id PK and user_id ---
    # Create new table with desired schema
    op.create_table(
        "app_settings_new",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("key", sa.String(100), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "key", name="uq_app_settings_user_key"),
    )
    op.create_index("ix_app_settings_user_id", "app_settings_new", ["user_id"])

    # Migrate existing data (user_id will be NULL for legacy rows)
    op.execute(
        "INSERT INTO app_settings_new (user_id, key, value, updated_at) "
        "SELECT NULL, key, value, updated_at FROM app_settings"
    )

    op.drop_table("app_settings")
    op.rename_table("app_settings_new", "app_settings")


def downgrade() -> None:
    # --- app_settings: revert to key-as-PK schema ---
    op.create_table(
        "app_settings_old",
        sa.Column("key", sa.String(100), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("key"),
    )
    op.execute(
        "INSERT INTO app_settings_old (key, value, updated_at) "
        "SELECT key, value, updated_at FROM app_settings WHERE user_id IS NULL"
    )
    op.drop_table("app_settings")
    op.rename_table("app_settings_old", "app_settings")

    # --- allowed_senders: revert ---
    op.drop_constraint("uq_allowed_senders_user_email", "allowed_senders", type_="unique")
    op.drop_index("ix_allowed_senders_user_id", table_name="allowed_senders")
    op.drop_column("allowed_senders", "user_id")
    op.create_unique_constraint("uq_allowed_senders_email", "allowed_senders", ["email"])

    # --- job_runs: revert ---
    op.drop_index("ix_job_runs_user_id", table_name="job_runs")
    op.drop_column("job_runs", "user_id")

    # --- google_connections: revert ---
    op.drop_constraint("uq_google_connections_user_type", "google_connections", type_="unique")
    op.drop_index("ix_google_connections_user_id", table_name="google_connections")
    op.drop_column("google_connections", "user_id")
    op.create_unique_constraint(
        "uq_google_connections_type", "google_connections", ["connection_type"]
    )
