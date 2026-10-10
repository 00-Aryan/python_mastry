"""Durable owned evaluation orchestration; no real runner is enabled."""

from alembic import op

revision = "0007_evaluation_lifecycle"
down_revision = "0006_immutable_submissions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE attempt_events DROP CONSTRAINT ck_attempt_event_type")
    op.execute("""ALTER TABLE attempt_events ADD CONSTRAINT ck_attempt_event_type CHECK
    (event_type IN ('started','paused','resumed','extended','expired','deferred','abandoned',
    'assistance_granted','submission_received','evaluation_requested'))""")
    op.execute("""CREATE TABLE evaluator_policy_versions (
	id UUID NOT NULL,
	version_code VARCHAR(100) NOT NULL,
	configuration_json JSONB NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (version_code)
)""")
    op.execute("""CREATE TABLE evaluation_test_bundles (
	id UUID NOT NULL,
	question_version_id UUID NOT NULL,
	purpose VARCHAR(16) NOT NULL,
	content_hash VARCHAR(64) NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_evaluation_bundle UNIQUE (question_version_id, purpose),
	CONSTRAINT ck_bundle_purpose CHECK (purpose IN ('public_run','assessment')),
	FOREIGN KEY(question_version_id) REFERENCES question_versions (id) ON DELETE RESTRICT
)""")
    op.execute("""CREATE TABLE evaluation_test_bundle_members (
	bundle_id UUID NOT NULL,
	test_id UUID NOT NULL,
	PRIMARY KEY (bundle_id, test_id),
	FOREIGN KEY(bundle_id) REFERENCES evaluation_test_bundles (id) ON DELETE RESTRICT,
	FOREIGN KEY(test_id) REFERENCES question_test_cases (id) ON DELETE RESTRICT
)""")
    op.execute("""CREATE TABLE evaluation_jobs (
	id UUID NOT NULL,
	attempt_id UUID NOT NULL,
	submission_id UUID NOT NULL,
	question_version_id UUID NOT NULL,
	policy_version_id UUID NOT NULL,
	test_bundle_id UUID NOT NULL,
	evaluator_policy_version_id UUID NOT NULL,
	purpose VARCHAR(16) NOT NULL,
	runner_identity VARCHAR(100) NOT NULL,
	status VARCHAR(32) NOT NULL,
	category VARCHAR(32),
	requested_event_sequence INTEGER NOT NULL,
	requested_at TIMESTAMP WITH TIME ZONE NOT NULL,
	deadline_at TIMESTAMP WITH TIME ZONE NOT NULL,
	finished_at TIMESTAMP WITH TIME ZONE,
	next_retry_at TIMESTAMP WITH TIME ZONE NOT NULL,
	generation INTEGER NOT NULL,
	last_sequence INTEGER NOT NULL,
	lease_token UUID,
	lease_until TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (id),
	CONSTRAINT uq_evaluation_submission UNIQUE (submission_id),
        CONSTRAINT ck_evaluation_status CHECK (status IN
('pending','running','passed','failed','infrastructure_error')),
        CONSTRAINT ck_evaluation_category CHECK (category IS NULL OR category IN
('passed','incorrect','syntax_error','resource_limit','infrastructure_error')),
        CONSTRAINT ck_evaluation_counters CHECK (generation >= 0 AND generation <= 3 AND
last_sequence > 0),
        CONSTRAINT ck_evaluation_lease CHECK ((status = 'running' AND lease_token IS NOT NULL
AND lease_until IS NOT NULL) OR (status <> 'running' AND lease_token IS NULL AND lease_until
IS NULL)),
        CONSTRAINT ck_evaluation_result CHECK ((status IN ('pending','running') AND
finished_at IS NULL AND category IS NULL) OR (status = 'passed' AND category = 'passed' AND
finished_at IS NOT NULL) OR (status = 'failed' AND category IN
('incorrect','syntax_error','resource_limit') AND finished_at IS NOT NULL) OR (status =
'infrastructure_error' AND category = 'infrastructure_error' AND finished_at IS NOT NULL)),
        CONSTRAINT ck_evaluation_times CHECK (deadline_at > requested_at AND next_retry_at >=
requested_at),
	FOREIGN KEY(attempt_id) REFERENCES attempts (id) ON DELETE RESTRICT,
	FOREIGN KEY(submission_id) REFERENCES submissions (id) ON DELETE RESTRICT,
	FOREIGN KEY(question_version_id) REFERENCES question_versions (id) ON DELETE RESTRICT,
	FOREIGN KEY(policy_version_id) REFERENCES learning_policy_versions (id) ON DELETE RESTRICT,
	FOREIGN KEY(test_bundle_id) REFERENCES evaluation_test_bundles (id) ON DELETE RESTRICT,
        FOREIGN KEY(evaluator_policy_version_id) REFERENCES evaluator_policy_versions (id) ON
DELETE RESTRICT
)""")
    op.execute("""CREATE INDEX ix_evaluation_dispatch ON evaluation_jobs (status, next_retry_at)""")
    op.execute(
        """CREATE INDEX ix_evaluation_history
ON evaluation_jobs (attempt_id, requested_event_sequence)"""
    )
    op.execute(
        """CREATE UNIQUE INDEX ix_evaluation_pending_assessment
ON evaluation_jobs (attempt_id) WHERE
purpose = 'assessment' AND status IN ('pending','running')"""
    )
    op.execute("""CREATE TABLE evaluation_dispatch_intents (
	job_id UUID NOT NULL,
	request_id VARCHAR(128),
	PRIMARY KEY (job_id),
	FOREIGN KEY(job_id) REFERENCES evaluation_jobs (id) ON DELETE RESTRICT
)""")
    op.execute("""CREATE TABLE evaluation_events (
	job_id UUID NOT NULL,
	sequence_number INTEGER NOT NULL,
	state VARCHAR(32) NOT NULL,
	reason_code VARCHAR(32) NOT NULL,
	occurred_at TIMESTAMP WITH TIME ZONE NOT NULL,
	generation INTEGER NOT NULL,
	PRIMARY KEY (job_id, sequence_number),
	CONSTRAINT ck_evaluation_event_count CHECK (sequence_number > 0 AND generation >= 0),
        CONSTRAINT ck_evaluation_event_state CHECK (state IN
('pending','running','passed','failed','infrastructure_error')),
	FOREIGN KEY(job_id) REFERENCES evaluation_jobs (id) ON DELETE RESTRICT
)""")
    op.execute("""CREATE TABLE evaluation_request_receipts (
	submission_id UUID NOT NULL,
	request_key VARCHAR(128) NOT NULL,
	job_id UUID NOT NULL,
	request_hash VARCHAR(64) NOT NULL,
	response_json JSONB NOT NULL,
	PRIMARY KEY (submission_id, request_key),
	FOREIGN KEY(submission_id) REFERENCES submissions (id) ON DELETE RESTRICT,
	FOREIGN KEY(job_id) REFERENCES evaluation_jobs (id) ON DELETE RESTRICT
)""")
    op.execute("""INSERT INTO evaluator_policy_versions
    VALUES ('00000000-0000-0000-0000-000000000201', 'orchestration-v1', '{"protocol_version":
1, "maximum_dispatches": 3, "lease_seconds": 30, "deadline_seconds": 300, "backoff_seconds":
5}'::jsonb)""")
    op.execute("""
CREATE FUNCTION immutable_evaluation_fact() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Evaluation facts are immutable' USING ERRCODE = '23514';
END $$
""")
    for table in (
        "evaluator_policy_versions",
        "evaluation_test_bundles",
        "evaluation_test_bundle_members",
        "evaluation_events",
        "evaluation_dispatch_intents",
        "evaluation_request_receipts",
    ):
        op.execute(
            f"CREATE TRIGGER immutable_evaluation_fact BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION immutable_evaluation_fact()"
        )
    op.execute("""
CREATE FUNCTION guard_evaluation_member() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE bundle evaluation_test_bundles%ROWTYPE; test question_test_cases%ROWTYPE;
BEGIN
    SELECT * INTO bundle FROM evaluation_test_bundles WHERE id = NEW.bundle_id FOR UPDATE;
    SELECT * INTO test FROM question_test_cases WHERE id = NEW.test_id;
    IF test.version_id IS DISTINCT FROM bundle.question_version_id
       OR (bundle.purpose = 'public_run' AND test.visibility <> 'public')
       OR EXISTS (SELECT 1 FROM evaluation_jobs WHERE test_bundle_id = bundle.id) THEN
        RAISE EXCEPTION 'Bundle must reference matching published tests before use'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END $$
""")
    op.execute("""CREATE TRIGGER evaluation_member BEFORE INSERT ON evaluation_test_bundle_members
FOR EACH ROW EXECUTE FUNCTION guard_evaluation_member()""")
    op.execute("""
CREATE FUNCTION guard_evaluation_job() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE source submissions%ROWTYPE; bundle evaluation_test_bundles%ROWTYPE;
        owned attempts%ROWTYPE; previous_time TIMESTAMPTZ;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Evaluation history cannot be deleted' USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'INSERT' THEN
        SELECT * INTO source FROM submissions WHERE id = NEW.submission_id;
        SELECT * INTO bundle FROM evaluation_test_bundles WHERE id = NEW.test_bundle_id;
        SELECT * INTO owned FROM attempts WHERE id = source.attempt_id FOR UPDATE;
        IF source.id IS NULL OR bundle.id IS NULL OR owned.id IS NULL
           OR NEW.attempt_id <> source.attempt_id OR NEW.question_version_id <>
source.question_version_id
           OR NEW.policy_version_id <> source.policy_version_id OR NEW.purpose <>
source.purpose
           OR bundle.question_version_id <> source.question_version_id OR bundle.purpose <>
source.purpose
           OR owned.lifecycle_state NOT IN ('active','paused')
           OR NEW.status <> 'pending' OR NEW.generation <> 0 OR NEW.last_sequence <> 1
           OR NEW.requested_at <> owned.last_reconciled_at
           OR NEW.requested_event_sequence <> owned.last_event_sequence
           OR NOT EXISTS (SELECT 1 FROM attempt_events WHERE attempt_id = owned.id
               AND sequence_number = NEW.requested_event_sequence AND event_type =
'evaluation_requested'
               AND payload_json->>'job_id' = NEW.id::text AND occurred_at = NEW.requested_at)
           OR NOT EXISTS (SELECT 1 FROM question_versions
               WHERE id = NEW.question_version_id AND status = 'published')
           OR EXISTS ((SELECT id FROM question_test_cases WHERE version_id =
NEW.question_version_id
                AND (NEW.purpose = 'assessment' OR visibility = 'public'))
                EXCEPT (SELECT test_id FROM evaluation_test_bundle_members WHERE bundle_id =
bundle.id))
           OR NOT EXISTS (SELECT 1 FROM evaluation_test_bundle_members WHERE bundle_id =
bundle.id) THEN
            RAISE EXCEPTION 'Evaluation must match immutable submission and test bundle'
                USING ERRCODE = '23514';
        END IF;
    ELSE
        IF OLD.status IN ('passed','failed','infrastructure_error')
           OR ROW(NEW.id, NEW.attempt_id, NEW.submission_id, NEW.question_version_id,
                  NEW.policy_version_id, NEW.test_bundle_id, NEW.evaluator_policy_version_id,
                  NEW.purpose, NEW.runner_identity, NEW.requested_at, NEW.deadline_at,
                  NEW.requested_event_sequence)
              IS DISTINCT FROM ROW(OLD.id, OLD.attempt_id, OLD.submission_id,
OLD.question_version_id,
                  OLD.policy_version_id, OLD.test_bundle_id, OLD.evaluator_policy_version_id,
                  OLD.purpose, OLD.runner_identity, OLD.requested_at, OLD.deadline_at,
                  OLD.requested_event_sequence)
           OR NEW.last_sequence <> OLD.last_sequence + 1
           OR NOT ((OLD.status = 'pending' AND NEW.status IN
('running','infrastructure_error'))
               OR (OLD.status = 'running' AND NEW.status IN
                   ('pending','passed','failed','infrastructure_error')))
           OR NEW.generation <> OLD.generation + (CASE WHEN NEW.status = 'running' THEN 1 ELSE
0 END)
           OR (NEW.status = 'running' AND NEW.lease_token = OLD.lease_token) THEN
            RAISE EXCEPTION 'Invalid evaluation transition or changed pins' USING ERRCODE =
'23514';
        END IF;
    END IF;
    RETURN NEW;
END $$
""")
    op.execute("""CREATE TRIGGER evaluation_job BEFORE INSERT OR UPDATE OR DELETE ON evaluation_jobs
FOR EACH ROW EXECUTE FUNCTION guard_evaluation_job()""")
    op.execute("""
CREATE FUNCTION guard_evaluation_event() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE job evaluation_jobs%ROWTYPE; previous evaluation_events%ROWTYPE;
BEGIN
    SELECT * INTO job FROM evaluation_jobs WHERE id = NEW.job_id;
    SELECT * INTO previous FROM evaluation_events WHERE job_id = NEW.job_id
        ORDER BY sequence_number DESC LIMIT 1;
    IF NEW.sequence_number <> job.last_sequence OR NEW.state <> job.status
       OR NEW.generation <> job.generation
       OR NEW.sequence_number <> COALESCE(previous.sequence_number, 0) + 1
       OR NEW.occurred_at < COALESCE(previous.occurred_at, job.requested_at) THEN
        RAISE EXCEPTION 'Evaluation event must match current ordered state' USING ERRCODE =
'23514';
    END IF;
    RETURN NEW;
END $$
""")
    op.execute("""CREATE TRIGGER evaluation_event BEFORE INSERT ON evaluation_events
FOR EACH ROW EXECUTE FUNCTION guard_evaluation_event()""")
    op.execute("""
CREATE FUNCTION require_evaluation_history() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM evaluation_events WHERE job_id = NEW.id
                   AND sequence_number = NEW.last_sequence AND state = NEW.status
                   AND generation = NEW.generation)
       OR NOT EXISTS (SELECT 1 FROM evaluation_dispatch_intents WHERE job_id = NEW.id) THEN
        RAISE EXCEPTION 'Evaluation requires atomic history and dispatch intent' USING ERRCODE
= '23514';
    END IF;
    RETURN NULL;
END $$
""")
    op.execute("""CREATE CONSTRAINT TRIGGER evaluation_history AFTER INSERT OR UPDATE
ON evaluation_jobs DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
EXECUTE FUNCTION require_evaluation_history()""")


def downgrade() -> None:
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM evaluation_jobs) THEN
            RAISE EXCEPTION 'Cannot downgrade stored evaluation history' USING ERRCODE =
'23514';
        END IF;
    END $$""")
    for table in (
        "evaluation_request_receipts",
        "evaluation_events",
        "evaluation_dispatch_intents",
        "evaluation_jobs",
        "evaluation_test_bundle_members",
        "evaluation_test_bundles",
        "evaluator_policy_versions",
    ):
        op.drop_table(table)
    for name in (
        "require_evaluation_history",
        "guard_evaluation_event",
        "guard_evaluation_job",
        "guard_evaluation_member",
        "immutable_evaluation_fact",
    ):
        op.execute(f"DROP FUNCTION {name}()")
    op.execute("ALTER TABLE attempt_events DROP CONSTRAINT ck_attempt_event_type")
    op.execute("""ALTER TABLE attempt_events ADD CONSTRAINT ck_attempt_event_type CHECK
    (event_type IN ('started','paused','resumed','extended','expired','deferred','abandoned',
    'assistance_granted','submission_received'))""")
