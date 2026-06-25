"""题目资产对象引用

Revision ID: 0003_challenge_artifacts
Revises: 0002_local_auth
Create Date: 2026-06-25
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0003_challenge_artifacts"
down_revision = "0002_local_auth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "challenge_artifacts",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("challenge_id", sa.String(64), sa.ForeignKey("challenges.id"), nullable=False),
        sa.Column(
            "version_id",
            sa.String(64),
            sa.ForeignKey("challenge_versions.id"),
            nullable=True,
        ),
        sa.Column("artifact_type", sa.String(80), nullable=False),
        sa.Column("object_ref", sa.String(500), nullable=False),
        sa.Column("sha256", sa.String(128), nullable=False),
        sa.Column("byte_count", sa.Integer(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("challenge_artifacts")
