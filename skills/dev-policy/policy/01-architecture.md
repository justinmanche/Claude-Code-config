# 01 — Architecture and module boundaries

Applies when creating a module, service, route group, package or deployable, or when a change crosses one. For a single-developer TypeScript/Node/React/PostgreSQL product; the shape is a modular monolith.

Contents: 1 Shape · 2 Dependency direction · 3 Boundaries · 4 Ports and adapters · 5 The service layer · 6 Transactions and side effects · 7 Data access · 8 When layering is overkill · 9 Sources

## 1. Shape

**ARCH-01** SHOULD build one deployable with enforced internal boundaries (a modular monolith). Microservices and a full Clean/Hexagonal layering are not justified for one developer and one database; they add network, deployment and consistency problems without a second team to isolate.

**ARCH-02** SHOULD organise code by business capability (vendors, questionnaires, evidence, risks) within each tier, not only by technical kind. A reader looking for "how questionnaires are approved" should find one place, not six folders.

## 2. Dependency direction

**ARCH-03** MUST keep dependencies pointing one way: HTTP routes → services → data access → database. Nothing lower imports anything higher.

**ARCH-04** MUST keep framework objects out of domain logic. A service never receives Express `req`/`res`; a React component never contains business rules that the backend also enforces. Services take plain typed inputs plus an actor/tenant context.

**ARCH-05** MUST take the tenant and the actor from the authenticated identity on the server, and pass them explicitly into every service call. Never from a request body, header or URL (see `05-security.md`, SEC-20).

## 3. Boundaries

**ARCH-06** SHOULD give each module a small public surface (an index file or a named service) and treat everything else as private. Other modules MUST NOT import a module's internals.

**ARCH-07** SHOULD enforce boundaries mechanically (ESLint `import/no-restricted-paths` or dependency-cruiser) rather than by convention. _Why:_ an AI agent crosses any boundary that nothing enforces, and a human reviewer does not notice an import line.

**ARCH-08** Routes MUST NOT call another domain's data access directly; cross-domain operations go through the owning service. Services MAY call other services for cross-domain coordination.

## 4. Ports and adapters

**ARCH-09** SHOULD add an abstraction (port) only where a second implementation exists or is funded: the AI provider, email delivery, file storage, a ticketing system. Everything else calls the concrete thing.

**ARCH-10** MUST NOT introduce a generic `Repository<T>` over PostgreSQL unless the store will actually be swapped. Name real queries in small data-access functions instead; a generic layer hides the SQL that matters.

## 5. The service layer

**ARCH-11** MUST keep route handlers thin: authenticate (via router-level middleware), validate input, call one service function, map the result to HTTP. No SQL and no business rules in a handler.

**ARCH-12** MUST put business rules, authorisation decisions and multi-step workflows in services. A service method is the unit a test exercises and the unit an audit event describes.

**ARCH-13** MUST handle errors centrally: services throw typed errors from one hierarchy; a single error middleware maps them to status codes and response shapes. Async handlers MUST propagate rejections (`next(error)`), never answer `res.status(500)` inline.

## 6. Transactions and side effects

**ARCH-14** MUST own the transaction boundary in the service: one use case, one transaction, the client passed down to every data-access call inside it. `BEGIN`/`COMMIT`/`ROLLBACK` with `release()` in `finally`.

**ARCH-15** MUST write the audit event inside the same transaction as the mutation it describes, so neither exists without the other.

**ARCH-16** SHOULD perform side effects that leave the database (email, queue jobs, webhooks) after commit, or through an outbox table the worker drains. A job enqueued before a rollback runs against data that never existed.

## 7. Data access

**ARCH-17** MUST use parameterised SQL. Dynamic identifiers (sort columns, table names) come from a module-level allow-list, never from input.

**ARCH-18** SHOULD keep the SQL visible and close to the service that owns it. Hiding it behind layers of mappers that differ in nothing is pass-through plumbing (see ARCH-19).

## 8. When layering is overkill

**ARCH-19** AVOID DTOs mapped through four layers when nothing changes between them. If every layer is pass-through, delete the layers. Reintroduce one when a real difference appears.

**ARCH-20** AVOID "just in case" interfaces, factories and event buses with one subscriber. See `00-principles.md`, PRIN-06.

## 9. Sources

- Hexagonal architecture, Cockburn (2005): https://alistair.cockburn.us/hexagonal-architecture/
- The Clean Architecture, Martin (2012): https://blog.cleancoder.com/uncle-bob/2012/08/13/the-clean-architecture.html
- Deconstructing the monolith, Shopify (2019): https://shopify.engineering/deconstructing-monolith-designing-software-maximizes-developer-productivity
- Enforcing modularity with Packwerk, Shopify (2020): https://shopify.engineering/enforcing-modularity-rails-apps-packwerk
- Node.js best practices §1 structure, Goldberg et al. (2026): https://github.com/goldbergyoni/nodebestpractices
- Service Layer and Repository, Fowler (2002): https://martinfowler.com/eaaCatalog/serviceLayer.html, https://martinfowler.com/eaaCatalog/repository.html
- Vertical slice architecture, Bogard (2018): https://www.jimmybogard.com/vertical-slice-architecture/
