"""settings table

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-20
"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table(
        "settings",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
    )
    # Seed defaults
    op.execute("INSERT INTO settings (key, value) VALUES ('qr_base_url', 'http://localhost:8000')")
    op.execute("INSERT INTO settings (key, value) VALUES ('backup_keep_days', '7')")
    op.execute("INSERT INTO settings (key, value) VALUES ('backup_time', '17:10')")
    op.execute("INSERT INTO settings (key, value) VALUES ('backup_last_at', '')")

def downgrade() -> None:
    op.drop_table("settings")
