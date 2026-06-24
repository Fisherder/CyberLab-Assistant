"""核心控制平面 schema

Revision ID: 0001_core
Revises:
Create Date: 2026-06-24
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0001_core"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("slug", sa.String(80), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("settings_json", sa.JSON(), nullable=False),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("oidc_subject", sa.String(200), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.UniqueConstraint("tenant_id", "oidc_subject"),
    )
    op.create_table(
        "courses",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("term", sa.String(80), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("owner_id", sa.String(64), sa.ForeignKey("users.id"), nullable=False),
        sa.UniqueConstraint("tenant_id", "code", "term"),
    )
    op.create_table(
        "course_members",
        sa.Column("course_id", sa.String(64), sa.ForeignKey("courses.id"), primary_key=True),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "challenges",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("slug", sa.String(120), nullable=False),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("owner_id", sa.String(64), sa.ForeignKey("users.id"), nullable=False),
        sa.UniqueConstraint("tenant_id", "slug"),
    )
    op.create_table(
        "challenge_versions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("challenge_id", sa.String(64), sa.ForeignKey("challenges.id"), nullable=False),
        sa.Column("semver", sa.String(40), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("manifest_json", sa.JSON(), nullable=False),
        sa.Column("artifact_digest", sa.String(160), nullable=False),
        sa.Column("risk_tier", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(64), sa.ForeignKey("users.id"), nullable=False),
        sa.UniqueConstraint("challenge_id", "semver"),
    )
    op.create_table(
        "validation_runs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("version_id", sa.String(64), sa.ForeignKey("challenge_versions.id"), nullable=False),
        sa.Column("workflow_id", sa.String(200), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("report_ref", sa.String(300), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "challenge_drafts",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("course_id", sa.String(64), sa.ForeignKey("courses.id"), nullable=False),
        sa.Column("brief_text", sa.Text(), nullable=False),
        sa.Column("constraints_json", sa.JSON(), nullable=False),
        sa.Column("intent_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(64), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "selected_version_id",
            sa.String(64),
            sa.ForeignKey("challenge_versions.id"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "assignments",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("course_id", sa.String(64), sa.ForeignKey("courses.id"), nullable=False),
        sa.Column(
            "challenge_version_id",
            sa.String(64),
            sa.ForeignKey("challenge_versions.id"),
            nullable=False,
        ),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("open_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_policy_json", sa.JSON(), nullable=False),
    )
    op.create_table(
        "attempts",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("assignment_id", sa.String(64), sa.ForeignKey("assignments.id"), nullable=False),
        sa.Column("student_id", sa.String(64), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("seed_hex", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("assignment_id", "student_id", "number"),
    )
    op.create_table(
        "lab_sessions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("attempt_id", sa.String(64), sa.ForeignKey("attempts.id"), nullable=False),
        sa.Column("epoch", sa.Integer(), nullable=False),
        sa.Column("workspace_type", sa.String(32), nullable=False),
        sa.Column("runtime_tier", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("route_ref", sa.String(120), nullable=False),
        sa.Column("route_endpoint", sa.String(240), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("workflow_id", sa.String(200), nullable=False),
        sa.UniqueConstraint("attempt_id", "epoch"),
    )
    op.create_table(
        "event_streams",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("attempt_id", sa.String(64), sa.ForeignKey("attempts.id"), nullable=False),
        sa.Column("session_epoch", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(120), nullable=False),
        sa.Column("last_sequence", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.UniqueConstraint("attempt_id", "session_epoch", "source"),
    )
    op.create_table(
        "events",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("attempt_id", sa.String(64), sa.ForeignKey("attempts.id"), nullable=False),
        sa.Column("session_epoch", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(120), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(160), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("trace_id", sa.String(120), nullable=True),
        sa.Column("previous_hash", sa.String(128), nullable=True),
        sa.Column("hash", sa.String(128), nullable=False),
        sa.UniqueConstraint("attempt_id", "session_epoch", "source", "sequence"),
    )
    op.create_table(
        "transcript_segments",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("attempt_id", sa.String(64), sa.ForeignKey("attempts.id"), nullable=False),
        sa.Column("epoch", sa.Integer(), nullable=False),
        sa.Column("direction", sa.String(16), nullable=False),
        sa.Column("seq_from", sa.Integer(), nullable=False),
        sa.Column("seq_to", sa.Integer(), nullable=False),
        sa.Column("object_ref", sa.String(300), nullable=False),
        sa.Column("sha256", sa.String(128), nullable=False),
        sa.Column("redaction_state", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "hints",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("attempt_id", sa.String(64), sa.ForeignKey("attempts.id"), nullable=False),
        sa.Column("level", sa.String(16), nullable=False),
        sa.Column("trigger_type", sa.String(80), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("tutor_version", sa.String(80), nullable=False),
        sa.Column("shown_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
    )
    op.create_table(
        "stuck_assessments",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("attempt_id", sa.String(64), sa.ForeignKey("attempts.id"), nullable=False),
        sa.Column("window_from", sa.Integer(), nullable=False),
        sa.Column("window_to", sa.Integer(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("features_json", sa.JSON(), nullable=False),
        sa.Column("detector_version", sa.String(80), nullable=False),
        sa.Column("decision", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "terminal_ticket_nonces",
        sa.Column("nonce", sa.String(160), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("attempt_id", sa.String(64), sa.ForeignKey("attempts.id"), nullable=False),
        sa.Column("session_id", sa.String(64), sa.ForeignKey("lab_sessions.id"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "grade_revisions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("attempt_id", sa.String(64), sa.ForeignKey("attempts.id"), nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("total_score", sa.Float(), nullable=False),
        sa.Column("independence_index", sa.Float(), nullable=False),
        sa.Column("rubric_version", sa.String(80), nullable=False),
        sa.Column("grader_version", sa.String(80), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("attempt_id", "revision_no"),
    )
    op.create_table(
        "criterion_results",
        sa.Column("grade_revision_id", sa.String(64), sa.ForeignKey("grade_revisions.id"), primary_key=True),
        sa.Column("criterion_id", sa.String(120), primary_key=True),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("max_score", sa.Float(), nullable=False),
        sa.Column("grader_type", sa.String(80), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
    )
    op.create_table(
        "appeals",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("grade_revision_id", sa.String(64), sa.ForeignKey("grade_revisions.id"), nullable=False),
        sa.Column("criterion_id", sa.String(120), nullable=False),
        sa.Column("student_id", sa.String(64), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("resolution", sa.Text(), nullable=True),
        sa.Column("resolved_by", sa.String(64), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("purpose", sa.String(80), nullable=False),
        sa.Column("prompt_version", sa.String(80), nullable=False),
        sa.Column("model_policy", sa.String(80), nullable=False),
        sa.Column("input_ref", sa.String(240), nullable=True),
        sa.Column("output_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("usage_json", sa.JSON(), nullable=False),
        sa.Column("trace_id", sa.String(120), nullable=True),
    )
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("actor", sa.String(120), nullable=False),
        sa.Column("action", sa.String(160), nullable=False),
        sa.Column("resource_type", sa.String(120), nullable=False),
        sa.Column("resource_id", sa.String(120), nullable=False),
        sa.Column("decision", sa.String(32), nullable=False),
        sa.Column("before_ref", sa.String(240), nullable=True),
        sa.Column("after_ref", sa.String(240), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "outbox_events",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("aggregate_type", sa.String(120), nullable=False),
        sa.Column("aggregate_id", sa.String(120), nullable=False),
        sa.Column("event_type", sa.String(160), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
    )
    op.create_table(
        "idempotency_records",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("actor_id", sa.String(64), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("route", sa.String(240), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("response_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("tenant_id", "actor_id", "route", "idempotency_key"),
    )


def downgrade() -> None:
    for table in [
        "idempotency_records",
        "outbox_events",
        "audit_logs",
        "agent_runs",
        "appeals",
        "criterion_results",
        "grade_revisions",
        "terminal_ticket_nonces",
        "stuck_assessments",
        "hints",
        "transcript_segments",
        "events",
        "event_streams",
        "lab_sessions",
        "attempts",
        "assignments",
        "challenge_drafts",
        "validation_runs",
        "challenge_versions",
        "challenges",
        "course_members",
        "courses",
        "users",
        "tenants",
    ]:
        op.drop_table(table)
