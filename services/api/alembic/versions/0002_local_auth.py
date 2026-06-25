"""本地账号注册登录字段

Revision ID: 0002_local_auth
Revises: 0001_core
Create Date: 2026-06-25
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0002_local_auth"
down_revision = "0001_core"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("password_hash", sa.String(300), nullable=True))
        batch.add_column(sa.Column("created_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("last_login_at")
        batch.drop_column("created_at")
        batch.drop_column("password_hash")
