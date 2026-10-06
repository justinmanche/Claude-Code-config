# 09 — Operations, configuration and infrastructure

Applies to configuration, environment variables, logging, health checks, alerting, runbooks, incidents, dependencies, container images and infrastructure as code.

Contents: 1 Configuration · 2 Build and runtime · 3 Logging · 4 Health checks · 5 Alerting and SLOs · 6 Runbooks and incidents · 7 Dependencies and images · 8 Infrastructure as code · 9 Sources

## 1. Configuration

**OPS-01** MUST keep everything that varies by deployment (URLs, credentials, flag defaults, limits) in the environment or a secret store, never in code or images. Test: could the repository be made public right now without leaking anything?

**OPS-02** MUST validate configuration at startup with a typed schema and fail fast with a clear message. The process refuses to boot if a required value is missing; it does not fail on the first request.

**OPS-03** SHOULD keep development, test and production as alike as possible: same database major version, same container topology, same base image. Differences are listed in one place.

## 2. Build and runtime

**OPS-04** MUST keep application processes stateless; anything that must persist goes to the database or object storage. Logs go to stdout.

**OPS-05** MUST run administrative tasks (migrations, seeds, one-off fixes) as one-off processes from the same build, never by hand against a shared database.

**OPS-06** MUST have every container run as a non-root user, define a health check, carry only production dependencies, pin its base image by version (SHOULD by digest) and keep a tight `.dockerignore`.

## 3. Logging

**OPS-07** MUST emit structured JSON logs with a request or trace id, the tenant id and the user id on every line that relates to a request, through one logger. No `console.log` in server code.

**OPS-08** MUST NEVER log secrets, tokens, session ids, personal data in full or record content; redact by allow-list (`05-security.md`, SEC-41).

**OPS-09** MUST make silent failures loud: a zero-row write where one row was expected, a job whose tenant could not be resolved, an unattached worker, a swallowed promise rejection, each logs at error level with enough context to find the cause.

**OPS-10** SHOULD adopt OpenTelemetry (HTTP, framework and database auto-instrumentation) once request paths span a queue or a second service; before that, structured logs with correlation ids are enough.

## 4. Health checks

**OPS-11** MUST expose separate checks: liveness (the process responds, no dependencies checked), readiness (database reachable, migrations applied, workers attached), and an authenticated deep check for queue, mail and AI provider.

**OPS-12** MUST NOT let the container restart because the database is down: liveness never depends on a dependency. Readiness is what takes the instance out of rotation.

**OPS-13** MUST point the post-deploy smoke test and any uptime probe at the deep check, not at liveness. "The process is up" has disguised three real outages.

## 5. Alerting and SLOs

**OPS-14** MUST alert on symptoms users feel (availability, error rate, latency, failed jobs) and send causes (CPU, disk, connections) to dashboards or tickets. Every page is actionable and links to a runbook section.

**OPS-15** MUST prove alert delivery end to end when an alert channel is created (send a test, see it arrive). An alert that has never delivered is not monitoring; a receiver that reads "enabled" is not verified.

**OPS-16** SHOULD define one or two service-level objectives even for a small product (for example 99.5 % of requests non-5xx within 1 s over 30 days) and alert on error-budget burn rather than single thresholds, once traffic makes thresholds meaningful.

**OPS-17** MUST record what is deliberately not monitored as an accepted risk with the condition that reopens it, in the risk register, not in a plan.

## 6. Runbooks and incidents

**OPS-18** MUST structure every runbook entry as: symptom or alert → impact → diagnosis (copy-pasteable commands) → mitigation → verification → escalation. Written against the environment that exists; where production would differ, say so.

**OPS-19** MUST write a blameless incident record for every user-visible incident: timeline, impact, contributing factors, action items with owners, and the fact that symptom and cause differed if they did. Track action items to closure.

**OPS-20** MUST have a written, tested rotation procedure for every secret before it is needed, including what each rotation invalidates (sessions, encrypted fields).

## 7. Dependencies and images

**OPS-21** MUST pin the runtime to an active or maintenance LTS line (`engines`, `.nvmrc`, base image) and upgrade before end of life.

**OPS-22** SHOULD upgrade dependencies in small, regular batches (weekly or monthly), with a cooldown on brand-new versions (`05-security.md`, SEC-36). Deprecation warnings become backlog items with a deadline, not noise.

**OPS-23** MUST keep lockfiles committed and reproducible installs (`npm ci`) everywhere a build happens.

## 8. Infrastructure as code

**OPS-24** MUST define all infrastructure in code in the repository. A portal change is an emergency measure that is ported back to code the same day.

**OPS-25** MUST preview every apply (`what-if` / `plan`) and read the output before applying. SHOULD run the linter with warnings as errors and a rules engine (PSRule for Azure, or equivalent) as a gate.

**OPS-26** MUST use managed identities with least-privilege role assignments scoped to the resource group or resource. AVOID long-lived service-principal secrets and broad Owner or Contributor grants.

**OPS-27** MUST tag every resource (environment, owner, managed-by) and set budgets with alerts. Budgets alert; they do not cap. Non-production environments SHOULD have power schedules.

**OPS-28** SHOULD prefer the platform's drift-tracking mechanism (deployment stacks or state files with plan) so removed resources and manual changes are visible, and keep per-environment parameter files with secrets as vault references only.

**OPS-29** MUST write recovery targets as capability statements derived from the configuration (retention days, geo-redundancy, high availability), and keep the untested parts honest (`04-data-and-migrations.md`, DATA-23).

## 9. Sources

- The Twelve-Factor App (2011; open-sourced 2024): https://12factor.net/
- Health Endpoint Monitoring pattern, Microsoft: https://learn.microsoft.com/azure/architecture/patterns/health-endpoint-monitoring
- Monitoring distributed systems, Google SRE book (2016): https://sre.google/sre-book/monitoring-distributed-systems/
- Alerting on SLOs, SRE workbook (2018): https://sre.google/workbook/alerting-on-slos/
- Postmortem culture, SRE book: https://sre.google/sre-book/postmortem-culture/
- OpenTelemetry for JavaScript: https://opentelemetry.io/docs/languages/js/
- Docker build best practices: https://docs.docker.com/build/building/best-practices/
- Node.js release schedule: https://nodejs.org/en/about/previous-releases
- Bicep best practices and deployment stacks, Microsoft: https://learn.microsoft.com/azure/azure-resource-manager/bicep/best-practices, https://learn.microsoft.com/azure/azure-resource-manager/bicep/deployment-stacks
- PSRule for Azure: https://azure.github.io/PSRule.Rules.Azure/
- Azure Key Vault best practices: https://learn.microsoft.com/azure/key-vault/general/best-practices
