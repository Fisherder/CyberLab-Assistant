"""题库条目生命周期

Revision ID: 0004_challenge_bank_items
Revises: 0003_challenge_artifacts
Create Date: 2026-06-25
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0004_challenge_bank_items"
down_revision = "0003_challenge_artifacts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "challenge_bank_items",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("course_id", sa.String(64), sa.ForeignKey("courses.id"), nullable=False),
        sa.Column(
            "challenge_version_id",
            sa.String(64),
            sa.ForeignKey("challenge_versions.id"),
            nullable=False,
        ),
        sa.Column("assignment_id", sa.String(64), sa.ForeignKey("assignments.id"), nullable=True),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("requirements", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("tags_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(64), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("open_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("unpublished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("restored_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("assignment_id"),
    )


def downgrade() -> None:
    op.drop_table("challenge_bank_items")
