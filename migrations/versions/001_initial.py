"""initial

Revision ID: 001
Revises:
Create Date: 2024-01-01 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "physical_cards",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("last4", sa.String(10), nullable=True),
        sa.Column("network", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("display_name"),
    )

    op.create_table(
        "card_aliases",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("physical_card_id", sa.Integer(), nullable=False),
        sa.Column("alias_last4", sa.String(10), nullable=False),
        sa.Column("alias_pattern", sa.String(100), nullable=True),
        sa.Column("notes", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["physical_card_id"], ["physical_cards.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "receipts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("gmail_message_id", sa.String(255), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="new"),
        sa.Column("subject", sa.String(500), nullable=True),
        sa.Column("sender", sa.String(255), nullable=True),
        sa.Column("received_at", sa.DateTime(), nullable=True),
        sa.Column("merchant", sa.String(255), nullable=True),
        sa.Column("purchase_date", sa.Date(), nullable=True),
        sa.Column("amount", sa.Float(), nullable=True),
        sa.Column("currency", sa.String(10), nullable=True, server_default="USD"),
        sa.Column("card_last4_seen", sa.String(10), nullable=True),
        sa.Column("card_network_or_issuer", sa.String(50), nullable=True),
        sa.Column("source_type", sa.String(50), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("extraction_notes", sa.Text(), nullable=True),
        sa.Column("physical_card_id", sa.Integer(), nullable=True),
        sa.Column("drive_file_id", sa.String(255), nullable=True),
        sa.Column("drive_path", sa.String(1000), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["physical_card_id"], ["physical_cards.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("gmail_message_id"),
    )
    op.create_index("ix_receipts_gmail_message_id", "receipts", ["gmail_message_id"])

    op.create_table(
        "attachment_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("receipt_id", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(500), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("decision", sa.String(50), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["receipt_id"], ["receipts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("attachment_logs")
    op.drop_index("ix_receipts_gmail_message_id", "receipts")
    op.drop_table("receipts")
    op.drop_table("card_aliases")
    op.drop_table("physical_cards")
