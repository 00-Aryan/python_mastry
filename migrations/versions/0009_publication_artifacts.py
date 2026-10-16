"""Append-only bounded publication verification artifacts, independent of publication."""

from alembic import op

revision = "0009_publication_artifacts"
down_revision = "0008_local_execution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE publication_verification_artifacts (
 id UUID PRIMARY KEY,
 question_version_id UUID NOT NULL REFERENCES question_versions(id) ON DELETE RESTRICT,
 requested_by UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
 revision INTEGER NOT NULL, snapshot_bytes BYTEA NOT NULL,
 content_hash VARCHAR(64) NOT NULL, bundle_hash VARCHAR(64) NOT NULL,
 reference_hash VARCHAR(64) NOT NULL,
 evaluator_policy_version_id UUID NOT NULL
 REFERENCES evaluator_policy_versions(id) ON DELETE RESTRICT,
 verifier_identity VARCHAR(100) NOT NULL, verifier_version VARCHAR(100) NOT NULL,
 created_at TIMESTAMPTZ NOT NULL, result_json JSONB NOT NULL,
 CONSTRAINT ck_publication_artifact_revision CHECK(revision > 0),
 CONSTRAINT ck_publication_artifact_snapshot CHECK(
 octet_length(snapshot_bytes) BETWEEN 1 AND 1048576 AND
 content_hash = encode(sha256(snapshot_bytes), 'hex')),
 CONSTRAINT ck_publication_artifact_hashes CHECK(
 bundle_hash ~ '^[a-f0-9]{64}$' AND reference_hash ~ '^[a-f0-9]{64}$'),
 CONSTRAINT ck_publication_artifact_verifier CHECK(
 verifier_identity = 'local-reference-verifier' AND verifier_version = 'reference-v1'),
 CONSTRAINT ck_publication_artifact_result CHECK(
 jsonb_typeof(result_json) = 'object' AND octet_length(result_json::text) <= 512),
 CONSTRAINT ck_publication_artifact_counts CHECK(
 jsonb_typeof(result_json->'outcome') = 'string' AND
 jsonb_typeof(result_json->'checked_cases') = 'number' AND
 jsonb_typeof(result_json->'total_cases') = 'number' AND
 result_json ?& ARRAY['outcome','checked_cases','total_cases'] AND
 result_json - ARRAY['outcome','checked_cases','total_cases'] = '{}'::jsonb AND
 result_json->>'outcome' IN ('passed','incorrect','syntax_error','runtime_error',
 'resource_limit','infrastructure_error') AND
 (result_json->>'total_cases')::integer BETWEEN 1 AND 64 AND
 (result_json->>'checked_cases')::integer BETWEEN 0 AND (result_json->>'total_cases')::integer AND
 (result_json->>'outcome' <> 'passed' OR
 result_json->>'checked_cases' = result_json->>'total_cases')));
CREATE INDEX ix_publication_artifact_version ON publication_verification_artifacts
(question_version_id,created_at,id);
CREATE TRIGGER immutable_publication_artifact BEFORE UPDATE OR DELETE
 ON publication_verification_artifacts FOR EACH ROW EXECUTE FUNCTION immutable_evaluation_fact();
""")


def downgrade() -> None:
    op.execute("""
DO $$ BEGIN
 IF EXISTS (SELECT 1 FROM publication_verification_artifacts) THEN
 RAISE EXCEPTION 'Cannot remove publication verification history'; END IF;
END $$;
DROP TABLE publication_verification_artifacts;
""")
