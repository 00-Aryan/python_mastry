"""Append-only assistance grants and server-owned waiting phases."""

from alembic import op

revision = "0005_progressive_assistance"
down_revision = "0004_attempt_timers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE attempts ALTER COLUMN independent_end_reason TYPE VARCHAR(32)")
    op.execute("ALTER TABLE attempts ADD COLUMN prior_phase_elapsed_ms BIGINT NOT NULL DEFAULT 0")
    op.execute(
        """
ALTER TABLE attempts ADD CONSTRAINT ck_attempt_prior_elapsed CHECK (prior_phase_elapsed_ms
>= 0 AND prior_phase_elapsed_ms <= total_active_elapsed_ms)
        """
    )
    op.execute("ALTER TABLE attempts DROP CONSTRAINT ck_attempt_assistance")
    op.execute(
        """
ALTER TABLE attempts ADD CONSTRAINT ck_attempt_assistance CHECK (assistance_level IN
('none','directional','pattern','pseudocode','partial_code','full_solution'))
        """
    )
    op.execute("ALTER TABLE attempts DROP CONSTRAINT ck_attempt_independent_end")
    op.execute("""ALTER TABLE attempts ADD CONSTRAINT ck_attempt_independent_end CHECK (
        (independent_interval_ended_at IS NULL AND independent_end_reason IS NULL) OR
        (independent_interval_ended_at IS NOT NULL AND independent_end_reason IS NOT NULL
        AND independent_end_reason IN
        ('expired','deferred','abandoned','assistance_requested')))""")
    op.execute("ALTER TABLE attempt_phases DROP CONSTRAINT ck_phase_kind")
    op.execute(
        """
ALTER TABLE attempt_phases ADD CONSTRAINT ck_phase_kind CHECK ((phase_number = 0 AND kind
= 'independent') OR (phase_number > 0 AND kind = 'assistance'))
        """
    )
    op.execute("ALTER TABLE attempt_events DROP CONSTRAINT ck_attempt_event_type")
    op.execute(
        """
ALTER TABLE attempt_events ADD CONSTRAINT ck_attempt_event_type CHECK (event_type IN
('started','paused','resumed','extended','expired','deferred','abandoned','assistance_granted'))
        """
    )
    op.execute("""
CREATE TABLE assistance_grants (
    id UUID PRIMARY KEY,
    attempt_id UUID NOT NULL REFERENCES attempts(id) ON DELETE RESTRICT,
    step_id UUID NOT NULL REFERENCES question_assistance_steps(id) ON DELETE RESTRICT,
    granted_at TIMESTAMPTZ NOT NULL,
    reason VARCHAR(32) NOT NULL,
    command_id UUID NOT NULL,
    operation VARCHAR(16) NOT NULL,
    request_key VARCHAR(128) NOT NULL,
    request_hash VARCHAR(64) NOT NULL,
    response_json JSONB NOT NULL,
    CONSTRAINT uq_assistance_grant_step UNIQUE (attempt_id, step_id),
    CONSTRAINT uq_assistance_grant_request UNIQUE (attempt_id, operation, request_key),
    CONSTRAINT ck_assistance_operation CHECK (operation IN ('next','solution')),
    CONSTRAINT ck_assistance_reason CHECK (reason IN
('budget_expired','learner_request','solution_escape'))
)
""")
    op.execute("""
INSERT INTO learning_policy_versions (id, version_code, configuration_json, effective_at)
VALUES ('00000000-0000-0000-0000-000000000101', 'pilot-assistance-1',
'{"minimum_budget_seconds": 60,"maximum_budget_seconds": 3600,
"maximum_extension_seconds": 1800,"allowed_modes":["practice","assessment"],
"assistance":{"minimum_wait_seconds": 60,"maximum_wait_seconds": 86400}}',
'2026-10-10T00:00:00Z')
""")
    op.execute("""
CREATE FUNCTION guard_assistance_projection() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE levels TEXT[] := ARRAY['none','directional','pattern','pseudocode',
                              'partial_code','full_solution'];
BEGIN
    IF array_position(levels, NEW.assistance_level)
       < array_position(levels, OLD.assistance_level)
       OR NEW.prior_phase_elapsed_ms < OLD.prior_phase_elapsed_ms THEN
        RAISE EXCEPTION 'Assistance history cannot be erased' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END $$
""")
    op.execute(
        """
CREATE TRIGGER immutable_assistance_projection BEFORE UPDATE ON attempts FOR EACH ROW
EXECUTE FUNCTION guard_assistance_projection()
        """
    )
    op.execute("""
CREATE FUNCTION guard_assistance_grant() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE owned attempts%ROWTYPE; asset question_assistance_steps%ROWTYPE;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'Assistance grants are immutable' USING ERRCODE = '23514';
    END IF;
    SELECT * INTO owned FROM attempts WHERE id = NEW.attempt_id FOR UPDATE;
    SELECT * INTO asset FROM question_assistance_steps WHERE id = NEW.step_id;
    IF owned.id IS NULL OR asset.id IS NULL OR asset.version_id <> owned.question_version_id
       OR asset.kind <> owned.assistance_level OR owned.lifecycle_state NOT IN ('active','paused')
       OR NEW.granted_at < owned.started_at OR owned.independent_interval_ended_at IS NULL
       OR (NEW.operation = 'solution') <> (asset.kind = 'full_solution')
       OR (NEW.operation = 'solution') <> (NEW.reason = 'solution_escape') THEN
        RAISE EXCEPTION 'Assistance grant must match owned pinned content and state'
        USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END $$
""")
    op.execute(
        """
CREATE TRIGGER immutable_assistance_grant BEFORE INSERT OR UPDATE OR DELETE ON
assistance_grants FOR EACH ROW EXECUTE FUNCTION guard_assistance_grant()
        """
    )


def downgrade() -> None:
    # Refuse destructive loss of assistance history; a B3-only database is reversible.
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM assistance_grants) OR EXISTS (SELECT 1 FROM attempts WHERE
          policy_version_id = '00000000-0000-0000-0000-000000000101'
          OR assistance_level <> 'none') THEN
            RAISE EXCEPTION 'Cannot downgrade stored assistance history' USING ERRCODE = '23514';
        END IF;
    END $$""")
    op.execute("ALTER TABLE attempts ALTER COLUMN independent_end_reason TYPE VARCHAR(16)")
    op.drop_table("assistance_grants")
    op.execute("DROP FUNCTION guard_assistance_grant()")
    op.execute("DROP TRIGGER immutable_assistance_projection ON attempts")
    op.execute("DROP FUNCTION guard_assistance_projection()")
    op.execute("ALTER TABLE attempts DROP COLUMN prior_phase_elapsed_ms")
    op.execute("ALTER TABLE attempts DROP CONSTRAINT ck_attempt_assistance")
    op.execute(
        """
ALTER TABLE attempts ADD CONSTRAINT ck_attempt_assistance CHECK (assistance_level =
'none')
        """
    )
    op.execute("ALTER TABLE attempts DROP CONSTRAINT ck_attempt_independent_end")
    op.execute("""ALTER TABLE attempts ADD CONSTRAINT ck_attempt_independent_end CHECK (
        (independent_interval_ended_at IS NULL AND independent_end_reason IS NULL) OR
        (independent_interval_ended_at IS NOT NULL AND independent_end_reason IS NOT NULL
        AND independent_end_reason IN ('expired','deferred','abandoned')))""")
    op.execute("ALTER TABLE attempt_phases DROP CONSTRAINT ck_phase_kind")
    op.execute(
        """
ALTER TABLE attempt_phases ADD CONSTRAINT ck_phase_kind CHECK (phase_number = 0 AND kind =
'independent')
        """
    )
    op.execute("ALTER TABLE attempt_events DROP CONSTRAINT ck_attempt_event_type")
    op.execute(
        """
ALTER TABLE attempt_events ADD CONSTRAINT ck_attempt_event_type CHECK (event_type IN
('started','paused','resumed','extended','expired','deferred','abandoned'))
        """
    )
    op.execute("ALTER TABLE learning_policy_versions DISABLE TRIGGER immutable_timer_history")
    op.execute(
        "DELETE FROM learning_policy_versions WHERE id = '00000000-0000-0000-0000-000000000101'"
    )
    op.execute("ALTER TABLE learning_policy_versions ENABLE TRIGGER immutable_timer_history")
