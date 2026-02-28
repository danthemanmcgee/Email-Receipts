"""Drive-authoritative receipt storage: deduplicate by content_hash.

Adds a unique constraint on (user_id, content_hash) in the receipts table
so that identical documents are stored only once per user.  Also creates the
gmail_receipt_links table that maps every Gmail message ID to its canonical
Receipt, enabling multiple forwarded or duplicate emails to reference the same
Drive file without re-uploading.

Revision ID: 009_drive_authoritative
Revises: 008_user_id_isolation
Create Date: 2026-02-28
"""
from alembic import op
import sqlalchemy as sa

revision = "009_drive_authoritative"
down_revision = "008_user_id_isolation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Unique constraint on (user_id, content_hash) in receipts.
    # NULL values are never considered equal in PostgreSQL/SQLite unique
    # constraints, so receipts without a content_hash are unaffected.
    op.create_unique_constraint(
        "uq_receipt_user_content_hash",
        "receipts",
        ["user_id", "content_hash"],
    )
    # Index on content_hash alone for fast single-column lookups during
    # deduplication checks (the unique constraint covers the composite case).
    op.create_index("ix_receipts_content_hash", "receipts", ["content_hash"])

    # Table that links every Gmail message to its canonical Receipt.
    op.create_table(
        "gmail_receipt_links",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column(
            "receipt_id",
            sa.Integer(),
            sa.ForeignKey("receipts.id"),
            nullable=False,
        ),
        sa.Column("gmail_message_id", sa.String(255), nullable=False),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "gmail_message_id", name="uq_gmail_receipt_links_message_id"
        ),
    )
    op.create_index(
        "ix_gmail_receipt_links_receipt_id",
        "gmail_receipt_links",
        ["receipt_id"],
    )
    op.create_index(
        "ix_gmail_receipt_links_user_id",
        "gmail_receipt_links",
        ["user_id"],
    )
    op.create_index(
        "ix_gmail_receipt_links_gmail_message_id",
        "gmail_receipt_links",
        ["gmail_message_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_gmail_receipt_links_gmail_message_id",
        table_name="gmail_receipt_links",
    )
    op.drop_index(
        "ix_gmail_receipt_links_user_id", table_name="gmail_receipt_links"
    )
    op.drop_index(
        "ix_gmail_receipt_links_receipt_id", table_name="gmail_receipt_links"
    )
    op.drop_table("gmail_receipt_links")
    op.drop_index("ix_receipts_content_hash", table_name="receipts")
    op.drop_constraint("uq_receipt_user_content_hash", "receipts", type_="unique")
