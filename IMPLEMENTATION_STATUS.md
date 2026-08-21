# Implementation Status

## Current step

Playbook Steps 7 through 9 plus all three interview features are implementation-complete. Step 7
provides the embedded approved MCP gateway and two authorization-revalidating document tools; Step
8 provides separate typed Perception and Decision
stages plus the host-owned bounded AgentLoop. The Step 6 grounded path remains intact. Live Runpod
Kimi Perception, typed-catalog Decision, and grounded final-answer contracts pass. Simple,
single-document, high-confidence grounded answers route to Mac Ollama `qwen3:8b`; complex,
multi-document, low-confidence, and all agentic stages route to Runpod `kimi-k3`. Scoped private,
Finance, Legal, and Shared memory is source-reauthorized before retrieval. Step 9 adds three fixed
financial calculators whose inputs are reauthorized and whose arithmetic/finalization is host-owned.

## Implemented

- A pure host-owned model policy runs only after authorization-first retrieval. It uses workload
  kind, distinct authorized document count, top authorized retrieval score, and bounded query-shape
  rules; no model, prompt, identity claim, or client field can choose authority or override a route.
- The Qwen adapter is pinned to `http://192.168.31.213:11434` and `qwen3:8b`, disables environment
  proxy inheritance, tools, streaming, and thinking, validates strict grounded JSON, rejects visible
  thinking markers, and has its own timeout. Retryable Qwen failures may fall forward to Kimi;
  Kimi-first work never downgrades to Qwen.
- Agent Perception, Decision, and finalization remain explicitly pinned to Kimi in router mode.
  Authorized evidence objects are reused unchanged on fallback. Migration `20260821_0007` records
  only the actual model, allow-listed route/fallback reason codes, and a fallback flag.
- Migration `20260821_0008` adds tenant/company-scoped `memories` and immutable copied-provenance
  `memory_sources`. Database constraints bind the four scopes to valid Finance, Legal, or Shared
  ACL tuples; private ownership is mandatory only for `PRIVATE_USER`.
- Memory creation accepts no client identity, tenant, department, visibility, classification, or
  owner fields. Source-free memory must be private. Every source ID is resolved through the current
  authorized-chunk repository, mixed ACLs fail closed, and sourced memory inherits the exact source
  restriction (with private visibility allowed only as a narrowing operation).
- Memory list/search/get first materializes current tenant, company, department, private owner,
  classification, expiry, deletion, and source authorization. Revoked/rejected/deleted source
  chunks make their memory invisible immediately. Search ranks only that materialized visible set.
- The grounded-chat prompt may receive at most five company-matched visible memories. They are
  serialized separately as untrusted, non-evidentiary context; embedded commands are ignored and
  memory IDs cannot satisfy document citation validation.
- `/api/memories` provides create/inspect/search/delete contracts and metadata-only audit events.
  The capability-gated `/memories` UI creates source-free private preferences, inspects only the
  server-filtered result, and honors a server-derived delete permission.
- Three fixed MCP tools calculate EBITDA margin, revenue growth, and net profit margin from one
  authorized approved P&L workbook. Inputs accept only company and period; every numeric cell is
  literal, unit-checked, bounded, tied to an authorized chunk, and cited with exact provenance.
- Host `Decimal` functions own formulas, denominator checks, rounding, and deterministic response
  finalization. The model never supplies authoritative numbers or arithmetic. Missing, invalid,
  ambiguous, unauthorized, and zero-denominator cases fail closed without evidence or results.
- The `/chat` calculation card renders formula, result, trusted inputs/units/periods, and evidence
  controls. Strict client validation rejects malformed calculation/citation graphs before display.

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
  retrieval or a model call. All other evidence comes only from the Step 5 `AuthorizedSearchService`, so
  grant-correlated ACL and lifecycle filtering occurs before evidence enters a prompt.
- The prompt boundary serializes the normalized question and at most five authorized evidence rows
  as JSON. Evidence excerpts are explicitly labeled untrusted quoted data. The system instruction
  says document commands, role changes, prompt text, URLs, files, tools, web search, code execution,
  outside knowledge, and hidden assumptions must be ignored.
- `LLMProvider` has Gemini and OpenAI-compatible Runpod Kimi adapters, a deterministic fake-test
  adapter, and a disabled adapter. The Kimi path fixes the approved base URL and `kimi-k3`, sends
  temperature exactly `1`, requires at least 1,024 output tokens, requests structured JSON, and
  permits at most two total calls for one transient, malformed, or incomplete response. Empty
  content ending for length is incomplete. `reasoning_content` is deleted at the provider boundary
  and is never returned, persisted, logged, or rendered. No model tool capability is configured.
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
- Automated model tests use deterministic fakes. They do not call a live provider, require a key, or depend on
  network availability.
- `POST /api/conversations/{conversation_id}/agent-runs` reloads conversation ownership and current
  database grants before any model or tool work. Recognizable cross-scope requests terminate as a
  controlled refusal before Perception, MCP, retrieval, or a model call.
- One typed `AgentSession` owns separate `user_query`/`step_result` Perception snapshots, Decision
  plan versions, one-to-three-entry internal plan text, exactly one next
  `TOOL_CALL|FINALIZE|CLARIFY|REFUSE` action, structured observations, immutable completed steps,
  counters, evidence, and one explicit terminal status. A dedicated plan-state module enforces
  version-one initialization, exact version increments, first-pending-step order, no completed-step
  replay, preserved history, and host-counted plan changes. Defaults enforce four tool steps, one
  semantic retrieval rewrite, one replan, a 90-second total duration, a per-tool timeout, and at
  most one transient retry.
- The official pinned `mcp==2.0.0` SDK runs an in-process request-scoped server/client. Its catalog is
  statically limited to two document tools and three fixed financial calculators, filtered by the
  host shortlist and current capability, and
  rechecked at execution. Raw model arguments are strictly validated before MCP conversion; trusted
  `AuthorizationScope` is injected through host closures and both adapters reauthorize through the
  Step 5 database predicates.
- Startup validates unique namespaced ownership plus exact input/output schema and capability
  mappings. Unknown/unshortlisted tools, forged scope fields, malformed input/output, missing or
  unauthorized IDs, provider failures, and bounds terminate with safe typed observations.
- Separate provider Perception and Decision calls use structured JSON, bounded timeout/output, one
  bounded retry, no tools, and strict local validation. Provider schemas derive from authoritative
  Pydantic contracts. Perception is observe/classify-only, records scope mentions as non-executable
  hints, and receives only the prior snapshot, current plan, immutable completed history, latest
  observation, and safe budgets after a step. Decision receives manifest-derived authorized tool
  descriptors with exact per-tool inputs, not identity or scope. Only the host loop calls the MCP
  gateway. Final answers reuse Step 6 host citation reconstruction and validation.
- The public trace contains only host UUID event IDs, eight stage/status types, the five approved
  action names, host-issued `ev_N` references, bounded durations, counters, and explicit allow-listed
  reason/stopping codes. It excludes queries, prompts, plans, observations, excerpts, answers,
  authorization fields, paths, exceptions, secrets, and model rationale/reasoning. The frontend
  recursively rejects any extra or non-host trace value before rendering inert text.

## Pending acceptance criteria

Live dual-route Qwen/Kimi verification remains part of the final three-feature gate. Live Runpod
Kimi Perception, typed-catalog Decision, and grounded finalization passed. A full
database-backed authorized agent API workflow remains a separate manual acceptance gate. Every
deterministic backend/frontend, local MCP, migration, security, and repository-integrity gate from
the Step 8 checkpoint passed.

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

Steps 7 and 8 were independently verified on 2026-08-21. Backend Ruff format/lint and strict mypy
pass; the current 263 backend tests pass against isolated PostgreSQL. Frontend Prettier, ESLint, strict
TypeScript, all 88 Vitest tests, the zero-vulnerability npm audit, and the production build pass.
The official MCP in-process smoke, real authorized search/excerpt integration, adversarial gateway
and agent state-machine tests, strict schema derivation, unrestricted-execution scan, and
trace-redaction gates pass. Steps 7 and 8 add no migration; the existing
`0006 -> 0005 -> 0006` reversibility and drift cycle remains green.
Live Gemini initially exposed and helped correct a dropped `Literal` constraint in the provider
schema transformation, then quota blocked the full chain. The Runpod replacement was live-verified
with the exact Kimi endpoint/model: initial Perception classified a financial lookup, initial
Decision returned a strict valid two-step plan selecting the sole permitted search tool,
step-result Perception marked synthetic authorized evidence sufficient, mid-session Decision chose
`FINALIZE`, and finalization returned one supported host-validatable cited claim with zero retry. A
nondeterministic malformed Decision was
observed once at Kimi's required temperature; validation failed closed, and the implementation now
places malformed/incomplete responses inside the same strict two-attempt total budget as transient
failures.

## Known limitations

- The Mac Qwen endpoint is development-only plaintext HTTP on a pinned private-LAN address. It is
  rejected in production; a production deployment requires an authenticated, encrypted approved
  economical-model endpoint. The retrieval score threshold is a deterministic routing heuristic,
  not a calibrated probability.

- The agent trace is response-only; Steps 7 and 8 do not add AgentRun/Plan/Step/Observation persistence or
  a trace-history endpoint. Existing message content and metadata-only request traces still persist.
- The conversation list is persisted, and message rows are stored, but Step 6 has no message-history
  read endpoint and sends no prior turns to the model. Scoped memory is explicit and separate; it
  does not restore earlier transcript turns after reload.
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
- Provider API keys are local environment configuration and the live smoke is a one-case
  connectivity/contract check, not a broad faithfulness, latency, availability, or cost benchmark.
  The fake provider is deterministic test infrastructure, not evidence of live-model quality.
- Perception and Decision quality remains model-dependent. Deterministic host validation constrains
  actions, authority, bounds, and trace/output shape, but it does not prove that a plan is optimal.
- The MCP gateway is embedded in-process. There is no remote MCP transport, dynamic discovery,
  multi-agent coordination, arbitrary calculation/code execution, or general sandbox.
- Production still requires `EMBEDDING_PROVIDER=disabled`; therefore the current synchronous Step 5
  retrieval dependency makes grounded chat a local demonstration rather than a production-ready
  deployment. A production embedding/indexing design remains necessary.

## Test commands

See [docs/testing-guide.md](docs/testing-guide.md) for the exact backend, frontend, migration,
fake-provider, live Runpod Kimi, chat/API/UI, authorization, redaction, and failure checks.

## Next approved step

Run the combined three-feature acceptance gate, live dual-route smoke, and branch publication. No
additional product feature is approved in this checkpoint.
