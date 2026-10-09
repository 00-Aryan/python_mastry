"""Immutable owned Python source receipts with acceptance-time evidence."""

from alembic import op

revision = "0006_immutable_submissions"
down_revision = "0005_progressive_assistance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE attempt_events DROP CONSTRAINT ck_attempt_event_type")
    op.execute("""
ALTER TABLE attempt_events ADD CONSTRAINT ck_attempt_event_type CHECK (event_type IN
('started','paused','resumed','extended','expired','deferred','abandoned',
 'assistance_granted','submission_received'))
""")
    op.execute("""
CREATE TABLE submissions (
    id UUID PRIMARY KEY,
    attempt_id UUID NOT NULL REFERENCES attempts(id) ON DELETE RESTRICT,
    question_version_id UUID NOT NULL REFERENCES question_versions(id) ON DELETE RESTRICT,
    policy_version_id UUID NOT NULL REFERENCES learning_policy_versions(id) ON DELETE RESTRICT,
    phase_id UUID NOT NULL REFERENCES attempt_phases(id) ON DELETE RESTRICT,
    source_code TEXT NOT NULL,
    code_hash VARCHAR(64) NOT NULL,
    source_bytes INTEGER NOT NULL,
    accepted_code_limit_bytes INTEGER NOT NULL,
    purpose VARCHAR(16) NOT NULL,
    accepted_at TIMESTAMPTZ NOT NULL,
    accepted_event_sequence INTEGER NOT NULL,
    attempt_revision INTEGER NOT NULL,
    evidence_json JSONB NOT NULL,
    request_key VARCHAR(128) NOT NULL,
    request_hash VARCHAR(64) NOT NULL,
    CONSTRAINT uq_submission_request UNIQUE (attempt_id, request_key),
    CONSTRAINT uq_submission_event UNIQUE (attempt_id, accepted_event_sequence),
    CONSTRAINT fk_submission_event FOREIGN KEY (attempt_id, accepted_event_sequence)
        REFERENCES attempt_events(attempt_id, sequence_number) ON DELETE RESTRICT,
    CONSTRAINT ck_submission_purpose CHECK (purpose IN ('public_run','assessment')),
    CONSTRAINT ck_submission_bytes CHECK (source_bytes > 0
        AND source_bytes <= accepted_code_limit_bytes AND source_bytes = octet_length(source_code)),
    CONSTRAINT ck_submission_hash CHECK (
        code_hash = encode(sha256(convert_to(source_code, 'UTF8')), 'hex')),
    CONSTRAINT ck_submission_counters CHECK (attempt_revision > 0 AND accepted_event_sequence > 0)
)
""")
    op.execute(
        "CREATE INDEX ix_submission_history ON submissions (attempt_id, accepted_event_sequence)"
    )
    op.execute("""
CREATE FUNCTION guard_submission_history() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE owned attempts%ROWTYPE; phase attempt_phases%ROWTYPE; grants JSONB;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'Submissions and acceptance evidence are immutable' USING ERRCODE = '23514';
    END IF;
    SELECT * INTO owned FROM attempts WHERE id = NEW.attempt_id FOR UPDATE;
    SELECT * INTO phase FROM attempt_phases WHERE id = NEW.phase_id;
    SELECT COALESCE(jsonb_agg(id ORDER BY granted_at, id), '[]'::jsonb) INTO grants
        FROM assistance_grants WHERE attempt_id = NEW.attempt_id;
    IF owned.id IS NULL OR phase.id IS NULL OR phase.attempt_id <> owned.id
       OR phase.phase_number IS DISTINCT FROM (SELECT max(phase_number)
            FROM attempt_phases WHERE attempt_id = owned.id)
       OR owned.lifecycle_state NOT IN ('active','paused')
       OR NEW.question_version_id <> owned.question_version_id
       OR NEW.policy_version_id <> owned.policy_version_id
       OR NEW.attempt_revision <> owned.revision
       OR NEW.accepted_event_sequence <> owned.last_event_sequence
       OR NEW.accepted_at <> owned.last_reconciled_at
       OR NEW.accepted_at < owned.started_at
       OR NOT EXISTS (SELECT 1 FROM attempt_events WHERE attempt_id = owned.id
                      AND sequence_number = NEW.accepted_event_sequence
                      AND event_type = 'submission_received' AND occurred_at = NEW.accepted_at
                      AND payload_json->>'submission_id' = NEW.id::text)
       OR (NEW.evidence_json->>'phase_id') IS DISTINCT FROM NEW.phase_id::text
       OR (NEW.evidence_json->'assistance_grant_ids') IS DISTINCT FROM grants
       OR NOT COALESCE((NEW.evidence_json->'attempt') @> jsonb_build_object(
            'id', owned.id, 'question_version_id', owned.question_version_id,
            'policy_version_id', owned.policy_version_id, 'mode', owned.mode,
            'lifecycle_state', owned.lifecycle_state, 'revision', owned.revision,
            'assistance_level', owned.assistance_level,
            'timing_accommodated', owned.timing_accommodated,
            'family_previously_attempted', owned.family_previously_attempted,
            'total_active_elapsed_ms', owned.total_active_elapsed_ms,
            'overdue_active_elapsed_ms', greatest(0, owned.total_active_elapsed_ms
                - owned.prior_phase_elapsed_ms - phase.active_elapsed_ms)), FALSE)
       OR NOT COALESCE((NEW.evidence_json->'attempt'->'timer') @> jsonb_build_object(
            'phase_number', phase.phase_number, 'budget_seconds', phase.budget_seconds,
            'active_elapsed_ms', phase.active_elapsed_ms,
            'remaining_ms', phase.budget_seconds::bigint * 1000 - phase.active_elapsed_ms), FALSE)
       OR (NEW.evidence_json->'attempt'->>'independent_end_reason')
            IS DISTINCT FROM owned.independent_end_reason
       OR (NEW.evidence_json->'attempt'->>'independent_interval_ended_at')::timestamptz
            IS DISTINCT FROM owned.independent_interval_ended_at
       OR (NEW.evidence_json->'attempt'->'timer'->>'expired_at')::timestamptz
            IS DISTINCT FROM phase.expired_at
       OR (NEW.evidence_json->'attempt'->'timer'->>'server_now')::timestamptz
            IS DISTINCT FROM NEW.accepted_at THEN
        RAISE EXCEPTION 'Submission must match owned pinned acceptance state'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END $$
""")
    op.execute("""
CREATE TRIGGER immutable_submission_history BEFORE INSERT OR UPDATE OR DELETE ON submissions
FOR EACH ROW EXECUTE FUNCTION guard_submission_history()
""")


def downgrade() -> None:
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM submissions) THEN
            RAISE EXCEPTION 'Cannot downgrade stored submission history' USING ERRCODE = '23514';
        END IF;
    END $$""")
    op.drop_table("submissions")
    op.execute("DROP FUNCTION guard_submission_history()")
    op.execute("ALTER TABLE attempt_events DROP CONSTRAINT ck_attempt_event_type")
    op.execute("""
ALTER TABLE attempt_events ADD CONSTRAINT ck_attempt_event_type CHECK (event_type IN
('started','paused','resumed','extended','expired','deferred','abandoned','assistance_granted'))
""")
