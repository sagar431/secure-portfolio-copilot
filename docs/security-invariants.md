# Step 1 Security Invariants

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
8. **No implied authorization.** Request IDs, browser state, and environment fields are not identity
   or permission controls. Authentication and authorization do not exist yet.
9. **No future capabilities.** This milestone contains no upload, retrieval, embedding, LLM, MCP,
   memory, calculation, arbitrary code execution, or cloud integration.
10. **Development database only.** Compose defaults are local credentials and must not be reused in
    shared or production environments.

Automated tests cover safe error output, invalid request-ID replacement, database-readiness failure,
and the frontend failure display. Later authorization tests cannot be claimed until their milestone.
