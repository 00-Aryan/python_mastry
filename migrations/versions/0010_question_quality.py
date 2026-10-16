"""Private version-owned misconception programs and immutable quality evidence."""

from alembic import op

revision = "0010_question_quality"
down_revision = "0009_publication_artifacts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE question_incorrect_solutions (
 id UUID PRIMARY KEY, version_id UUID NOT NULL REFERENCES question_versions(id) ON DELETE RESTRICT,
 position INTEGER NOT NULL, label VARCHAR(64) NOT NULL, source_code TEXT NOT NULL,
 CONSTRAINT uq_incorrect_position UNIQUE(version_id,position),
 CONSTRAINT uq_incorrect_label UNIQUE(version_id,label),
 CONSTRAINT ck_incorrect_source CHECK(position > 0 AND length(source_code) BETWEEN 1 AND 65536),
 CONSTRAINT ck_incorrect_label CHECK(label ~ '^[A-Z][A-Z0-9_-]{1,63}$'));
CREATE TRIGGER freeze_question_content BEFORE INSERT OR UPDATE OR DELETE
 ON question_incorrect_solutions FOR EACH ROW EXECUTE FUNCTION guard_question_child('version_id');
ALTER TABLE publication_verification_artifacts DROP CONSTRAINT ck_publication_artifact_verifier;
ALTER TABLE publication_verification_artifacts ADD CONSTRAINT ck_publication_artifact_verifier
 CHECK(verifier_identity = 'local-reference-verifier' AND
 verifier_version IN ('reference-v1','quality-v2'));
CREATE TABLE publication_quality_evidence (
 artifact_id UUID PRIMARY KEY REFERENCES publication_verification_artifacts(id) ON DELETE RESTRICT,
 reason_code VARCHAR(32) NOT NULL, total_candidates INTEGER NOT NULL,
 killed_candidates INTEGER NOT NULL, executions INTEGER NOT NULL,
 CONSTRAINT ck_quality_reason CHECK(reason_code IN ('PASSED','INVALID_CONTRACT',
 'INVALID_CANDIDATES','REFERENCE_FAILED','WEAK_SUITE','INFRASTRUCTURE_ERROR','RESOURCE_LIMIT')),
 CONSTRAINT ck_quality_counts CHECK(total_candidates BETWEEN 0 AND 8 AND
 killed_candidates BETWEEN 0 AND total_candidates AND executions BETWEEN 0 AND 256),
 CONSTRAINT ck_quality_passed CHECK(reason_code <> 'PASSED' OR
 (total_candidates >= 2 AND killed_candidates=total_candidates AND
 executions >= 2 + 2 * total_candidates)));
CREATE TRIGGER immutable_quality_evidence BEFORE UPDATE OR DELETE ON publication_quality_evidence
 FOR EACH ROW EXECUTE FUNCTION immutable_evaluation_fact();
""")


def downgrade() -> None:
    op.execute("""
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM publication_quality_evidence) OR
 EXISTS(SELECT 1 FROM question_incorrect_solutions) OR
 EXISTS(SELECT 1 FROM publication_verification_artifacts WHERE verifier_version='quality-v2') THEN
 RAISE EXCEPTION 'Cannot remove question quality history'; END IF;
END $$;
DROP TABLE publication_quality_evidence;
DROP TABLE question_incorrect_solutions;
ALTER TABLE publication_verification_artifacts DROP CONSTRAINT ck_publication_artifact_verifier;
ALTER TABLE publication_verification_artifacts ADD CONSTRAINT ck_publication_artifact_verifier
 CHECK(verifier_identity='local-reference-verifier' AND verifier_version='reference-v1');
""")
