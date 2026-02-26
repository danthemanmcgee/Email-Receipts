"""add google_connections table

Revision ID: 002
Revises: 001
Create Date: 2024-01-02 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "google_connections",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("connection_type", sa.String(20), nullable=False),
        sa.Column("google_account_email", sa.String(255), nullable=True),
        sa.Column("access_token", sa.Text(), nullable=True),
        sa.Column("refresh_token", sa.Text(), nullable=True),
        sa.Column("token_expiry", sa.DateTime(), nullable=True),
        sa.Column("scopes", sa.String(500), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("connected_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("connection_type", name="uq_google_connections_type"),
    )


def downgrade() -> None:
    op.drop_table("google_connections")
