# Step 4 Architecture

## Scope

This document describes the Step 1 foundation, Step 2 identity/authorization, Step 3 governed
synthetic-document ingestion, and Step 4 secure chunk storage and deterministic keyword retrieval.
Embeddings and all later capabilities remain absent.

```mermaid
flowchart LR
    Browser[React application] -->|login or bearer token| API[FastAPI]
    API --> RequestID[Request ID middleware]
    RequestID --> Auth[Authentication dependency]
    Auth --> JWT[Strict JWT validation]
    JWT --> Identity[Reload user memberships and grants]
    Identity --> Scope[Frozen AuthorizationScope]
    Scope --> Policy[Deterministic RBAC plus ABAC]
    Policy --> Ingestion[Governed document service]
    Ingestion --> Validator[Bounded format validation]
    Validator --> Parser[Resource-limited parser worker]
    Parser --> ObjectStore[Generated-key local object storage]
    Parser --> Parsed[(Versioned parsed provenance)]
    Ingestion -->|approve in one transaction| Chunker[Deterministic chunker]
    Chunker --> Chunks[(ACL-copied document chunks)]
    Browser -->|development search| SearchAPI[Authorized search API]
    SearchAPI --> Scope
    Scope --> Search[Scoped PostgreSQL full-text repository]
    Search --> Chunks
    Identity --> SQLAlchemy[SQLAlchemy async engine]
    RequestID --> Route[Typed health/readiness route]
    Route -->|/ready only| SQLAlchemy
    SQLAlchemy --> PostgreSQL[(PostgreSQL + pgvector)]
    Auth --> Envelope[JSON success/error envelope]
    Route --> Envelope
    Envelope --> Browser
    Alembic[Alembic] -->|schema migrations| PostgreSQL
```

## Authentication and authorization path

1. The browser posts only email and password to `/api/auth/login`; extra fields are rejected.
2. The backend performs Argon2 verification. Unknown users take a dummy verification path and
   receive the same error as a wrong password.
3. A successful login receives a signed 15-minute JWT containing only `sub`, `iss`, `aud`, `iat`,
   `exp`, and `jti`.
4. `/api/auth/me` accepts a bearer token and validates the fixed algorithm, signature, issuer,
   audience, required claims, and expiry.
5. The backend reloads the user, all active memberships, tenant status, role, primary department,
   and grants from PostgreSQL. Token claims never supply authorization.
6. The repository creates frozen `TrustedIdentity` and `AuthorizationScope` objects. Each scope grant
   binds one membership to one workspace, its companies, departments, and capabilities.
7. Policy code intersects capability, workspace, company, department, and role. Missing information
   denies by default and every result has a stable reason code.
8. The frontend displays the returned scope. Its protected route improves UX but does not authorize
   backend data.

```mermaid
flowchart TD
    Token[Bearer token: subject only] --> Validate[Signature issuer audience expiry]
    Validate --> User[(Active user)]
    User --> Membership[(Active membership)]
    Membership --> Workspace[(Workspace grant)]
    Membership --> Company[(Company grant)]
    Membership --> Department[(Workspace-bound department grant)]
    Workspace --> Effective[Immutable effective scope]
    Company --> Effective
    Department --> Effective
    Effective --> Decision{Policy request}
    Decision -->|all required grants match| Allow[Reason-coded ALLOW]
    Decision -->|anything missing or conflicting| Deny[Reason-coded DENY]
```

## Backend request path

1. Uvicorn passes a request to FastAPI.
2. `RequestIDMiddleware` validates `X-Request-ID` or creates a UUID.
3. The route returns a Pydantic response model. `/ready` first calls the database readiness probe.
4. Expected and unexpected exceptions pass through centralized safe-error handlers.
5. The response includes the same request ID in JSON and the `X-Request-ID` header.
6. A structured log records request metadata after completion, without query strings or bodies.

Success shape:

```json
{
  "data": { "status": "healthy" },
  "request_id": "f6d8..."
}
```

Error shape:

```json
{
  "error": {
    "code": "service_unavailable",
    "message": "Service is not ready."
  },
  "request_id": "f6d8..."
}
```

## Frontend state flow

React Router renders the shared header, route outlet, and footer. The home route starts one abortable
health request through `getJson`. The client validates the envelope's basic shape and converts HTTP,
network, and invalid-response failures into a typed `ApiError`. `BackendHealth` renders a distinct
loading, online, or offline state.

The nested `/admin/documents` route mounts only when a current grant contains `MANAGE_UPLOADS`.
After mounting it loads a dedicated backend-derived options contract and the scoped management
library. The form cascades tenant to company and department to the allowed
visibility/classification pair. Native XHR reports upload-byte progress; subsequent job polling is
recursive, abortable, and non-overlapping. The page owns selection, preview, mutations, and refresh
state while child upload, library, preview, badge, and deletion components remain controlled.

In development builds, `/development/search` mounts only when a current grant contains
`QUERY_DOCUMENTS`. It posts a normalized bounded query and `top_k` to the development-only backend
endpoint. The page displays the active scope and renders only returned IDs, bounded excerpts,
metadata, provenance, and scores. It performs no client-side authorization filtering. Production
frontend builds omit the route, navigation, page, and API module.

## Document ingestion path

1. The route validates strict JSON metadata inside multipart form data, validates the idempotency
   header, and authorizes the target workspace/company before reading the file body.
2. Validation bounds bytes and checks the sanitized filename, extension, declared MIME, signature,
   PDF safety, CSV structure, and OOXML container contents. Invalid attempts persist only safe
   metadata and a stable failure code.
3. Accepted bytes receive a generated UUID-only storage key. The local adapter confines writes to
   its root, uses private permissions and an atomic promotion, and verifies size/checksum.
4. A spawned worker applies wall-clock and process resource limits. PDF output contains numbered
   pages. XLSX/CSV output contains sheets, numbered rows, coordinates, value kinds, and a
   `formula_like` flag; it never executes formulas.
5. The service writes parsed provenance and advances the version/job together to `PREVIEW_READY`.
   Version-addressed preview is then available; approval or rejection is legal only from that state.
   Approval locks the version row, transitions it to `APPROVED`, deterministically chunks parsed
   content, deactivates old-version chunks, installs new active chunks, updates the current-approved
   pointer, writes metadata-only audit events, and commits once.
6. Initial uploads deduplicate on checksum plus canonical scope metadata. A separate endpoint creates
   explicit versions. Actor/idempotency-key plus request fingerprint makes exact retries stable and
   conflicting reuse fail safely.
7. Rejection creates no chunks and deactivates any matching rows defensively. Deletion marks the
   logical document and every version `DELETED`, clears the approved pointer, deactivates every
   chunk, commits immediate unavailability, and then performs best-effort object cleanup with
   audited failures.

```mermaid
stateDiagram-v2
    [*] --> UPLOADED
    UPLOADED --> VALIDATING
    VALIDATING --> PARSING
    VALIDATING --> VALIDATION_FAILED
    PARSING --> PREVIEW_READY
    PARSING --> PARSING_FAILED
    PREVIEW_READY --> APPROVED
    PREVIEW_READY --> REJECTED
    UPLOADED --> DELETED
    VALIDATING --> DELETED
    PARSING --> DELETED
    PREVIEW_READY --> DELETED
    APPROVED --> DELETED
    REJECTED --> DELETED
    VALIDATION_FAILED --> DELETED
    PARSING_FAILED --> DELETED
```

## Database flow

The `db` Compose service exposes local PostgreSQL. Alembic reads the same environment-backed URL as
the application. Its initial reversible migration enables pgvector; SQLAlchemy metadata is empty.
Step 2 adds tenants, companies, departments, roles, users, memberships, and three dimension-specific
grant tables. Step 3 adds logical documents, versions, ingestion jobs, parsed pages, parsed sheets,
rows, cells, and document audit events. Step 4 adds `document_chunks`, copied ACL/lifecycle columns,
a generated `TSVECTOR`, an ACL/lifecycle B-tree index, and a GIN full-text index. The development
seed writes only synthetic identity rows; documents and chunks are created through governed
ingestion. `/ready` still executes only `SELECT 1`.

## Authorized search path

1. FastAPI authenticates the bearer subject and reloads the current database scope.
2. The service denies users such as Nora who have no `QUERY_DOCUMENTS` capability; no repository
   search runs on this path.
3. Strict request validation accepts only `query` (1–500 normalized characters) and `top_k` (1–20).
   Identity, tenant, company, department, role, document, version, and scope fields are forbidden.
4. Every public production retrieval repository method requires `AuthorizationScope` as a mandatory
   argument. Grant-correlated SQL predicates bind workspace, company, and allowed departments.
5. The same SQL statement requires exact visibility/classification pairing, active tenant/company,
   copied and authoritative approval/deletion state, active chunks, and the document's current
   approved version before `plainto_tsquery('simple', query)`, rank, order, and limit are applied.
6. The repository materializes at most 20 rows with a maximum 500-character excerpt. The service
   returns chunk/document/version IDs, source metadata, page or sheet/row/cell provenance, and score.
7. The audit event contains actor/request/resource IDs and counts only. Query and document content
   are absent from audit metadata and logs.

## Trust boundaries

- The browser and all request headers are untrusted.
- Environment configuration is operational input and is validated by Pydantic.
- PostgreSQL connectivity is not exposed as raw errors.
- The request ID is correlation metadata, never proof of identity or authority.
- JWTs prove only a subject reference; database state determines current authority.
- Workspace, company, and department grants remain bound rather than flattened into client-editable
  arrays.
- A role alone never grants query access. Nora's Admin role has no query department grant.
- Uvicorn's query-string access log is disabled; the application emits metadata-only request logs.
- Uploaded filenames and file contents never become storage paths, authority inputs, audit metadata,
  or log fields. Generated storage keys are server-owned.
- Approval changes lifecycle state only. It does not grant `QUERY_DOCUMENTS` or invoke retrieval.
- Parser output is untrusted display data and is rendered as React text, never HTML or executable
  spreadsheet content.
- Chunks inherit authorization metadata; they cannot widen a document's visibility or classification.
- Search authorization lives in SQL-backed repository code. UI route hiding is only a convenience.
- Forbidden candidate text is never returned to the service, UI, audit event, or request log.
- The authorized-search API is registered only for `development` and `test` environments.
