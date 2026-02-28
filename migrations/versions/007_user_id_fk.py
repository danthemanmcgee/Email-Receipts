"""Add user_id FK to receipts and physical_cards for per-user data isolation.

Revision ID: 007_user_id_fk
Revises: 006_users
Create Date: 2026-02-28
"""
from alembic import op
import sqlalchemy as sa

revision = "007_user_id_fk"
down_revision = "006_users"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "receipts",
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
    )
    op.create_index("ix_receipts_user_id", "receipts", ["user_id"])

    op.add_column(
        "physical_cards",
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
    )
    op.create_index("ix_physical_cards_user_id", "physical_cards", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_physical_cards_user_id", table_name="physical_cards")
    op.drop_column("physical_cards", "user_id")

    op.drop_index("ix_receipts_user_id", table_name="receipts")
    op.drop_column("receipts", "user_id")
