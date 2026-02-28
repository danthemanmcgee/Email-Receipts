"""Alembic migration: card_statements and statement_lines tables.

Revision ID: 010_card_statements
Revises: 009_drive_authoritative
Create Date: 2026-02-28
"""
from alembic import op
import sqlalchemy as sa

revision = "010_card_statements"
down_revision = "009_drive_authoritative"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "card_statements",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("card_id", sa.Integer(), sa.ForeignKey("physical_cards.id"), nullable=False),
        sa.Column("filename", sa.String(500), nullable=False),
        sa.Column("format", sa.String(10), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("imported_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_card_statements_user_id", "card_statements", ["user_id"])
    op.create_index("ix_card_statements_card_id", "card_statements", ["card_id"])

    op.create_table(
        "statement_lines",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "statement_id",
            sa.Integer(),
            sa.ForeignKey("card_statements.id"),
            nullable=False,
        ),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "card_id", sa.Integer(), sa.ForeignKey("physical_cards.id"), nullable=False
        ),
        sa.Column("txn_date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("merchant", sa.String(500), nullable=True),
        sa.Column("transaction_id", sa.String(255), nullable=True),
        sa.Column("currency", sa.String(10), nullable=False, server_default="USD"),
        sa.Column("raw_data", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_statement_lines_statement_id", "statement_lines", ["statement_id"])
    op.create_index("ix_statement_lines_user_id", "statement_lines", ["user_id"])
    op.create_index("ix_statement_lines_card_id", "statement_lines", ["card_id"])


def downgrade() -> None:
    op.drop_index("ix_statement_lines_card_id", table_name="statement_lines")
    op.drop_index("ix_statement_lines_user_id", table_name="statement_lines")
    op.drop_index("ix_statement_lines_statement_id", table_name="statement_lines")
    op.drop_table("statement_lines")
    op.drop_index("ix_card_statements_card_id", table_name="card_statements")
    op.drop_index("ix_card_statements_user_id", table_name="card_statements")
    op.drop_table("card_statements")
