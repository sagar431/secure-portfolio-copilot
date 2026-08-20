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
