"""Authenticated local execution and immutable runtime provenance."""

from alembic import op

revision = "0008_local_execution"
down_revision = "0007_evaluation_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
ALTER TABLE evaluation_jobs DROP CONSTRAINT ck_evaluation_category;
ALTER TABLE evaluation_jobs ADD CONSTRAINT ck_evaluation_category CHECK
(category IS NULL OR category IN ('passed','incorrect','syntax_error','runtime_error',
'resource_limit','infrastructure_error'));
ALTER TABLE evaluation_jobs DROP CONSTRAINT ck_evaluation_result;
ALTER TABLE evaluation_jobs ADD CONSTRAINT ck_evaluation_result CHECK
((status IN ('pending','running') AND finished_at IS NULL AND category IS NULL)
OR (status = 'passed' AND category = 'passed' AND finished_at IS NOT NULL)
OR (status = 'failed' AND category IN ('incorrect','syntax_error','runtime_error','resource_limit')
AND finished_at IS NOT NULL) OR (status = 'infrastructure_error' AND
category = 'infrastructure_error' AND finished_at IS NOT NULL));
CREATE TABLE execution_worker_identities (
 id UUID PRIMARY KEY, credential_hash VARCHAR(64) NOT NULL,
 runner_identity VARCHAR(100) NOT NULL UNIQUE,
 evaluator_policy_version_id UUID NOT NULL REFERENCES evaluator_policy_versions(id)
 ON DELETE RESTRICT,
 revoked BOOLEAN NOT NULL DEFAULT false, ready_until TIMESTAMPTZ,
 CONSTRAINT ck_worker_hash CHECK (length(credential_hash) = 64));
CREATE TABLE evaluation_run_provenance (
 job_id UUID NOT NULL REFERENCES evaluation_jobs(id) ON DELETE RESTRICT,
 generation INTEGER NOT NULL,
 worker_id UUID NOT NULL REFERENCES execution_worker_identities(id) ON DELETE RESTRICT,
 record_json JSONB NOT NULL, signature VARCHAR(64) NOT NULL,
 PRIMARY KEY(job_id,generation),
 CONSTRAINT ck_provenance_generation CHECK(generation BETWEEN 1 AND 3),
 CONSTRAINT ck_provenance_signature CHECK(length(signature) = 64));
CREATE TRIGGER immutable_run_provenance BEFORE UPDATE OR DELETE ON evaluation_run_provenance
FOR EACH ROW EXECUTE FUNCTION immutable_evaluation_fact();
CREATE FUNCTION guard_worker_identity() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'Worker identity is historical' USING ERRCODE='23514';
 END IF;
 IF (NEW.id,NEW.credential_hash,NEW.runner_identity,NEW.evaluator_policy_version_id)
 IS DISTINCT FROM (OLD.id,OLD.credential_hash,OLD.runner_identity,OLD.evaluator_policy_version_id)
 OR (OLD.revoked AND NOT NEW.revoked) THEN
 RAISE EXCEPTION 'Worker authority is immutable; provision a new identity' USING ERRCODE='23514';
 END IF; RETURN NEW;
END $$;
CREATE TRIGGER guard_worker_identity BEFORE UPDATE OR DELETE ON execution_worker_identities
FOR EACH ROW EXECUTE FUNCTION guard_worker_identity();
CREATE FUNCTION guard_run_provenance() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE j evaluation_jobs; w execution_worker_identities; p JSONB;
 s submissions; b evaluation_test_bundles;
BEGIN
 SELECT * INTO j FROM evaluation_jobs WHERE id=NEW.job_id;
 SELECT * INTO w FROM execution_worker_identities WHERE id=NEW.worker_id;
 SELECT configuration_json INTO p FROM evaluator_policy_versions WHERE
 id=j.evaluator_policy_version_id;
 SELECT * INTO s FROM submissions WHERE id=j.submission_id;
 SELECT * INTO b FROM evaluation_test_bundles WHERE id=j.test_bundle_id;
 IF w.revoked OR w.runner_identity <> j.runner_identity
 OR w.evaluator_policy_version_id <> j.evaluator_policy_version_id
 OR NEW.generation > j.generation OR p->>'protocol_version' <> '2'
 OR NEW.record_json->>'job_id' IS DISTINCT FROM j.id::text
 OR NEW.record_json->>'generation' IS DISTINCT FROM NEW.generation::text
 OR NEW.record_json->>'worker_id' IS DISTINCT FROM w.id::text
 OR NEW.record_json->>'runner_identity' IS DISTINCT FROM j.runner_identity
 OR NEW.record_json->>'submission_id' IS DISTINCT FROM j.submission_id::text
 OR NEW.record_json->>'question_version_id' IS DISTINCT FROM j.question_version_id::text
 OR NEW.record_json->>'policy_version_id' IS DISTINCT FROM j.policy_version_id::text
 OR NEW.record_json->>'evaluator_policy_version_id'
 IS DISTINCT FROM j.evaluator_policy_version_id::text
 OR NEW.record_json->>'test_bundle_id' IS DISTINCT FROM j.test_bundle_id::text
 OR NEW.record_json->>'source_hash' IS DISTINCT FROM s.code_hash
 OR NEW.record_json->>'bundle_hash' IS DISTINCT FROM b.content_hash
 OR NEW.record_json->>'runtime_image_hash' IS DISTINCT FROM p->>'runtime_image_hash'
 OR NEW.record_json->>'isolation_profile_hash' IS DISTINCT FROM p->>'isolation_profile_hash'
 OR NEW.record_json->>'outcome' NOT IN
 ('passed','incorrect','syntax_error','runtime_error','resource_limit','infrastructure_error')
 THEN RAISE EXCEPTION 'Execution provenance does not match immutable pins' USING ERRCODE='23514';
 END IF; RETURN NEW;
END $$;
CREATE TRIGGER guard_run_provenance BEFORE INSERT ON evaluation_run_provenance
FOR EACH ROW EXECUTE FUNCTION guard_run_provenance();

""")


def downgrade() -> None:
    op.execute("""DO $$ BEGIN
IF EXISTS (SELECT 1 FROM evaluation_run_provenance) OR EXISTS
(SELECT 1 FROM evaluation_jobs WHERE category = 'runtime_error') THEN
RAISE EXCEPTION 'Cannot remove execution history'; END IF; END $$;
DROP TABLE evaluation_run_provenance;
DROP TABLE execution_worker_identities;
DROP FUNCTION guard_run_provenance();
DROP FUNCTION guard_worker_identity();
ALTER TABLE evaluation_jobs DROP CONSTRAINT ck_evaluation_category;
ALTER TABLE evaluation_jobs ADD CONSTRAINT ck_evaluation_category CHECK
(category IS NULL OR category IN ('passed','incorrect','syntax_error','resource_limit',
'infrastructure_error'));
ALTER TABLE evaluation_jobs DROP CONSTRAINT ck_evaluation_result;
ALTER TABLE evaluation_jobs ADD CONSTRAINT ck_evaluation_result CHECK
((status IN ('pending','running') AND finished_at IS NULL AND category IS NULL)
OR (status = 'passed' AND category = 'passed' AND finished_at IS NOT NULL)
OR (status = 'failed' AND category IN ('incorrect','syntax_error','resource_limit')
AND finished_at IS NOT NULL) OR (status = 'infrastructure_error' AND
category = 'infrastructure_error' AND finished_at IS NOT NULL));""")
