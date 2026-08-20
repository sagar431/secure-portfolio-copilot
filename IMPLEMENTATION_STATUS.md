# Implementation Status

## Current milestone

Playbook Step 2 — identity, tenancy, departments, and deterministic policy engine.

## Completed acceptance criteria

- Tenant, company, department, role, user, membership, workspace-grant, company-grant, and
  department-grant models are normalized and migrated.
- The development seed creates Nora, Alice, Leo, Maya, Amir, and Lina with deterministic IDs and
  idempotent grants.
- Passwords use Argon2id hashes; plaintext passwords are never stored or logged.
- `POST /api/auth/login` issues signed 15-minute JWT access tokens.
- `GET /api/auth/me` validates signature, algorithm, issuer, audience, expiry, user status, and
  current database membership/grant state.
- Tokens contain identity reference claims only. Tenant, company, department, role, and scope are
  rebuilt from PostgreSQL for protected requests.
- Frozen `TrustedIdentity` and `AuthorizationScope` contracts feed a deterministic deny-by-default
  RBAC/ABAC policy engine with reason-coded decisions.
- Alice receives Orion Finance + Shared, Leo Orion Legal + Shared, Maya explicit Orion Finance +
  Legal + Shared, Amir Atlas Finance + Shared, and Lina Atlas Legal + Shared.
- Nora receives platform administration and Orion/Atlas upload-management capabilities with no
  document-query capability.
- Login errors do not distinguish an unknown user from a wrong password.
- Forged identity, tenant, role, department, company, and scope fields are rejected or ignored.
- React provides login, development-only demo cards, protected routing, session validation,
  identity/scope display, safe errors, and logout.
- Existing Step 1 health, readiness, request-ID, safe-error, and frontend-health behavior remains
  covered by regression tests.

## Pending acceptance criteria

None within Step 2.

## Verification result

Verified on 2026-08-20:

- Backend: formatting, linting, strict type checking, and 44 tests pass, including PostgreSQL-backed
  integration and security tests.
- Frontend: formatting, linting, strict type checking, 7 Vitest tests, and production build pass.
- Alembic upgrade, drift check, downgrade to Step 1, re-upgrade, and double-seed idempotence pass.
- Live login and `/api/auth/me` pass for all six synthetic identities.
- Live forged-scope, generic-login-error, malformed-token, expired-token, and wrong-issuer probes
  return the expected safe results.
- Headless Chrome renders the login screen and completes Alice's real login flow to the protected
  Orion Finance + Shared scope screen without a Vite error overlay.

## Known limitations

- Password login and demo users are development-only; production requires an external identity
  provider in a later hardening phase.
- Access tokens are held in browser `sessionStorage`; production should prefer a hardened session or
  HttpOnly cookie design with CSRF controls.
- There is no refresh token; a session expires after 15 minutes and the user signs in again.
- Each synthetic user currently has one home membership. The contracts support multiple active
  membership-derived grants, but no workspace-switching UI exists.
- Step 2 defines upload-management and query capabilities but implements no document endpoint.
- Documents, parsing, retrieval, embeddings, LLMs, MCP, memory, calculations, agents, and AWS remain
  intentionally absent.

## Test commands

See [docs/testing-guide.md](docs/testing-guide.md) for exact automated, migration, seed, live API,
and UI verification commands.

## Next approved milestone

None. Work must stop after Step 2 until the user explicitly approves Step 3.
