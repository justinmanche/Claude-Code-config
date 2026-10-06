# 03 — API design

Applies when adding or changing an HTTP endpoint, the OpenAPI contract, a response shape, or the generated client.

Contents: 1 The contract · 2 Resources and verbs · 3 Requests · 4 Responses and errors · 5 Lists · 6 Change and versioning · 7 Sources

## 1. The contract

**API-01** MUST treat the OpenAPI document as the single source of truth for the HTTP contract. A route that is not in it does not exist; a change to a shape is a change to the document first.

**API-02** MUST generate the frontend client from the contract and never hand-edit the generated output (`02-code-quality.md`, CODE-30). A drift check between the document and the generated client is a merge gate.

**API-03** MUST document every endpoint's authentication, the permission it requires, the tenant types it serves and every error code it can return. An undocumented 403 is a support ticket.

## 2. Resources and verbs

**API-04** SHOULD model URLs as nouns in the plural (`/vendors/{id}/contacts`) and use HTTP verbs for actions. A domain action that is not CRUD (`approve`, `submit`) is a sub-resource verb (`POST /questionnaires/{id}/approve`), not a `?action=` parameter.

**API-05** MUST make `GET` and `HEAD` free of side effects and make `PUT` and `DELETE` idempotent. A retried request must not create a second record.

**API-06** SHOULD accept an idempotency key on `POST` endpoints that create money-like or irreversible things (sent emails, submissions, exports).

## 3. Requests

**API-07** MUST validate every parameter, query field and body field at the boundary against a schema that rejects unknown fields. Validation failures return 400 with field-level messages; nothing reaches a service unvalidated.

**API-08** MUST NOT accept `tenant_id`, `role`, `owner_id` or any other authorisation-bearing field from the client when the server can derive it. Mass-assignment payloads are the standard attack.

**API-09** MUST enforce request size limits per endpoint (body, file upload, array length) rather than one global ceiling that is wrong for everything.

## 4. Responses and errors

**API-10** MUST use one error envelope across the whole API (`{ code, message, correlationId, details? }`). Clients branch on `code`, never on message text.

**API-11** MUST return the same 404 for "does not exist" and "exists but not yours", so an attacker cannot enumerate other tenants' ids.

**API-12** MUST keep 403 bodies minimal; do not list the permission that was missing.

**API-13** MUST NOT leak stack traces, SQL, file paths or dependency names in any response in production. The correlation id is what links the response to the log line that holds the detail.

**API-14** SHOULD map status codes consistently: 400 validation, 401 unauthenticated, 403 forbidden, 404 not found, 409 conflict/state, 413 too large, 422 only if the project already uses it, 429 rate limited, 500 defect.

## 5. Lists

**API-15** MUST paginate every list endpoint with a server-side maximum page size (clamp, do not reject). Unbounded lists are a denial-of-service and a memory bug.

**API-16** MUST allow sorting only on an explicit allow-list of columns, mapped in code; the client never names a database column.

**API-17** SHOULD filter server-side with explicit, documented query parameters. A client that downloads everything and filters locally will stop working at the first real customer.

## 6. Change and versioning

**API-18** MUST make changes backwards-compatible by default: add optional fields, never rename or remove one that a shipped client reads. Breaking changes follow expand/contract (`04-data-and-migrations.md`, DATA-08) across releases.

**API-19** SHOULD version only when a consumer outside the repo exists (a public API, a partner). A frontend deployed with its backend does not need versioning; it needs the drift check.

**API-20** MUST keep a human-readable changelog entry for any contract change that an external consumer could notice.

## 7. Sources

- OWASP API Security Top 10 (2023): https://owasp.org/API-Security/editions/2023/en/0x11-t10/
- OWASP REST Security Cheat Sheet: https://cheatsheetseries.owasp.org/cheatsheets/REST_Security_Cheat_Sheet.html
- Microsoft REST API guidelines: https://github.com/microsoft/api-guidelines/blob/vNext/Guidelines.md
- OpenAPI specification 3.1: https://spec.openapis.org/oas/v3.1.0
- RFC 9457 Problem Details for HTTP APIs (2023): https://www.rfc-editor.org/rfc/rfc9457
- Idempotency-Key header draft (IETF): https://datatracker.ietf.org/doc/draft-ietf-httpapi-idempotency-key-header/
