# Step 2 Security Invariants

These rules apply now and must remain true as later milestones are approved.

1. **No real portfolio data.** Only explicitly synthetic data may exist in this repository.
2. **No secret commits.** `.env`, credentials, and private keys remain ignored; `.env.example`
   contains development placeholders only.
3. **Safe external errors.** API errors use stable codes and generic messages. Stack traces,
   connection strings, SQL text, request bodies, and exception details are not returned.
4. **Metadata-only request logs.** Request logs contain request ID, method, path, status, and duration.
   They do not contain request bodies or query strings.
5. **Bounded request IDs.** A caller-provided ID is accepted only when it matches the limited
   character set and length; otherwise the backend generates a UUID.
6. **Honest health semantics.** `/health` reports process liveness. `/ready` reports database
   connectivity. A database outage must not be mislabeled as full readiness.
7. **Typed boundaries.** Settings and API envelopes are Pydantic models; frontend API failures are a
   typed `ApiError`.
8. **Server-derived authority.** Request IDs, browser state, headers, query parameters, JWT custom
   claims, and request JSON never define effective tenant, user, role, department, company, or
   authorization scope.
9. **Short-lived identity reference.** JWTs use one fixed algorithm and require a valid signature,
   issuer, audience, issued-at time, expiry, subject, and token ID. They contain no effective scope.
10. **Database revalidation.** Every protected request reloads the user and active memberships/grants.
    Disabled users and revoked memberships invalidate existing tokens.
11. **Secure passwords.** User passwords exist only as Argon2id hashes in PostgreSQL. Passwords and
    tokens never enter application audit/request logs.
12. **Generic authentication failures.** Unknown user and wrong password return the same status,
    code, and message. Unknown users take a dummy password-verification path.
13. **Immutable authorization.** `TrustedIdentity`, `AuthorizationScope`, grants, policy requests,
    and decisions are frozen strict models. Policy is deterministic Python and denies by default.
14. **Dimension intersection.** Query permission requires matching workspace, company, department,
    and capability grants. Admin/upload permission never implies query permission.
15. **Frontend is not enforcement.** Protected routes and hidden UI are UX only. Backend endpoints
    independently authenticate and derive scope.
16. **Development-only credentials.** The seed refuses production mode and placeholder/short demo
    passwords. Demo cards are excluded from production frontend builds. Production rejects the
    default development JWT key and password login.
17. **No future capabilities.** This milestone contains no upload endpoint, retrieval, embedding, LLM, MCP,
   memory, calculation, arbitrary code execution, or cloud integration.
18. **Development database only.** Compose defaults are local credentials and must not be reused in
    shared or production environments.

Automated tests cover password/token primitives, exact seeded scopes, policy reason codes, generic
login errors, forged fields, malformed/expired/wrong-issuer/wrong-audience/wrong-signature tokens,
disabled users, revoked memberships, direct backend enforcement, safe logging, invalid request IDs,
database-readiness failure, and frontend session failure.
