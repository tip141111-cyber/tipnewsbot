"""Persist Gemini request limits and reported usage across restarts."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "inference_usage",
        sa.Column("day", sa.String(10), primary_key=True),
        sa.Column("requests", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    raise RuntimeError("Destructive downgrade disabled; keep additive table on image rollback")
