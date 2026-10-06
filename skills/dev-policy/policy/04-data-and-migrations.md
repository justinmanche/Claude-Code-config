# 04 — Data and migrations

Applies when touching a schema, a migration, a seed, an index, a transaction, row-level security, or backups.

Contents: 1 Schema design · 2 Migrations as code · 3 Changing a live schema · 4 Locks and performance · 5 Row-level security · 6 Seeds and test data · 7 Backups and recovery · 8 Sources

## 1. Schema design

**DATA-01** MUST give every tenant-scoped table an explicit tenant column (or an unambiguous foreign-key chain to one), a primary key, and the constraints that encode the business rule (`NOT NULL`, `UNIQUE`, `CHECK`, foreign keys with the right `ON DELETE`). A rule enforced only in code is enforced only sometimes.

**DATA-02** SHOULD store enumerations as database enums or checked text, timestamps as `timestamptz`, money as integer minor units or `numeric`, never as floating point.

**DATA-03** MUST index every foreign key and every column that a list endpoint filters or sorts on. Verify with `EXPLAIN` on realistic row counts before shipping a new query path; a query that uses a sequential scan on a growing table is a time bomb.

**DATA-04** MUST keep parent links of audit-relevant rows immutable after creation, or denormalise the ancestry at write time, so history survives re-parenting and deletion.

## 2. Migrations as code

**DATA-05** MUST version every schema change as a migration file in the repo, numbered monotonically, applied automatically by the deploy, and recorded in a migrations table. No portal or `psql` changes to shared environments.

**DATA-06** MUST NEVER edit a migration that has been applied anywhere shared. Fix forward with a new migration. A new migration MUST NOT depend on a lower-numbered one being re-run.

**DATA-07** SHOULD make production migrations forward-only. Where a reversal is genuinely needed (a security cutover), author and exercise the rollback script before the migration ships, and run it through the migration runner under the administrator credential, never by hand.

## 3. Changing a live schema

**DATA-08** MUST use expand/contract for any breaking change: add the new column or table (nullable or defaulted) → dual-write and backfill in batches → switch reads → drop the old structure in a later release. This is what makes application rollback possible: the previous image still works against the expanded schema.

**DATA-09** MUST test the upgrade path, not only the fresh install: run the migrations against a copy of existing data **as the role the deploy uses**, with existing ownership and grants. Privilege, ownership and volume-permission changes break on the transition, never on the clean build.

**DATA-10** MUST have a migration that changes who or what runs as (a role, an owner, a container user) verified against both a fresh database and an upgraded one. They fail differently.

## 4. Locks and performance

**DATA-11** MUST use `CREATE INDEX CONCURRENTLY` on any table with real rows, set a `lock_timeout` in migrations, and add constraints as `NOT VALID` then `VALIDATE` so writers are not blocked for the scan.

**DATA-12** SHOULD batch backfills (thousands of rows per transaction, with a pause), never one `UPDATE` over the whole table.

**DATA-13** MUST set a statement timeout on the application role so a runaway query cannot hold a connection forever.

## 5. Row-level security

**DATA-14** SHOULD use PostgreSQL row-level security as a second enforcement layer beneath service-level tenant filters, when the product's isolation failure would be existential. If adopted, the following are mandatory, not optional.

**DATA-15** MUST connect the application as a role that is not a superuser, not the table owner, and does not hold `BYPASSRLS`; and MUST set `FORCE ROW LEVEL SECURITY` so even the owner is bound.

**DATA-16** MUST set the tenant context per transaction or per pooled checkout (`set_config(..., true)` / `SET LOCAL`) so identity cannot leak across a connection pool. Absent context MUST resolve to a sentinel that matches no row.

**DATA-17** MUST cover every table with row security enabled by a negative cross-tenant test, enforced by a coverage test that compares the enabled set to the tested set in both directions.

**DATA-18** MUST pair each policy guard with a sensitivity test that removes the guard and watches the attack succeed; a guard that no test would miss is untested (`06-testing.md`, TEST-22).

**DATA-19** MUST give background workers an explicit tenant resolved from the database, never from the queue payload, and MUST make a zero-row write under a wrong identity a thrown error rather than a silent no-op.

## 6. Seeds and test data

**DATA-20** MUST keep seed data idempotent and separate from schema migrations. Development and demo seeds never run in production.

**DATA-21** SHOULD build test data with factories that have safe defaults and override only the fields under test; each test owns its own tenant or rows so tests cannot see each other.

## 7. Backups and recovery

**DATA-22** MUST write down the recovery point objective (how much data can be lost) and recovery time objective (how long recovery may take) and configure backups to match: point-in-time recovery or base backup plus WAL archiving, stored outside the primary host and in the required jurisdiction.

**DATA-23** MUST run a restore drill into a scratch database on a schedule and record how long it took. Until a restore has been executed and timed, the recovery time is unknown and is recorded as an accepted risk, not estimated as a number.

**DATA-24** MUST verify after any restore or new environment that the queue, workers and application role come up correctly; a restored database that boots the API but not the workers is a silent outage.

## 8. Sources

- Evolutionary Database Design, Sadalage & Fowler (2016): https://martinfowler.com/articles/evodb.html
- Parallel Change (expand/contract), Fowler (2014): https://martinfowler.com/bliki/ParallelChange.html
- PostgreSQL row security policies (current): https://www.postgresql.org/docs/current/ddl-rowsecurity.html
- PostgreSQL continuous archiving and PITR: https://www.postgresql.org/docs/current/continuous-archiving.html
- Safe PostgreSQL migrations (strong_migrations rationale): https://github.com/ankane/strong_migrations
- OWASP Multi-Tenant Security Cheat Sheet: https://cheatsheetseries.owasp.org/cheatsheets/Multi_Tenant_Security_Cheat_Sheet.html
