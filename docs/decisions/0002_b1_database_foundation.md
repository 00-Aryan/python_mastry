# B1 first increment: database foundation

This is a partial B1 release, identified as `B1-foundation`. It adds PostgreSQL
connections, synchronous SQLAlchemy sessions, database readiness and Alembic.
Identity, roles, content storage and publication remain subsequent B1 work.
No timer, execution or learning rules are introduced.

## Responsibilities and request flow

`infrastructure/database/session.py` creates a lazy, bounded engine using psycopg
3, a session factory and a read-only connection probe. Both supported URL schemes
select psycopg 3. URL query options are rejected so they cannot override the
configured connection policy. Settings validate positive timeouts and bounded
pool limits. Every connection sets UTC and the statement timeout through libpq
startup options, including connections used by Alembic.

The app lifespan owns one engine and factory per app; shutdown disposes the pool.
Creating the app does not connect or migrate. A synchronous readiness route runs
the probe in FastAPI's worker thread, returns `database: connected`, or translates
SQLAlchemy connection/pool failures into a safe 503 `DATABASE_UNAVAILABLE`.
Existing request IDs, safe structured exception frames and CORS still apply.
Liveness performs no database I/O. Public capabilities remain empty. Readiness
establishes connectivity only, not migration currency or evaluator readiness.

Each factory call creates a new session. Future application use cases must open
their own session and transaction, for example `with factory() as session,
session.begin(): ...`. Closing a session does not commit. Repositories will not
commit. Do not share a session between concurrent operations or hold a transaction
across external work. No empty repositories, ORM models or application services
are added before they have implemented responsibilities.

## Migration and data relationships

`alembic.ini` locates repository migrations without storing credentials.
`migrations/env.py` reads validated settings and uses the same engine policy;
programmatic callers can supply a connection for isolated migration tests.
`migrations/script.py.mako` supports future reviewed revisions.

Revision `0001_database_baseline` intentionally has no application DDL. Alembic
creates its own `alembic_version` table with a primary key and stores the revision.
This establishes migration history before adding identities/content with their
use cases and constraints. There are no application data relationships yet.
Upgrade is replayable; downgrade to base clears the revision row. Startup never
calls `create_all` or automatically upgrades the schema. Autogeneration has no
model metadata in this increment; future model migrations must wire it explicitly.

## Acceptance tests

Unit/API tests cover lazy engine creation, independent sessions, invalid database
settings, rejected URL overrides, shutdown disposal, readiness success/outage/
recovery, secret-safe errors and database-independent liveness. Existing B0 tests
continue checking the released routes and public data boundaries.

Real PostgreSQL tests exercise migration upgrade/replay/downgrade/re-upgrade and
the Alembic primary key; session close rollback, explicit commit and exception
rollback; UTC, configured statement timeout and recovery after cancellation.
Tests create randomly named schemas and clean only those schemas. A test URL must
end in `_test` and its database name must differ from DATABASE_URL, even across
host aliases or credentials. Missing TEST_DATABASE_URL skips real DB checks;
invalid or unavailable configured databases fail. CI supplies PostgreSQL.
The ordinary application URL is read through Settings, including `.env`, so
unexported development configuration cannot bypass the separate-database guard.

No row-locking or application FK/check constraints are claimed: there are no
concurrent mutation use cases or application tables yet. Those tests accompany
the relevant next increment.

Source archive inclusion of migrations and setup records is configured with
uv's documented [source-include setting](https://docs.astral.sh/uv/concepts/build-backend/#file-inclusion-and-exclusion)
and checked against the built archive.
