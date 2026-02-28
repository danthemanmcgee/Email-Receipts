"""Alembic migration: reconciliation support.

Adds match_status to statement_lines and creates statement_line_matches table.

Revision ID: 011_reconciliation
Revises: 010_card_statements
Create Date: 2026-02-28
"""
from alembic import op
import sqlalchemy as sa

revision = "011_reconciliation"
down_revision = "010_card_statements"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "statement_lines",
        sa.Column(
            "match_status",
            sa.String(20),
            nullable=False,
            server_default="unmatched",
        ),
    )

    op.create_table(
        "statement_line_matches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "statement_line_id",
            sa.Integer(),
            sa.ForeignKey("statement_lines.id"),
            nullable=False,
        ),
        sa.Column(
            "receipt_id",
            sa.Integer(),
            sa.ForeignKey("receipts.id"),
            nullable=False,
        ),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("statement_line_id", name="uq_statement_line_match"),
    )
    op.create_index(
        "ix_statement_line_matches_line_id",
        "statement_line_matches",
        ["statement_line_id"],
    )
    op.create_index(
        "ix_statement_line_matches_receipt_id",
        "statement_line_matches",
        ["receipt_id"],
    )
    op.create_index(
        "ix_statement_line_matches_user_id",
        "statement_line_matches",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_statement_line_matches_user_id", table_name="statement_line_matches")
    op.drop_index("ix_statement_line_matches_receipt_id", table_name="statement_line_matches")
    op.drop_index("ix_statement_line_matches_line_id", table_name="statement_line_matches")
    op.drop_table("statement_line_matches")
    op.drop_column("statement_lines", "match_status")
