# Step 6 Security Invariants

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
17. **Capability and target authorization.** Every document-management operation requires a current
    database-derived `MANAGE_UPLOADS` grant for the exact workspace/company. Route hiding is not an
    authorization boundary, and upload targets are checked before file bytes are read.
18. **Development database only.** Compose defaults are local credentials and must not be reused in
    shared or production environments.
19. **Canonical metadata only.** Tenant/company IDs, department, visibility, classification,
    document type, and reporting period must match backend-published and backend-validated values.
    Identity, role, filesystem path, URL, and version number are never accepted from the browser.
20. **Bounded uploads.** Files are capped at 10 MiB and validated by sanitized extension, MIME type,
    signature, archive structure, decompressed size, entry count, and parser-specific limits.
21. **Fail-closed formats.** Encrypted or active PDFs, macros, external links, unsafe OOXML members,
    ZIP bombs, malformed containers, and unsupported content are rejected before preview.
22. **Parser isolation.** Parsing occurs in a spawned process with a wall-clock timeout and operating
    system resource limits. Parser errors expose only stable safe codes/messages.
23. **Generated object identity.** Raw files use UUID-only server-generated keys confined beneath a
    configured storage root. Browser filenames never choose a path. Writes are private and atomic;
    checksums and sizes are verified.
24. **Inert preview.** Parsed spreadsheet values and PDF text are display data only. Formula-like
    strings are preserved for provenance but never executed or injected as HTML.
25. **Legal lifecycle only.** Version/job state changes follow the explicit Step 3 state machine.
    Approval and rejection are allowed only from `PREVIEW_READY`; rejected/failed/deleted versions
    cannot later be approved.
26. **Deterministic retries and versions.** Actor-scoped idempotency keys and request fingerprints
    prevent accidental duplicate writes. Conflicting reuse fails. New versions require the explicit
    version endpoint and cannot change canonical scope metadata.
27. **Safe deletion.** Soft deletion commits immediate unavailability before best-effort object
    cleanup. Cleanup failures are audited without restoring access or exposing storage details.
28. **Approved versions only.** Chunk generation rejects any version that is not the non-deleted,
    current approved version. Preview-ready, rejected, failed, old, and deleted versions cannot
    become active search sources.
29. **Copied chunk authority.** Every chunk copies tenant, company, department, visibility,
    classification, document/version identity, version status, deletion state, and active status.
    Chunk metadata cannot widen source-document authority.
30. **Atomic replacement.** Approval locks the managed version and commits its lifecycle transition,
    old-chunk/vector invalidation, new READY chunk/vector insertion, and current-version pointer
    together. Chunking or embedding failure rolls back the replacement and returns a generic safe
    error.
31. **Immediate removal.** Replacement, rejection, and deletion deactivate affected chunks in the
    same transaction as their authoritative lifecycle change. Search also rechecks authoritative
    document/version rows, so copied flags alone are never sufficient.
32. **Deterministic bounded chunks.** PDF chunks never cross pages and split only by deterministic
    headings/size bounds. Spreadsheet chunks never cross sheets and preserve bounded row/cell ranges.
    Empty, inactive, oversized, or inconsistent source input fails closed with a content-free error.
33. **Mandatory repository scope.** Every public production search/count repository method requires
    an immutable `AuthorizationScope`; no unscoped production retrieval method exists.
34. **Authorization before materialization.** Tenant, company, department, exact
    visibility/classification, capability, approval, deletion, active-version, current-version, and
    active tenant/company filters are SQL predicates in a materialized authorized CTE before vector
    distance, hybrid rank, ordering, or limit is applied.
35. **Bounded deterministic search.** Queries normalize to 1–500 characters, `top_k` is 1–20,
    excerpts are at most 500 characters, and total excerpt output is at most 10,000 characters.
36. **No forged search scope.** The search body accepts only query and `top_k`. Tenant, company,
    department, role, user, document, version, or scope fields fail validation; similarly named
    headers/query parameters never alter database-derived authority.
37. **No query authority for upload admins.** Nora receives a generic 403 before repository search.
    `MANAGE_UPLOADS` still never implies `QUERY_DOCUMENTS`.
38. **Metadata-only search audit.** Search logs/audits contain request/actor/resource IDs and counts,
    plus bounded `top_k`, never query text, vectors, raw candidates, excerpts, or document content.
    Forbidden candidates are absent from responses, logs, traces, caches, and debug output.
39. **Development-only inspector.** The backend search route is registered only in development/test.
    Production frontend builds omit the search route, navigation, page, and endpoint client.
40. **Exact embedding contract.** Persisted READY rows use `nomic-embed-text:v1.5`, 768 dimensions,
    a finite non-zero vector, and an `embedding_chunk_hash` equal to the chunk's current
    `content_hash`. Wrong-model, wrong-dimension, null, stale-hash, and non-READY rows cannot enter
    hybrid retrieval.
41. **Provider output is untrusted.** Batch cardinality, dimensions, finiteness, non-zero norm, total
    chunks, and time are validated before persistence. Provider errors expose only a generic message,
    never an upstream body, URL, model response, query, content, or internal reason code.
42. **Development providers only.** Ollama is restricted to explicit HTTP loopback URLs, disables
    environment proxy inheritance, and never substitutes another model. The deterministic fake is
    test-only. Production accepts only the disabled provider and omits development retrieval routes.
43. **Capability before query embedding.** A caller without `QUERY_DOCUMENTS` is denied before the
    embedding provider and retrieval repository are invoked. Search sends only the authorized
    caller's query to the provider, never candidate document content.
44. **Authorization before vector ranking.** Hybrid SQL references cosine distance only through
    `authorized_chunks AS MATERIALIZED`. Raw `document_chunks.embedding` cannot be vector-ranked
    before grant-correlated ACL, copied-to-authoritative equality, and current lifecycle filters.
45. **Deterministic bounded fusion.** Hybrid scores are bounded to `[0,1]` and use the fixed formula
    `0.35 * keyword + 0.65 * vector`; ordering is final score, keyword score, then chunk ID. Query,
    `top_k`, result, and excerpt limits remain enforced.
46. **Embedding lifecycle follows source lifecycle.** Replacement, rejection, and deletion clear
    vectors/model/hash metadata and mark affected rows `STALE` in the authoritative transaction.
    Approval publishes READY vectors only with the current approved version.
47. **Authorized bounded backfill.** Reindexing accepts no client scope and processes only bounded
    `PENDING`/`FAILED`, active, current-approved rows inside a current admin `MANAGE_UPLOADS`
    workspace/company grant. It rechecks authoritative ACL/lifecycle state and locks candidates with
    `SKIP LOCKED`; query access alone never permits reindexing.
48. **No unsafe fallback.** Provider failure returns a generic 503. Search does not silently fall
    back to keyword-only results, and approval/reindex does not persist partial or invalid vectors.
49. **Citation integrity at the boundary.** Returned citation IDs, version, excerpt, and source
    location are constructed from the same authorized repository row as the result. The frontend
    validates their equality and renders excerpts as inert text.
50. **Honest evaluation state.** Checked-in curated synthetic queries report their measured
    Recall@5, expected hit, and authorization-leak count. Ad hoc queries report `not_run`; UI fixtures
    are not represented as additional measured results.
51. **No Step 5 overclaim.** The curated retrieval gate is narrow. It does not establish broad
    semantic quality, reranking quality, or production readiness.
52. **Owned conversations.** Conversation create/list/message operations derive tenant and user from
    the authenticated database context. Lookup includes conversation, tenant, and user; a foreign ID
    returns the same safe 404 as a missing ID.
53. **Capability before chat work.** `QUERY_DOCUMENTS` is required before a chat message can invoke
    retrieval or generation. Missing capability returns a generic denial before either provider is
    called.
54. **Recognizable scope denial before retrieval.** Explicit tenant/company/department target hints
    outside the current query grants produce an abstention without retrieval or Gemini. This
    conservative heuristic is defense in depth; it never replaces Step 5 SQL authorization.
55. **Authorized retrieval before prompting.** Every evidence row must come from
    `AuthorizedSearchService` under the current immutable `AuthorizationContext`. Authorization and
    lifecycle filtering finish before document content can enter the prompt.
56. **No model-defined authority.** The LLM request contains question and authorized evidence only.
    It cannot supply or alter tenant, company, department, user, role, capability, conversation
    ownership, retrieval filters, or authorization scope.
57. **Documents are untrusted data.** Evidence is JSON-serialized under an explicit untrusted-data
    label. The system instruction requires ignoring embedded instructions, policies, role changes,
    prompt text, URLs, files, tools, web search, code execution, and hidden assumptions.
58. **No Gemini tools.** The official Google GenAI request supplies neither `tools` nor
    `tool_config`. It enables no web/file search, URL access, function call, computer use, or code
    execution. Medium thinking excludes thoughts from the response.
59. **Bounded provider call.** Question length, evidence count, excerpt size, output tokens, timeout,
    response schema, candidate count, and temperature are bounded. SDK attempts equal one; only a
    transient failure may receive one application retry. Authorization denials never retry.
60. **Provider output is untrusted.** Structured output is locally validated. Unsupported status,
    empty claims, oversized/empty claim text, missing references, unknown evidence IDs, duplicate
    evidence identity, or invalid response shape fails closed.
61. **Host-owned citations.** Gemini returns evidence references, not trusted citation DTOs. The
    backend reconstructs title, document/version/chunk IDs, version, excerpt, and page or
    sheet/row/cell location exclusively from the retrieved evidence map.
62. **Complete claim references.** Every returned grounded claim has at least one retrieved evidence
    ID. Every citation returned to the browser is referenced by a claim. Insufficient-evidence
    responses contain neither claims nor citations.
63. **Controlled abstention.** Missing/low-relevance evidence, recognizable unauthorized targets,
    inconsistent retrieval provenance, and citation-validation failure return the same bounded
    insufficient-evidence answer without restricted content or fabricated citations.
64. **Safe provider failure.** Provider timeout maps to generic 504; unavailable/rejected/invalid
    provider behavior maps to generic 503. Raw upstream errors, bodies, keys, prompts, evidence,
    generated output, and exception text never cross the API boundary.
65. **Sanitized chat traces and logs.** Trace rows/logs contain only correlation/ownership IDs,
    model, safe status/reason, permitted retrieved IDs, token counts, latency, retry count, and
    bounded counts. They contain no question, prompt, excerpt, answer, provider body, key, or hidden
    reasoning. Conversation `messages` are intentionally separate persisted content.
66. **Strict inert frontend.** The chat client rejects extra response fields, malformed provenance,
    mismatched conversation IDs, and missing/unknown/duplicate/unreferenced citations. React renders
    questions, answers, claims, limitations, titles, and excerpts as text rather than HTML.
67. **No partial UI answer.** Loading, cancellation, timeout, denial, and error paths do not render a
    partial provider response or unvalidated citation. Browser cancellation is a UI guarantee, not a
    claim that already-started upstream work was canceled.
68. **No later capabilities.** Step 6 has no MCP, Perception, Decision, plan, tool calling, memory,
    deterministic financial calculation, arbitrary execution, cloud deployment, or agent loop.

Automated tests cover password/token primitives, exact seeded scopes, policy reason codes, generic
login errors, forged fields, malformed/expired/wrong-issuer/wrong-audience/wrong-signature tokens,
disabled users, revoked memberships, direct backend enforcement, safe logging, invalid request IDs,
database-readiness failure, frontend session failure, upload authorization, strict metadata,
malicious/malformed formats, parser/storage limits, state transitions, idempotency, versioning,
preview provenance, inert formulas, deletion, deterministic chunk provenance, metadata inheritance,
approved-only creation, atomic replacement, rejection/deletion, mandatory repository scope,
six-user isolation, forged search values, query/result/excerpt bounds, safe audit/logging,
provider/model validation, bounded batching, production/provider isolation, authorization-before-
vector SQL construction, embedding invalidation/backfill, citation response validation,
conversation ownership, authorization-before-prompting, scope preflight, prompt injection, Gemini
no-tool/bound/retry behavior, fake-provider grounded answers, citation reconstruction and failure,
sanitized trace/log behavior, and all chat UI states. Final Step 6 verification passes 191 backend
and 74 frontend tests, migration `0006` downgrade/re-upgrade/drift checks, live Ollama and minimal
synthetic Gemini smokes, production/integrity gates, and zero-vulnerability frontend audit.
