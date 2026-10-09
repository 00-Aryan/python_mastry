"""Owned attempt lifecycle, timer policy, phases and immutable event history."""

from alembic import op

revision = "0004_attempt_timers"
down_revision = "0003_skill_graph"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE learning_policy_versions (
    id UUID NOT NULL,
    version_code VARCHAR(64) NOT NULL,
    configuration_json JSONB NOT NULL,
    effective_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    UNIQUE (version_code)
)
""")
    op.execute("""
CREATE TABLE attempts (
    id UUID NOT NULL,
    user_id UUID NOT NULL,
    question_version_id UUID NOT NULL,
    policy_version_id UUID NOT NULL,
    mode VARCHAR(32) NOT NULL,
    lifecycle_state VARCHAR(16) NOT NULL,
    assistance_level VARCHAR(32) NOT NULL,
    revision INTEGER NOT NULL,
    last_event_sequence INTEGER NOT NULL,
    started_at TIMESTAMP WITH TIME ZONE NOT NULL,
    finished_at TIMESTAMP WITH TIME ZONE,
    total_active_elapsed_ms BIGINT NOT NULL,
    total_running_since TIMESTAMP WITH TIME ZONE,
    last_reconciled_at TIMESTAMP WITH TIME ZONE NOT NULL,
    independent_interval_ended_at TIMESTAMP WITH TIME ZONE,
    independent_end_reason VARCHAR(16),
    timing_accommodated BOOLEAN NOT NULL,
    family_previously_attempted BOOLEAN NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT ck_attempt_mode CHECK (mode IN ('practice','assessment')),
    CONSTRAINT ck_attempt_lifecycle CHECK (lifecycle_state IN
    ('active','paused','completed','deferred','abandoned')),
    CONSTRAINT ck_attempt_assistance CHECK (assistance_level = 'none'),
    CONSTRAINT ck_attempt_counters CHECK (revision > 0 AND last_event_sequence >= 0 AND
    total_active_elapsed_ms >= 0),
    CONSTRAINT ck_attempt_finished CHECK ((lifecycle_state IN ('active','paused') AND finished_at IS
    NULL) OR (lifecycle_state IN ('completed','deferred','abandoned') AND finished_at IS NOT
    NULL)),
    CONSTRAINT ck_attempt_running CHECK ((lifecycle_state = 'active' AND total_running_since IS NOT
    NULL) OR (lifecycle_state <> 'active' AND total_running_since IS NULL)),
    CONSTRAINT ck_attempt_independent_end CHECK ((independent_interval_ended_at IS NULL AND
    independent_end_reason IS NULL) OR (independent_interval_ended_at IS NOT NULL
    AND independent_end_reason IS NOT NULL
    AND independent_end_reason IN ('expired','deferred','abandoned'))),
    CONSTRAINT ck_attempt_timestamps CHECK (last_reconciled_at >= started_at AND (finished_at IS
    NULL OR finished_at >= started_at)),
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE RESTRICT,
    FOREIGN KEY(question_version_id) REFERENCES question_versions (id) ON DELETE RESTRICT,
    FOREIGN KEY(policy_version_id) REFERENCES learning_policy_versions (id) ON DELETE RESTRICT
)
""")
    op.execute("""
CREATE INDEX ix_attempt_owner_history ON attempts (user_id, started_at, id)
""")
    op.execute("""
CREATE TABLE attempt_phases (
    id UUID NOT NULL,
    attempt_id UUID NOT NULL,
    phase_number INTEGER NOT NULL,
    kind VARCHAR(32) NOT NULL,
    started_at TIMESTAMP WITH TIME ZONE NOT NULL,
    budget_seconds INTEGER NOT NULL,
    active_elapsed_ms BIGINT NOT NULL,
    running_since TIMESTAMP WITH TIME ZONE,
    expired_at TIMESTAMP WITH TIME ZONE,
    closed_at TIMESTAMP WITH TIME ZONE,
    PRIMARY KEY (id),
    CONSTRAINT uq_attempt_phase_number UNIQUE (attempt_id, phase_number),
    CONSTRAINT ck_phase_kind CHECK (phase_number = 0 AND kind = 'independent'),
    CONSTRAINT ck_phase_durations CHECK (budget_seconds > 0 AND active_elapsed_ms >= 0 AND
    active_elapsed_ms <= budget_seconds::bigint * 1000),
    CONSTRAINT ck_phase_expired CHECK (expired_at IS NULL OR (closed_at IS NOT NULL
    AND closed_at = expired_at AND
    running_since IS NULL AND active_elapsed_ms = budget_seconds::bigint * 1000)),
    CONSTRAINT ck_phase_closed CHECK (closed_at IS NULL OR running_since IS NULL),
    FOREIGN KEY(attempt_id) REFERENCES attempts (id) ON DELETE RESTRICT
)
""")
    op.execute("""
CREATE UNIQUE INDEX ix_attempt_open_phase ON attempt_phases (attempt_id) WHERE closed_at IS NULL
""")
    op.execute("""
CREATE TABLE attempt_events (
    id UUID NOT NULL,
    attempt_id UUID NOT NULL,
    sequence_number INTEGER NOT NULL,
    event_type VARCHAR(32) NOT NULL,
    occurred_at TIMESTAMP WITH TIME ZONE NOT NULL,
    payload_json JSONB NOT NULL,
    command_id UUID,
    PRIMARY KEY (id),
    CONSTRAINT uq_attempt_event_sequence UNIQUE (attempt_id, sequence_number),
    CONSTRAINT ck_attempt_event_sequence CHECK (sequence_number > 0),
    CONSTRAINT ck_attempt_event_type CHECK (event_type IN
    ('started','paused','resumed','extended','expired','deferred','abandoned')),
    FOREIGN KEY(attempt_id) REFERENCES attempts (id) ON DELETE RESTRICT
)
""")
    op.execute("""
CREATE TABLE user_question_family_history (
    user_id UUID NOT NULL,
    family_id UUID NOT NULL,
    first_attempt_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (user_id, family_id),
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE RESTRICT,
    FOREIGN KEY(family_id) REFERENCES question_families (id) ON DELETE RESTRICT
)
""")
    op.execute("""
INSERT INTO learning_policy_versions (id, version_code, configuration_json, effective_at)
VALUES ('00000000-0000-0000-0000-000000000100', 'pilot-timer-1',
'{"minimum_budget_seconds": 60,"maximum_budget_seconds": 3600,
"maximum_extension_seconds": 1800,"allowed_modes":["practice","assessment"]}',
'2026-10-09T00:00:00Z')
""")
    op.execute("""
CREATE FUNCTION reject_timer_history_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Timer policy and event history are immutable' USING ERRCODE = '23514';
END $$
""")
    for table in ("learning_policy_versions", "attempt_events", "user_question_family_history"):
        op.execute(
            f"CREATE TRIGGER immutable_timer_history BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION reject_timer_history_mutation()"
        )
    op.execute("""
CREATE FUNCTION guard_attempt_history() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Attempt history cannot be deleted' USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF NOT EXISTS (SELECT 1 FROM question_versions
                       WHERE id = NEW.question_version_id AND status = 'published') THEN
            RAISE EXCEPTION 'Attempt requires published content' USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    IF ROW(NEW.user_id, NEW.question_version_id, NEW.policy_version_id, NEW.mode,
           NEW.started_at, NEW.family_previously_attempted)
       IS DISTINCT FROM ROW(OLD.user_id, OLD.question_version_id, OLD.policy_version_id,
                            OLD.mode, OLD.started_at, OLD.family_previously_attempted) THEN
        RAISE EXCEPTION 'Attempt ownership and versions are immutable' USING ERRCODE = '23514';
    END IF;
    IF (OLD.independent_interval_ended_at IS NOT NULL AND
        ROW(NEW.independent_interval_ended_at, NEW.independent_end_reason)
        IS DISTINCT FROM ROW(OLD.independent_interval_ended_at, OLD.independent_end_reason))
        OR (OLD.timing_accommodated AND NOT NEW.timing_accommodated)
        OR NEW.total_active_elapsed_ms < OLD.total_active_elapsed_ms
        OR NEW.last_reconciled_at < OLD.last_reconciled_at
        OR NEW.revision < OLD.revision OR NEW.last_event_sequence < OLD.last_event_sequence THEN
        RAISE EXCEPTION 'Attempt timing history cannot be erased' USING ERRCODE = '23514';
    END IF;
    IF OLD.lifecycle_state IN ('completed','deferred','abandoned') AND NEW IS DISTINCT FROM OLD THEN
        RAISE EXCEPTION 'Terminal attempt cannot be changed' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END $$
""")
    op.execute(
        "CREATE TRIGGER immutable_attempt_history BEFORE INSERT OR UPDATE OR DELETE ON attempts "
        "FOR EACH ROW EXECUTE FUNCTION guard_attempt_history()"
    )
    op.execute("""
CREATE FUNCTION guard_attempt_phase_history() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Phase history cannot be deleted' USING ERRCODE = '23514';
    END IF;
    IF ROW(NEW.attempt_id, NEW.phase_number, NEW.kind, NEW.started_at)
       IS DISTINCT FROM ROW(OLD.attempt_id, OLD.phase_number, OLD.kind, OLD.started_at)
       OR NEW.active_elapsed_ms < OLD.active_elapsed_ms OR NEW.budget_seconds < OLD.budget_seconds
       OR (OLD.expired_at IS NOT NULL AND
           ROW(NEW.expired_at, NEW.closed_at, NEW.budget_seconds)
           IS DISTINCT FROM ROW(OLD.expired_at, OLD.closed_at, OLD.budget_seconds))
       OR (OLD.closed_at IS NOT NULL AND NEW IS DISTINCT FROM OLD) THEN
        RAISE EXCEPTION 'Phase history cannot be erased' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END $$
""")
    op.execute(
        "CREATE TRIGGER immutable_phase_history BEFORE UPDATE OR DELETE ON attempt_phases "
        "FOR EACH ROW EXECUTE FUNCTION guard_attempt_phase_history()"
    )


def downgrade() -> None:
    for table in (
        "user_question_family_history",
        "attempt_events",
        "attempt_phases",
        "attempts",
        "learning_policy_versions",
    ):
        op.drop_table(table)
    for function in (
        "guard_attempt_phase_history",
        "guard_attempt_history",
        "reject_timer_history_mutation",
    ):
        op.execute(f"DROP FUNCTION {function}()")
