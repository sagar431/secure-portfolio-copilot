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
