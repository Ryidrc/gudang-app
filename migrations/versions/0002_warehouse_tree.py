"""warehouse tree + stocks

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-20
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gudangs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_gudangs_name", "gudangs", ["name"], unique=True)

    op.create_table(
        "areas",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("gudang_id", sa.Integer(), sa.ForeignKey("gudangs.id"), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("layout", sa.String(10), nullable=False, server_default="vertical"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("gudang_id", "name", name="uq_areas_gudang_name"),
    )
    op.create_index("ix_areas_gudang_id", "areas", ["gudang_id"])

    op.create_table(
        "raks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("area_id", sa.Integer(), sa.ForeignKey("areas.id"), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("area_id", "name", name="uq_raks_area_name"),
    )
    op.create_index("ix_raks_area_id", "raks", ["area_id"])

    op.create_table(
        "skus",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_skus_code", "skus", ["code"], unique=True)
    op.create_index("ix_skus_name", "skus", ["name"])

    op.create_table(
        "stocks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("rak_id", sa.Integer(), sa.ForeignKey("raks.id"), nullable=False),
        sa.Column("sku_id", sa.Integer(), sa.ForeignKey("skus.id"), nullable=False),
        sa.Column("qty_boxes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("rak_id", "sku_id", name="uq_stocks_rak_sku"),
    )
    op.create_index("ix_stocks_rak_id", "stocks", ["rak_id"])
    op.create_index("ix_stocks_sku_id", "stocks", ["sku_id"])


def downgrade() -> None:
    op.drop_table("stocks")
    op.drop_table("skus")
    op.drop_table("raks")
    op.drop_table("areas")
    op.drop_table("gudangs")
