# Implementation Status

## Current step

Playbook Step 7 complete — the Step 6 grounded path remains intact and a production-safe bounded
single-agent path now adds separate typed Perception and Decision calls, an approved MCP gateway,
two authorization-revalidating document tools, explicit terminal states, and a sanitized React
timeline. Step 8 was not started.

## Implemented

- All completed Step 1–5 identity, authorization, ingestion, lifecycle, chunking, embedding, hybrid
  retrieval, citation, and evaluation behavior remains in place.
- Reversible migration `20260821_0006` adds tenant/user-owned `conversations`, persisted user and
  assistant `messages`, and metadata-only `chat_request_traces`. Trace rows store request,
  conversation, tenant/user, model, status/reason, retrieved document/chunk IDs, token counts,
  latency, and retry count; they have no prompt, question, excerpt, answer, provider body, key, or
  hidden-reasoning column.
- `POST /api/conversations`, `GET /api/conversations`, and
  `POST /api/conversations/{conversation_id}/messages` use strict typed envelopes. Conversation
  create/list is tenant-and-owner scoped; an unknown or foreign conversation returns the same safe
  not-found response.
- The answer path requires a current database-derived `QUERY_DOCUMENTS` grant. A deterministic
  target/department scope preflight abstains on recognizable unauthorized requests without calling
  retrieval or Gemini. All other evidence comes only from the Step 5 `AuthorizedSearchService`, so
  grant-correlated ACL and lifecycle filtering occurs before evidence enters a prompt.
- The prompt boundary serializes the normalized question and at most five authorized evidence rows
  as JSON. Evidence excerpts are explicitly labeled untrusted quoted data. The system instruction
  says document commands, role changes, prompt text, URLs, files, tools, web search, code execution,
  outside knowledge, and hidden assumptions must be ignored.
- `LLMProvider` has an official `google-genai` Gemini adapter, deterministic fake-test adapter, and
  disabled adapter. The real adapter is fixed to `gemini-3.7-flash`, medium thinking with thoughts
  excluded, temperature zero, one candidate, structured JSON output, bounded output/time, SDK
  retries disabled, and at most one application retry for transient failures. No tool, tool config,
  web search, code execution, file search, URL access, or computer-use capability is configured.
- Provider output is treated as untrusted. A supported response must have non-empty bounded claims;
  every claim must cite one or more unique retrieved evidence IDs; unknown or fabricated IDs fail
  closed. Citation DTOs are reconstructed by the host from the corresponding retrieved row and
  preserve document/version/chunk identity, title, excerpt, and PDF page or spreadsheet
  sheet/row/cell provenance. Invalid, contradictory, or incomplete response structures become a
  controlled insufficient-evidence answer.
- Missing or low-relevance evidence, unauthorized recognizable targets, and citation validation
  failure return an explicit `insufficient_evidence` response with no claims or citations. Provider
  timeout/unavailability returns generic 504/503 errors; no partial or unvalidated answer is shown.
- Successful and abstaining calls persist the user message, controlled assistant response, and one
  sanitized trace. Provider failures persist a metadata-only failure trace. Application audit logs
  contain request/conversation IDs, safe status/reason codes, and counts only; tests assert that API
  keys, raw questions, excerpts, provider data, answers, prompts, and hidden reasoning do not appear.
- The `/chat` UI is visible only to users whose current scope includes `QUERY_DOCUMENTS`. It provides
  an owner-scoped conversation list, automatic/new conversation creation, bounded suggestions and
  composer, request cancellation, loading and empty states, controlled insufficient-evidence cards,
  safe denial/timeout/generic-error cards, supported claims with inline citations, limitations, and
  an accessible evidence drawer with exact provenance. Its strict response validator rejects extra
  fields, malformed provenance, unknown/duplicate/unreferenced citations, and mismatched
  conversation IDs before rendering content as inert React text.
- Automated model tests use deterministic fakes. They do not call Gemini, require a key, or depend on
  network availability.
- `POST /api/conversations/{conversation_id}/agent-runs` reloads conversation ownership and current
  database grants before any model or tool work. Recognizable cross-scope requests terminate as a
  controlled refusal before Perception, MCP, retrieval, or Gemini.
- One typed `AgentSession` owns separate `user_query`/`step_result` Perception snapshots, Decision
  plan versions, exactly one next `TOOL_CALL|FINALIZE|CLARIFY|REFUSE` action, structured
  observations, completed steps, counters, evidence, and one explicit terminal status. Defaults
  enforce four tool steps, one semantic retrieval rewrite, one replan, a 90-second total duration,
  a per-tool timeout, and at most one transient retry.
- The official pinned `mcp==2.0.0` SDK runs an in-process request-scoped server/client. Its catalog is
  statically limited to `portfolio.search_authorized_documents` and
  `portfolio.get_document_excerpt`, filtered by the host shortlist and current capability, and
  rechecked at execution. Raw model arguments are strictly validated before MCP conversion; trusted
  `AuthorizationScope` is injected through host closures and both adapters reauthorize through the
  Step 5 database predicates.
- Startup validates unique namespaced ownership plus exact input/output schema and capability
  mappings. Unknown/unshortlisted tools, forged scope fields, malformed input/output, missing or
  unauthorized IDs, provider failures, and bounds terminate with safe typed observations.
- Separate Gemini Perception and Decision calls use structured JSON, medium thinking with thoughts
  excluded, bounded timeout/output, one transient retry, no tools, and strict local validation.
  Decision cannot execute tools, emit source code, or create/change scope; only the host loop calls
  the MCP gateway. Final answers reuse Step 6 host citation reconstruction and validation.
- The public trace contains only host UUID event IDs, eight stage/status types, the two approved
  action names, host-issued `ev_N` references, bounded durations, counters, and explicit allow-listed
  reason/stopping codes. It excludes queries, prompts, plans, observations, excerpts, answers,
  authorization fields, paths, exceptions, secrets, and model rationale/reasoning. The frontend
  recursively rejects any extra or non-host trace value before rendering inert text.

## Pending acceptance criteria

None within Step 7. Bounded success and all terminal paths, gateway/MCP contracts, authorization,
schema/startup, retry/timeout, trace-redaction, citation preservation, fake-provider, local MCP,
live-model, frontend, regression, migration, and repository-integrity gates passed.

## Verification result

Step 4 was verified on 2026-08-21: backend format/lint/type checks and its then-current 132-test
suite passed against isolated PostgreSQL; frontend format/lint/type checks, 40 Vitest tests, build,
and audit passed; migration `0004` reversibility/no-drift and the Step 4 manual API/UI matrix passed.

Step 5 was independently verified on 2026-08-21. Backend Ruff format/lint and strict mypy passed;
all 167 backend tests passed against isolated PostgreSQL. Frontend Prettier, ESLint, strict
TypeScript, all 47 Vitest tests, the zero-vulnerability npm audit, and the production build passed.
Migration `0005` upgrade, no-drift check, downgrade to `0004`, re-upgrade, and second no-drift check
passed. A live local Ollama smoke returned one finite, non-zero 768-dimensional
`nomic-embed-text:v1.5` vector. Production exclusion, tracked-secret, `.env`, `Simulated_data`, and
whitespace gates also passed.

Step 6 was independently verified on 2026-08-21. Backend Ruff format/lint and strict mypy pass; all
191 backend tests pass against isolated PostgreSQL. Frontend Prettier, ESLint, strict TypeScript,
all 74 Vitest tests, the zero-vulnerability npm audit, and the production build pass. Migration
`0006` upgraded with no drift, downgraded to `0005`, re-upgraded, and passed a second drift check.
The minimal live Gemini smoke used synthetic authorized evidence and returned `status=supported`,
one cited claim, `claims_cited=true`, and `retry_count=0`; the check printed no key, prompt,
evidence, answer, or reasoning. Focused security tests also pass for prompt injection, preflight
scope denial, authorization-before-generation, citation reconstruction/validation, safe provider
failure, retry bounds, and content-free logs. Repository integrity and `git diff --check` pass.

Step 7 was independently verified on 2026-08-21. Backend Ruff format/lint and strict mypy pass; all
236 backend tests pass against isolated PostgreSQL. Frontend Prettier, ESLint, strict
TypeScript, all 88 Vitest tests, the zero-vulnerability npm audit, and the production build pass.
The official MCP in-process smoke, real authorized search/excerpt integration, adversarial gateway
and agent state-machine tests, unrestricted-execution scan, and trace-redaction gates pass. Step 7
adds no migration; the existing `0006 -> 0005 -> 0006` reversibility and drift cycle remains green.

## Known limitations

- The agent trace is response-only; Step 7 does not add AgentRun/Plan/Step/Observation persistence or
  a trace-history endpoint. Existing message content and metadata-only request traces still persist.
- The conversation list is persisted, and message rows are stored, but Step 6 has no message-history
  read endpoint and sends no prior turns to Gemini. After a reload the UI lists the conversation but
  cannot reload its earlier transcript; there is no working or long-term memory.
- Scope preflight is a conservative bounded regex/token heuristic for recognizable tenant/company
  and department wording. It is defense in depth, not the primary authorization boundary and not a
  complete natural-language entity resolver. Step 5 repository authorization still controls every
  retrieved row.
- Citation validation proves structural completeness and exact membership/provenance against the
  retrieved evidence IDs. It does not independently prove natural-language entailment or numeric
  correctness. The deterministic abstention threshold is intentionally small, and the curated
  retrieval set remains a narrow synthetic quality gate.
- User questions and controlled assistant answers are intentionally persisted in `messages` as
  conversation content. They are excluded from traces and logs, but there is not yet a retention,
  deletion, export, encryption-at-rest, or content-redaction workflow for conversations.
- Browser cancellation aborts the client request and suppresses partial UI output, but it is not a
  guarantee that an already-started upstream/provider or database operation has stopped.
- The Gemini API key is local environment configuration and the live smoke is a one-case
  connectivity/contract check, not a broad faithfulness, latency, availability, or cost benchmark.
  The fake provider is deterministic test infrastructure, not evidence of live-model quality.
- Perception and Decision quality remains model-dependent. Deterministic host validation constrains
  actions, authority, bounds, and trace/output shape, but it does not prove that a plan is optimal.
- The MCP gateway is embedded in-process. There is no remote MCP transport, dynamic discovery,
  multi-agent coordination, memory, deterministic financial calculation, or general sandbox.
- Production still requires `EMBEDDING_PROVIDER=disabled`; therefore the current synchronous Step 5
  retrieval dependency makes grounded chat a local demonstration rather than a production-ready
  deployment. A production embedding/indexing design remains necessary.

## Test commands

See [docs/testing-guide.md](docs/testing-guide.md) for the exact backend, frontend, migration,
fake-provider, live Gemini, chat/API/UI, authorization, redaction, and failure checks.

## Next approved step

None in this goal. Step 8 was explicitly not started.
