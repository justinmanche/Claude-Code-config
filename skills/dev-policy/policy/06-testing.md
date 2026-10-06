# 06 — Testing and verification

Applies when writing or changing any test, when changing code that has tests, and before declaring anything done. The standing rule: a change is finished when it is verified at the layer the user touches, with evidence, not when a unit test passes.

Contents: 1 Strategy · 2 What goes where · 3 Test design · 4 Flaky tests · 5 Coverage · 6 Test-first and regression · 7 Security and isolation tests · 8 Never weaken a test · 9 Verification beyond tests · 10 Sources

## 1. Strategy

**TEST-01** MUST choose the test boundary by risk and cost, not by a shape. The pyramid, trophy and honeycomb disagree mostly about what "unit" means. Decide per behaviour: what would catch the bug that would actually hurt here?

**TEST-02** MUST test behaviour through the public interface, not private methods or call sequences. A refactor that keeps behaviour must leave the tests green.

**TEST-03** SHOULD classify tests by size (Google): small = one process, no I/O; medium = one machine, a local database allowed; large = deployed systems. Merge gates run small and medium; large runs before release and after deploy.

## 2. What goes where

**TEST-04** MUST test anything that touches SQL (queries, constraints, transactions, row security, migrations, audit writes) against a real PostgreSQL. A mocked query proves the code built a string, not that the column, join, enum or policy exists.

**TEST-05** SHOULD keep pure logic (scoring, state machines, validators, formatters) in fast unit tests with no I/O and no mocks.

**TEST-06** SHOULD test HTTP routes through the real middleware chain (authentication, validation, tenant scoping) with the service stubbed at its boundary, and stub only the true external edge: AI provider, email, object storage.

**TEST-07** SHOULD limit end-to-end browser tests to critical journeys and cross-role handoffs. They are slow, flaky and localise faults poorly; they are not where business rules are proven.

**TEST-08** AVOID unit tests that assert on SQL text (`expect(query).toContain('WHERE tenant_id')`). They couple the test to the implementation and still miss a wrong column. Prove the behaviour against the database instead.

## 3. Test design

**TEST-09** MUST structure each test as arrange, act, assert, with one behaviour per test. Several assertions are fine when they describe one outcome.

**TEST-10** MUST name tests as behaviour plus condition: `rejects submit when instance is already approved`, not `test submit 2`.

**TEST-11** AVOID logic in tests (loops, conditionals, computed expected values). Literal, obvious expected values beat a clever helper (DAMP over DRY in tests).

**TEST-12** SHOULD build test data with factories that have safe defaults and override only what matters. AVOID large shared fixtures that no single test fully understands.

**TEST-13** MUST make tests deterministic: inject the clock and id/random sources, give each test its own tenant or rows, never depend on order.

**TEST-14** SHOULD assert on state and outputs, not interactions, unless the interaction is the contract (an audit row was written; an email was enqueued).

**TEST-15** MUST keep test placement with the implementation milestone: a change is not complete until its tests pass. Tests are never a separate later task.

## 4. Flaky tests

**TEST-16** MUST treat a flaky test as a bug with an owner. The usual causes, in order: waiting on async work, concurrency, order dependence, time, network, unordered collections.

**TEST-17** MUST replace sleeps with condition waits (web-first assertions in the browser, polling on database state elsewhere).

**TEST-18** SHOULD quarantine a confirmed flaky test out of the gating suite with a ticket and a fix-or-delete deadline. A red build people ignore is worse than no build.

**TEST-19** SHOULD allow automatic retries only in end-to-end suites, reported separately as "passed on retry". AVOID retries in unit or integration suites; there they hide real races.

## 5. Coverage

**TEST-20** MUST NOT treat a coverage percentage as a goal. Coverage correlates only weakly with fault detection once suite size is controlled for. Use it to find untested authorisation, tenancy and error paths in the diff.

**TEST-21** SHOULD enforce a ratchet: a committed per-workspace baseline that cannot drop, and higher expectations for changed lines than for the whole repository. SHOULD run mutation testing on high-risk modules or on the diff, not the whole repository.

## 6. Test-first and regression

**TEST-22** MUST give every security or business-rule guard a sensitivity test: remove the guard (or run the mutation) and confirm at least one test fails. A guard that no test would miss is untested, whatever the coverage report says.

**TEST-23** MUST write a regression test for every bug fix and see it fail before the fix, then pass after.

**TEST-24** SHOULD write the test first when the behaviour is specified in advance (a bug, a contract, a state transition). Test-after is acceptable for exploratory UI work done in small increments; what matters is small, steady cycles, not the order.

## 7. Security and isolation tests

**TEST-25** MUST have a negative cross-tenant test for every tenant-scoped endpoint and table: tenant B's credentials with tenant A's id → 404 or 403 and no data, across read, list, update, delete and nested routes.

**TEST-26** MUST test the denied cells of the role × action matrix, not only the allowed ones (member vs admin, vendor vs customer, unauthenticated).

**TEST-27** MUST run row-security tests as the application role (never superuser or owner), and include the "no tenant context" case, which must return nothing rather than everything.

**TEST-28** SHOULD generate authorisation cases from an inventory of routes and tables, so a new endpoint without a test fails a meta-test rather than being forgotten.

## 8. Never weaken a test

**TEST-29** MUST NOT edit, loosen, skip or delete an existing test to get to green unless the specification changed, and then the change description says why. Language-model agents demonstrably "cheat" this way; a reviewer checks the test diff before the code diff. `.only` never ships; `.skip` carries an issue reference.

## 9. Verification beyond tests

**TEST-30** MUST verify a user-visible change by driving the same path the user does (browser → API → database) on the deployed environment before calling it done. A middleware or guard upstream of the unit you edited can silently invalidate the fix.

**TEST-31** MUST put at least one regression test at the outermost layer that was actually failing, not only at the inner function.

**TEST-32** MUST smoke-test after every deploy: deep health (database, migrations applied, workers attached), a login, one read and one write on a critical path. A health route that only proves the process is up is not a smoke test.

**TEST-33** MUST test the upgrade path for any change to roles, ownership, container users, volumes or required secrets: a fresh install passes while the transition breaks. Rehearse against a copy of the existing state.

**TEST-34** SHOULD keep a written manual QA playbook for exploratory and cross-role journeys (real email links, real files, AI paths) and promote every bug it finds into an automated regression test. Clear caches before re-verifying so the new build, not the old one, is under test.

**TEST-35** MUST show evidence, not claims: the command that ran and its output, the request made and the response seen. "Tests pass" without output is not verification.

## 10. Sources

- Test shapes, Fowler (2021): https://martinfowler.com/articles/2021-test-shapes.html
- Test sizes, Google Testing Blog (2010): https://testing.googleblog.com/2010/12/test-sizes.html
- Just say no to more end-to-end tests, Google (2015): https://testing.googleblog.com/2015/04/just-say-no-to-more-end-to-end-tests.html
- Testing trophy, Dodds (2021): https://kentcdodds.com/blog/the-testing-trophy-and-testing-classifications
- Software Engineering at Google, ch. 12 Unit Testing (2020): https://abseil.io/resources/swe-book/html/ch12.html
- xUnit Test Patterns, test smells, Meszaros (2007): http://xunitpatterns.com/Test%20Smells.html
- Eradicating non-determinism in tests, Fowler (2011): https://martinfowler.com/articles/nonDeterminism.html
- Flaky tests at Google (2016): https://testing.googleblog.com/2016/05/flaky-tests-at-google-and-how-we.html
- Code coverage best practices, Google (2020): https://testing.googleblog.com/2020/08/code-coverage-best-practices.html
- Coverage is not strongly correlated with effectiveness, Inozemtseva & Holmes (ICSE 2014): https://www.cs.ubc.ca/~rtholmes/papers/icse_2014_inozemtseva.pdf
- Mutation testing at Google (2018): https://research.google/pubs/state-of-mutation-testing-at-google/
- TDD evidence, Fucci et al. (TSE 2017): https://arxiv.org/abs/1611.05994
- ImpossibleBench, agents gaming tests (2025): https://arxiv.org/abs/2510.20270
- QA in production, Fowler (2017): https://martinfowler.com/articles/qa-in-production.html
- OWASP API1 Broken Object Level Authorization (2023): https://owasp.org/API-Security/editions/2023/en/0xa1-broken-object-level-authorization/
