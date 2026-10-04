"""Initial immutable schema."""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "articles",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("source_id", sa.String(80), nullable=False),
        sa.Column("source_name", sa.String(200), nullable=False),
        sa.Column("topic", sa.String(32), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("published_at", sa.Integer(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("summary", sa.Text()),
        sa.Column("summary_version", sa.String(160)),
    )
    op.create_index("ix_articles_published_at", "articles", ["published_at"])
    op.create_table(
        "subscribers",
        sa.Column("chat_id", sa.Integer(), primary_key=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("topics", sa.Text(), nullable=False),
    )
    op.create_table(
        "digests",
        sa.Column("day", sa.String(10), primary_key=True),
        sa.Column("items", sa.Text(), nullable=False),
    )
    op.create_table(
        "deliveries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("day", sa.String(10), sa.ForeignKey("digests.day"), nullable=False),
        sa.Column("chat_id", sa.Integer(), sa.ForeignKey("subscribers.chat_id"), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt", sa.Integer(), nullable=False),
        sa.UniqueConstraint("day", "chat_id", name="uq_delivery_day_chat"),
    )
    op.create_index("ix_deliveries_state", "deliveries", ["state"])
    op.create_table(
        "jobs",
        sa.Column("name", sa.String(80), primary_key=True),
        sa.Column("last_attempt", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    raise RuntimeError("Destructive downgrade disabled; restore a verified backup explicitly")
