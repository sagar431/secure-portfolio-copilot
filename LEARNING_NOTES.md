# Learning Notes

## Step 1 / Milestone 0 — Development foundation

### What problem this milestone solves

It gives every later feature a reproducible API, database, browser application, error contract, and
test harness. It proves that the three local processes can communicate before product complexity is
introduced.

### Frontend flow

The browser starts in `src/main.tsx`, mounts React Router, and renders `ApplicationLayout`. The home
route renders `BackendHealth`, which calls the typed API client. The component renders loading,
online, or safe offline states. It never decides whether the backend is database-ready; `/health` is
intentionally only a process check.

### Backend flow

FastAPI receives `GET /health`. Request ID middleware accepts a safe caller-provided ID or generates
one, stores it on request state, and adds it to the response. The route creates a typed success
envelope. The middleware records method, path, status, duration, and request ID without recording a
body. Registered exception handlers convert failures to a consistent error envelope.

For `GET /ready`, the same flow includes an asynchronous SQLAlchemy `SELECT 1`. A failed connection
returns a generic HTTP 503 response without database details.

### Database flow

Docker Compose starts PostgreSQL from a pgvector-enabled image. SQLAlchemy owns the async connection
engine. Alembic's baseline migration creates the `vector` extension; there are no application tables
or rows in this milestone.

### Heuristic versus LLM ownership

All current behavior is deterministic. No LLM exists. Input validation, request-ID acceptance,
readiness, status selection, and error sanitization are ordinary typed code.

### MCP tools involved

None. MCP is explicitly outside Step 1.

### Security invariant

An external error must not reveal stack traces, connection strings, request bodies, or internal
exception messages. Logs contain operational metadata and a request ID, but not request bodies.

### Failure example

If PostgreSQL is stopped, `/health` remains HTTP 200 because the API process is alive, while `/ready`
returns HTTP 503 with `service_unavailable`. The UI displays a safe message if its health request
cannot reach the backend.

### Questions Sagar should be able to answer

1. Why are `/health` and `/ready` separate?
2. Where does a request ID originate, and where is it returned?
3. What does the frontend do when `fetch` fails or the backend returns an error envelope?
4. Which configuration values come from `.env`?
5. What does the first Alembic migration change?
6. Which request metadata is logged, and which data is deliberately excluded?
7. Why are there no domain tables or authentication checks yet?

## Step 2 — Identity, tenancy, departments, and policy engine

### What problem this milestone solves

It turns an untrusted browser login into a short-lived identity reference and reconstructs current
authorization from normalized database grants. This proves tenant, company, and department
isolation before any governed document exists.

### Frontend flow

`AuthProvider` checks for a session token and calls `/api/auth/me`. An anonymous or invalid session
is sent to `/login`. Login posts only email/password, validates the returned token immediately with
`/api/auth/me`, and then renders the protected home route. The browser displays tenant, role,
primary department, companies, query departments, and capabilities returned by the backend. Demo
cards are compiled only in Vite development mode and fill email—not the password. Logout clears the
session token and returns to the protected-route redirect.

### Backend flow

`POST /api/auth/login` normalizes the email, follows the same Argon2 verification path for known and
unknown users, requires an active user with an effective active grant, and issues a 15-minute HS256
JWT. The token contains `sub`, `iss`, `aud`, `iat`, `exp`, and `jti`; it contains no tenant, role,
department, company, or permission claims.

`GET /api/auth/me` verifies the fixed algorithm, signature, issuer, audience, required claims, and
expiry. It then loads the user, memberships, tenants, roles, departments, and all grants from the
database. A disabled user or revoked last membership invalidates an already-issued token.

### Database flow

The login lookup reads `users` plus membership/grant relationships. Scope construction intersects
active workspace, company, and workspace-bound department grants. Nora's Platform membership has
separate platform-administration and scoped upload-management grants, while ordinary users have
query grants only for their tenant/company/departments. The seed writes 3 tenants, 2 companies, 5
departments, 4 roles, 6 users, 6 memberships, 8 workspace grants, 7 company grants, and 11 department
grants.

### Heuristic versus LLM ownership

Everything remains deterministic Python and SQL. Password verification, token validation,
membership reload, scope construction, policy intersections, decision reason codes, frontend route
state, and safe errors use no prompt or LLM.

### MCP tools involved

None. MCP remains outside Step 2.

### Security invariant

The browser and JWT cannot define effective authorization. A protected request is authorized only
from an active database user and immutable, database-derived grants. Admin/upload authority never
implies query authority.

### Failure example

Alice may send `tenant=atlas`, `role=admin`, `department=legal`, an Atlas company, and Nora's user ID.
The login body rejects extra fields; forged query parameters and headers do not affect `/api/auth/me`.
The returned identity remains Alice with Orion Finance + Shared. A direct policy request for Atlas,
Orion Legal, or an Atlas company returns a reason-coded denial.

### Questions Sagar should be able to answer

1. Why are authorization claims deliberately absent from the JWT?
2. Which database changes invalidate an existing token?
3. Why do workspace, company, and department grants remain separate?
4. Why does Maya receive Legal access while Alice does not?
5. Why can Nora manage future uploads without querying documents?
6. How do unknown-user and wrong-password flows avoid user enumeration?
7. Which checks make an expired or wrong-audience token fail?
8. Why is the React protected route not treated as a security boundary?

## Step 3 — Governed document ingestion

### What problem this milestone solves

It turns synthetic PDF/XLSX/CSV files into bounded, attributable, previewable document versions
without yet making them queryable. The central problem is not simply file upload: it is preserving
tenant/company/classification authority and source provenance through validation, parsing, review,
versioning, and deletion.

### Frontend flow

`CapabilityRoute` mounts `/admin/documents` only when `/api/auth/me` includes `MANAGE_UPLOADS` in at
least one grant. The page then asks `/api/admin/ingestion/options` for manageable tenant/company
choices and canonical classification pairs; it never builds scope from the home membership or JWT.
Changing tenant resets company, and changing department/visibility resets classification to a
backend-published combination. Explicit version upload locks all canonical document metadata.

Native XHR reports upload-byte progress while carrying bearer auth and a generated idempotency key.
After the bytes reach 100%, the UI switches from upload progress to backend ingestion status and
polls without overlapping requests. A version can be approved or rejected only after its preview
request succeeds. PDF content is shown page by page; spreadsheet content is bounded and shows sheet,
row, and coordinate provenance. React renders every value as text, including formula-like strings.

### Backend flow

The multipart route parses strict JSON metadata and authorizes the target workspace/company before
reading bytes. The service computes a request fingerprint, checks actor-scoped idempotency, validates
the file, generates a storage key, stores verified bytes, invokes the resource-limited parser, and
persists parsed provenance. Version and ingestion-job state advance together. Expected failures
become stable API codes and metadata-only audit events; they do not expose content, paths, parser
details, or storage keys.

Initial upload checksum deduplication includes canonical scope metadata and only reuses an existing
preview-ready or approved version. Creating a deliberate next version uses
`POST /api/admin/documents/{document_id}/versions`; scope metadata cannot change. Preview, approve,
and reject are version-addressed so an action cannot silently select the wrong version. Delete marks
the logical document and all versions unavailable before best-effort object cleanup.

### Database flow

`documents` stores the canonical scope/classification tuple and current-approved pointer.
`document_versions` stores immutable file metadata, checksum, safe storage key, counts, lifecycle,
and reviewer attribution. `ingestion_jobs` mirrors processing state and a safe failure code.
`parsed_pages` preserves PDF page order; `parsed_sheets`, `parsed_rows`, and `parsed_cells` preserve
spreadsheet location. `document_audit_events` stores actor, resource identifiers, outcome, reason,
and request ID without file content or filenames.

### Heuristic versus LLM ownership

Everything remains deterministic. Classification validation is an exact lookup, file safety uses
format rules and hard limits, parsing uses maintained local libraries, lifecycle changes use a
finite state machine, and policy uses the Step 2 engine. No LLM decides metadata, safety, parsing,
approval, or access.

### MCP tools involved

None. MCP remains outside Step 3.

### Security invariant

A browser-selected file may influence only bounded parsed display data. It cannot choose authority,
storage paths, executable formulas, HTML, lifecycle transitions, or query access. `MANAGE_UPLOADS`
does not imply `QUERY_DOCUMENTS`, and approval does not activate retrieval.

### Failure example

Renaming arbitrary text to `report.pdf` and declaring `application/pdf` fails signature validation.
The backend records a `VALIDATION_FAILED` attempt with a stable safe code and no raw bytes or host
path in the response/log. Retrying with the same idempotency key does not create another version.
Alice cannot use Nora's tenant/company IDs to bypass the denial because authorization occurs from
Alice's freshly loaded database grants before the route reads the file.

### Questions Sagar should be able to answer

1. Why does the upload form use a dedicated options endpoint instead of `/api/auth/me`?
2. Which checks run before parsing a PDF or XLSX, and which limits bound decompression?
3. Why are preview, approval, and rejection version-addressed?
4. What differs between initial checksum deduplication, idempotent retry, and explicit new version?
5. Which states may transition to `APPROVED`, `REJECTED`, and `DELETED`?
6. How are spreadsheet formulas kept inert while preserving provenance?
7. Why is deletion committed before object cleanup, and what happens if cleanup fails?
8. Why can Nora approve a document but still not query it?
9. Which data is retained for a failed validation attempt, and which data is deliberately absent?
10. What remains for Step 4, and why is none of it implemented here?

## Step 4 — Secure chunks and deterministic keyword search

### What problem this step solves

It makes approved synthetic documents searchable without weakening the authorization boundary.
Parsed content is converted into bounded evidence units whose source location and effective ACL stay
attached, then PostgreSQL ranks only candidates that match the authenticated user's current scope
and the authoritative document lifecycle.

### Frontend flow

In a development build, `ApplicationLayout` shows **Authorized search** only when the current
database-derived grants include `QUERY_DOCUMENTS`. `CapabilityRoute` prevents Nora from mounting the
page; direct navigation returns home without a search request. The form sends only a normalized
query and bounded `top_k`. It shows loading, indexing/count, empty, and safe error states, then
renders the backend result list as inert React text with IDs, copied metadata, provenance, and score.
The browser does not receive or filter forbidden candidates. Production builds omit the feature.

### Backend flow

Approval locks the managed version, performs the legal `PREVIEW_READY -> APPROVED` transition, sets
the current-approved pointer, constructs a typed parsed-document snapshot, and calls the pure
deterministic chunker. The index adapter validates that every generated chunk matches the document,
version, ACL, approval, deletion, and active state. It deactivates old chunks, inserts new chunks,
writes metadata-only audit events, and commits once. A failure rolls back the transition/replacement
and returns a generic indexing error.

For search, FastAPI validates a strict `{query, top_k}` body after authentication. The service denies
users without query capability before repository access. The repository requires
`AuthorizationScope`, builds grant-correlated predicates, applies ACL/lifecycle/current-version
filters, then applies PostgreSQL `plainto_tsquery`, rank, deterministic ID tie-break, and limit. The
service maps permitted rows to bounded DTOs and audits only IDs and counts.

### Database flow

Migration `20260821_0004` creates `document_chunks`. Each row has document/version/tenant/company/
department IDs, copied department/visibility/classification/version/lifecycle fields, deterministic
ordinal and content hash, content, and either PDF page provenance or spreadsheet sheet/row/cell
provenance. PostgreSQL maintains a generated `TSVECTOR`; a GIN index supports keyword matching and a
compound index supports ACL/lifecycle filtering. Authoritative `documents` and `document_versions`
are joined and rechecked for every search.

### Heuristic versus LLM ownership

All Step 4 behavior is deterministic. Heading detection, row grouping, bounds, hashes, scope
construction, SQL filters, ranking, excerpts, lifecycle changes, audits, and UI states use typed
Python/TypeScript and PostgreSQL. No LLM chooses chunks, changes authority, rewrites queries, ranks
results, or generates an answer.

### MCP tools involved

None. Search is a direct development baseline used to prove storage and authorization before the
later MCP/agent steps.

### Security invariant

Content can leave the retrieval repository only when its copied ACL and authoritative source rows
both match a mandatory database-derived `AuthorizationScope`, the version is approved/current, and
the chunk is active/non-deleted. Forbidden candidates never enter responses, audits, request logs,
traces, caches, or frontend state.

### Failure example

Alice may add Atlas tenant/company IDs, Legal department, Admin role, Nora's user ID, and arbitrary
document/version IDs to the body. Strict validation rejects the body. The same values in headers or
query parameters are ignored, and the SQL statement still uses Alice's reloaded Orion Finance +
Shared grants. Searching for a Legal term returns no forbidden result. Nora receives a generic 403
before the repository is called.

### Questions Sagar should be able to answer

1. Why must every retrieval repository method accept `AuthorizationScope`?
2. Which copied fields exist on a chunk, and why are authoritative rows still joined during search?
3. How does approval replace old-version chunks atomically?
4. Why can rejected, deleted, inactive, or old-version chunks not appear?
5. How are PDF and spreadsheet chunk boundaries different?
6. Which provenance fields identify a PDF result versus a spreadsheet result?
7. Where are query, `top_k`, excerpt, and total-result bounds enforced?
8. Why does Nora receive 403 even though she can approve uploads?
9. Which search metadata is audited, and which text is deliberately excluded?
10. Why is this keyword baseline deterministic retrieval rather than Step 5 hybrid RAG?
