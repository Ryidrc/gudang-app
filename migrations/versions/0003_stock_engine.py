"""stock engine

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-20
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table(
        "stock_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("type", sa.String(10), nullable=False),
        sa.Column("sku_id", sa.Integer(), sa.ForeignKey("skus.id"), nullable=False),
        sa.Column("from_rak_id", sa.Integer(), sa.ForeignKey("raks.id"), nullable=True),
        sa.Column("to_rak_id", sa.Integer(), sa.ForeignKey("raks.id"), nullable=True),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(255), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("requested_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reviewed_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("review_note", sa.String(255), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_stock_requests_type", "stock_requests", ["type"])
    op.create_index("ix_stock_requests_sku_id", "stock_requests", ["sku_id"])
    op.create_index("ix_stock_requests_status", "stock_requests", ["status"])
    op.create_index("ix_stock_requests_requested_by", "stock_requests", ["requested_by"])

    op.create_table(
        "stock_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("type", sa.String(10), nullable=False),
        sa.Column("sku_id", sa.Integer(), sa.ForeignKey("skus.id"), nullable=False),
        sa.Column("from_rak_id", sa.Integer(), sa.ForeignKey("raks.id"), nullable=True),
        sa.Column("to_rak_id", sa.Integer(), sa.ForeignKey("raks.id"), nullable=True),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(255), nullable=True),
        sa.Column("request_id", sa.Integer(), sa.ForeignKey("stock_requests.id"), nullable=True),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_stock_events_type", "stock_events", ["type"])
    op.create_index("ix_stock_events_sku_id", "stock_events", ["sku_id"])

def downgrade() -> None:
    op.drop_table("stock_events")
    op.drop_table("stock_requests")
