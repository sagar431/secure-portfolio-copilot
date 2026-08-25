# Implementation Status

## Memory-aware bounded portfolio agent — current head (2026-08-23)

The current head implements the complete request path requested for the memory-aware demo:

`typed intent -> authorize-first memory/conversation context -> authorized retrieval or approved
MCP tool -> deterministic validation -> persisted result -> validated NDJSON delivery`.

- The host routes every request before retrieval as `CASUAL`, `DOCUMENT_QUESTION`,
  `CONVERSATION_FOLLOW_UP`, `MEMORY_RECALL`, `MEMORY_WRITE`, `CALCULATION`, `CLARIFICATION`, or
  `REFUSE`. Obvious greetings, memory commands, calculations, and recognizable forbidden scopes are
  deterministic; only ambiguous classification may use the constrained provider.
- Working memory is a bounded persisted message window plus an owner/conversation rolling summary.
  Semantic preferences and episodic runs are private by default, lifecycle-managed, and selected
  only after current SQL authorization and source revalidation. Memory is untrusted navigation
  context, never financial evidence or an instruction.
- Explicit low-sensitivity preference forms are resolved by a deterministic-first extractor before
  the constrained semantic provider, so a safe `remember INR crores` request does not fail because
  of transient model behavior. Fuzzy candidates still use the provider and every candidate still
  passes the same host-owned policy boundary.
- Episodes inherit only the reauthorized chunks cited by the accepted answer, never uncited
  retrieval distractors. A continuation extracts only the prior goal, excludes the historical
  outcome, and asks the finalizer to answer that goal from newly retrieved authorized evidence.
- Perception and Decision receive bounded safe projections of recent conversation, summary,
  semantic preferences, episodes, and the host-shortlisted tool catalog. The host owns scope,
  approval, schemas, step/retry/time limits, arithmetic, citation validation, persistence, and the
  explicit terminal state.
- The request-scoped in-process MCP catalog contains eleven tools: authorized search/excerpt,
  metric query, six fixed financial calculations, authorized memory search, and a proposal-only
  memory tool. `propose_memory` cannot write directly; host policy derives owner, ACL, and expiry.
- Authenticated POST streaming uses strict NDJSON events. Safe progress is immediate; provider
  drafts remain server-side until validation, after which only validated answer deltas and
  citations are emitted. Cancellation cancels the answer task and rolls back; an actor-scoped
  `client_message_id` safely replays completed retries without duplicate messages. The client makes
  at most one transport reconnect with that same ID and replaces prior-attempt rendering.
- The chat UI now has independently scrolling conversation and transcript regions, persisted
  history loading, deterministic first-message titles, a sticky bounded composer, validated
  streaming with Stop, compact citations/memory notices, and collapsed details/sanitized trace.
  The trace exposes only selected Perception intent, policy outcome, approved tool shortlist,
  current plan version, selected tool/status/reason, evidence-advanced flag, bounded counters, and
  terminal reason.
- Legacy `Evaluation`/`New conversation` rows are preserved in PostgreSQL but displayed with a
  bounded title derived from the first non-casual owned user message. This removes sidebar clutter
  without deleting or rewriting existing conversations.
- Alembic revisions `20260823_0012` through `20260823_0015` add automatic-memory lifecycle,
  selected intent trace, actor-scoped stream replay, and the expanded approved tool constraint.
- Current deterministic verification: 447 backend tests and 135 frontend tests pass; Ruff,
  strict mypy, Prettier, ESLint, TypeScript, Vite production build, Alembic drift checks, and each
  new revision's downgrade/re-upgrade cycle pass. The explicit opt-in live-model quality run passes
  all ten semantic checks on the configured provider; it is supplementary, not deterministic
  evidence.

Older step-by-step checkpoints below are retained as historical implementation notes. Where their
test counts, catalog size, migration head, or limitations differ, this current-head section and the
current testing guide are authoritative.

## Automatic user-isolated memory — implemented locally (2026-08-23)

- Alembic `20260823_0012` extends the existing `memories`/`memory_sources` design with typed
  `SEMANTIC`, `EPISODIC`, and `CONVERSATION_SUMMARY` records; explicit lifecycle states; origin,
  normalized-key, confidence/importance, conversation/message/run provenance, supersession,
  last-access, and a metadata-only durable audit table. PostgreSQL triggers reject cross-tenant
  company, conversation, message, and copied document-source relationships.
- Grounded chat reloads the current database authorization context on every request, loads at most
  eight owner-and-conversation-scoped messages plus one bounded rolling summary, and performs
  memory authorization/source revalidation in a materialized CTE before FTS ranking. Retrieval has
  separate semantic/episodic limits, a relevance floor, recency/importance/type weighting, a
  financial-format preference boost, deduplication, and a 2,400-character prompt budget.
- The existing provider boundary now includes strict structured memory-candidate extraction.
  The model may propose only; host policy derives the private owner/tenant/company, rejects
  sensitive/temporary/document-fact candidates, bounds content, applies retention, and owns
  ADD/NOOP/supersession behavior. Explicit preferences auto-activate; inferred preferences remain
  pending until owner confirmation. Automatic shared/department memory is impossible.
- Successful useful grounded responses create private 30-day episodic summaries with the current
  authorized chunk provenance. Every later read reauthorizes every source; revoked, replaced,
  rejected, deleted, corrupted, or unauthorized sources hide the episode. Episodes are navigation
  context only; current document retrieval and citations remain authoritative.
- `/api/memories` now supports type/status inspection, safe provenance, confirm, dismiss, and
  owner-only delete. The Memory Inspector shows semantic, episodic, and working-memory sections,
  owner/scope/origin/status/dates/reason/sources, and pending controls. Grounded Chat shows the
  non-blocking “Private preference remembered” indicator.
- Verification: Ruff and strict mypy pass; all 447 backend tests pass; all 135 frontend tests pass;
  TypeScript/Vite production build passes; focused Alice/Leo, supersession, confirmation, bounded
  summary, episode creation, and source-revocation tests pass; Alembic upgrade, check, downgrade,
  and re-upgrade pass.

## Current step

Playbook Steps 7 through 9 plus all three interview features are implementation-complete. Step 7
provides the embedded approved MCP gateway and two authorization-revalidating document tools; Step
8 provides separate typed Perception and Decision
stages plus the host-owned bounded AgentLoop. The Step 6 grounded path remains intact. Simple,
single-document, high-confidence grounded answers route to `google/gemini-3.1-flash-lite`; complex,
multi-document, low-confidence, and all agentic stages route to `google/gemini-3.7-flash`. Both use
OpenRouter through the pinned Google Vertex BYOK connection with shared fallback disabled. Scoped private,
Finance, Legal, and Shared memory is source-reauthorized before retrieval. Step 9 adds three fixed
financial calculators whose inputs are reauthorized and whose arithmetic/finalization is host-owned.

## Implemented

- A pure host-owned model policy runs only after authorization-first retrieval. It uses workload
  kind, distinct authorized document count, top authorized retrieval score, and bounded query-shape
  rules; no model, prompt, identity claim, or client field can choose authority or override a route.
  The router derives the question and distinct-document count from the actual authorized generation
  request, so inconsistent internal signal metadata cannot downgrade multi-document work.
- The shared OpenRouter Vertex client pins the exact HTTPS endpoint, `google-vertex` provider, and
  both Gemini model IDs. It disables environment proxy inheritance, provider fallback, tools,
  streaming, and reasoning parameters, then validates visible JSON strictly. Retryable Gemini 3.1
  Flash Lite failures may fall forward to Gemini 3.7 Flash;
  Gemini 3.7 Flash-first work never downgrades to Gemini 3.1 Flash Lite.
- Agent Perception, Decision, and finalization are explicitly pinned to Gemini 3.7 Flash.
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
  chunks make their memory invisible immediately. Copied document/version provenance must also
  match the current authorized source chunk. Search ranks only that materialized visible set.
- The grounded-chat prompt may receive at most five company-matched visible memories. They are
  serialized separately as untrusted, non-evidentiary context; embedded commands are ignored and
  memory IDs cannot satisfy document citation validation. Evidence tenant/company pairs are
  resolved against authorized company IDs in the database without positional ID/slug assumptions.
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
- `LLMProvider` has separate simple and heavy adapters over one typed OpenRouter Vertex client, plus
  deterministic fake-test and disabled adapters. The provider request does not send JSON-schema
  response format or reasoning parameters. System prompts require JSON only; strict local Pydantic
  validation and retries share a two-call ceiling. Empty content ending for length is incomplete.
  Provider bodies and hidden fields are never returned, persisted, logged, or rendered. No model
  tool capability is configured.
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
  `AuthorizationScope` is injected through host closures and all eleven adapters reauthorize through
  the Step 5 database predicates.
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

## Acceptance criteria

The combined three-feature gate passes. The full database-backed suite covers authorized agent and
calculator API workflows. Live OpenRouter Vertex Perception, typed-catalog Decision, and grounded
finalization pass. The dual-route smoke selected Gemini 3.1 Flash Lite for the simple one-document case and Gemini 3.7 Flash for
the multi-document case; both returned supported claims without fallback. Backend/frontend, local
MCP, migration, security, dependency, build, and repository-integrity gates pass.

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
schema transformation, then quota blocked the full chain. The OpenRouter replacement was live-verified
with the exact Gemini 3.7 Flash endpoint/model: initial Perception classified a financial lookup, initial
Decision returned a strict valid two-step plan selecting the sole permitted search tool,
step-result Perception marked synthetic authorized evidence sufficient, mid-session Decision chose
`FINALIZE`, and finalization returned one supported host-validatable cited claim with zero retry. A
nondeterministic malformed Decision was
observed once at Gemini 3.7 Flash's required temperature; validation failed closed, and the implementation now
places malformed/incomplete responses inside the same strict two-attempt total budget as transient
failures.

All three interview features were independently checkpointed and jointly verified on 2026-08-21.
Backend Ruff format/lint, strict mypy, and all 302 pytest cases pass. Frontend Prettier, ESLint,
strict TypeScript, all 98 Vitest cases, the zero-vulnerability npm audit, and production build pass.
Migration `0008 -> 0006 -> 0008` exercises both router and memory revisions and finishes at head
with no schema drift. The live router smoke returned Gemini 3.1 Flash Lite `SIMPLE_LOW_RISK` and Gemini 3.7 Flash
`MULTI_DOCUMENT`, each supported with no fallback. Calculator integration proves exact 10% EBITDA
margin, 25% revenue growth, and 3% net profit margin plus missing, malformed, zero-denominator, and
authorization failures.
The completion audit additionally verifies paired multi-company scope construction,
database-resolved company-matched chat memory, copied source document/version integrity,
actual-request-derived router signals, and agentic route-reason persistence. A fresh live smoke
again returned supported Gemini 3.1 Flash Lite `SIMPLE_LOW_RISK` and Gemini 3.7 Flash `MULTI_DOCUMENT` responses without
fallback.

Authenticated browser acceptance uses a genuinely one-document profile phrase for Auto/Fast and an
explicit FY2024/FY2025 comparison for Deep routing. It also exposed and closed a live calculator
usability gap: a Decision-stage `orion` workspace alias now resolves only when the immutable scope
contains exactly one authorized Finance company, producing the canonical `orion-main` 10% EBITDA
margin result. Unauthorized or ambiguous aliases still deny. No-model denial traces now persist the
explicit `NO_MODEL_CALL` sentinel instead of a configured-but-unused model name.

## Known limitations

- The retrieval score threshold is a deterministic routing heuristic, not a calibrated probability.
  Vertex BYOK currently requires prompt-only JSON enforcement followed by strict local validation.

- Authorization is a database-derived request-start snapshot. Grant changes are enforced on the
  next request; the application does not replace that snapshot during an in-flight request between
  retrieval or calculator steps.

- Memory retrieval currently uses secure PostgreSQL FTS plus deterministic ranking signals. Memory
  embeddings are intentionally not generated yet: adding a fake vector column/query path would
  misrepresent semantic retrieval. The repository boundary is ready for a real authorized
  embedding provider later. The MCP `propose_memory` tool is proposal-only; automatic chat
  extraction, host policy, and the authenticated HTTP lifecycle remain the only write authorities.

- Agent history and human-approval metadata are metadata-only and owner-scoped. Approval and safe
  resume are implemented; retention/deletion/export and automatic recovery after a consumed
  approval is interrupted remain out of scope.
- The browser loads up to 100 owner-scoped transcript messages per selected conversation. Older
  messages remain persisted but the UI does not yet paginate beyond that bounded window, and
  historical messages do not reconstruct their old expandable citation cards.
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
- Browser cancellation aborts the request; backend generator cleanup cancels the answer task and
  rolls back the request transaction. An upstream provider may already have received the bounded
  request before cancellation, so cancellation cannot retract data already sent to that provider.
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
fake-provider, live OpenRouter Vertex, chat/API/UI, authorization, redaction, and failure checks.

## Next approved step

Publish the isolated branch for review. No additional product feature is approved in this
checkpoint.
## Evaluation release system — complete locally

- Versioned suite `1.0.0`: 42 cases exactly (20 positive, 10 denial, 4 memory, 4 calculation, 4 abstention).
- Backend boundaries: strict contracts, manifest loader/hash, real-service runner, deterministic scorers, optional Vertex judge, PostgreSQL repository, service, admin API, and safe audit events.
- Persistence: Alembic `20260821_0009`; `evaluation_runs` and `evaluation_case_results` contain only bounded metadata and safe identifiers.
- API: `POST /api/admin/evaluations/run`, list/detail endpoints, and downloadable JSON report.
- Frontend: capability-gated run controls, advisory warning, release gates, composition, metrics, routing/cost/latency, safe filters/details, download, and prominent `SECURITY_FAILED` treatment.
- Local live deterministic result: 42 passed, 0 failed, 0 errors; every release gate scored 100%.
- Live advisory sample: `google/gemini-3.7-flash`, provider `Google`, Vertex BYOK confirmed, strict score validation passed, shared fallback disabled.

The implementation and verification artifacts remain local and uncommitted on `codex/evaluation-42`.

## Secure response modes — implemented locally

- Shared strict `ResponseMode` (`fast`, `auto`, `deep`) flows through message, routing, chat, and
  agent contracts; omitted mode defaults to Auto and model/provider/scope/route overrides remain
  forbidden extras.
- Routing records requested/resolved mode, model tier, safe reason, and upgrade status. Fast
  complex/low-confidence/multi-document requests return a safe 409 with no provider call or message
  persistence; Fast agent requests stop before Perception, Decision, MCP, and tools.
- The accessible composer radio group defaults to Auto, is disabled in flight, applies to chat and
  agent submissions, and renders route metadata plus explicit Continue-with-Deep/Cancel actions.
- Dollar cost remains unset until an applicable stable Vertex list-price snapshot is unambiguous;
  token/latency metadata remains available, and BYOK zero-cost metadata is never treated as zero
  upstream cost.
- The exact checked-in 42-case manifest is unchanged; response-mode tests are separate.

No migration is required because this is request/response and existing trace metadata, not a
persisted browser preference. Changes remain local and uncommitted on `codex/response-modes`.

## Persistent agent runs — implemented locally

- Alembic revision `20260822_0010` adds `agent_runs`, immutable `agent_plan_versions`, ordered
  `agent_steps`, and authorization-validated `agent_observation_records` with bounded constraints.
- The host state machine supports CREATED, RUNNING, AWAITING_APPROVAL, COMPLETED, REFUSED,
  CLARIFICATION_REQUIRED, INSUFFICIENT_EVIDENCE, LIMIT_REACHED, FAILED, and CANCELLED. Terminal
  states cannot transition; AWAITING_APPROVAL is a durable, resolvable pause state.
- Run creation follows owned-conversation and capability checks and follows Fast-mode preflight.
  Safe initial state is committed before model/tool execution; failures and cancellation update a
  terminal record without persisting partial plan/step/observation rows.
- Plan rows exclude model plan text and are update-immutable in ORM and PostgreSQL. Step replay and
  duplicate positions are rejected. Observation identifiers are rechecked through the current
  authorization-first chunk statement before insertion.
- `GET /api/agent-runs` uses an opaque keyset cursor; `GET /api/agent-runs/{run_id}` applies exact
  server-derived tenant/user ownership. Foreign and missing IDs share the same response.
- The capability-gated Agent History page includes paginated list, safe expansion, loading, empty,
  error, and inaccessible states using the same sanitized timeline vocabulary as live runs.
- Final verification passes 398 PostgreSQL-backed backend tests, all 42 evaluation cases and release
  gates, 116 frontend tests, Ruff/strict mypy/Prettier/ESLint/TypeScript, the production build,
  zero-vulnerability `npm audit`, the complete reversible Alembic cycle, static secret scans, and
  authenticated browser persistence/reload acceptance.

Implementation remains local, uncommitted, and unpushed on `codex/persistent-agent-runs`.

## Human approval controls — implemented locally

- Alembic `20260822_0011` adds content-free, single-use approval rows, independent
  Guided/Balanced/Autonomous control mode, initial-message reconstruction references, and canonical
  action hashes for stored steps.
- Guided pauses before every tool. Balanced automatically runs the five current low-risk read-only
  retrieval/calculator tools. Autonomous uses the same allowlist and fixed budgets;
  `ALWAYS_REQUIRE_APPROVAL` remains mandatory for future tools.
- Approve once, Reject, Stop, and Change request are owner-scoped typed APIs. Resolution reloads
  current identity and grants, locks rows, verifies status/expiry/plan/step/tool/scope/action binding,
  and prevents replay and concurrent double execution.
- Resume keeps the same run ID and reconstructs authorized prior observations from immutable IDs.
  Any action-hash or history mismatch fails closed. Reject makes zero tool calls, Stop records
  CANCELLED, and Change request preserves the cancelled old history while creating a new run.
- The accessible React approval card renders safe metadata only and disables all resolution controls
  in flight or after expiry. Agent History displays both control mode and persisted pause/final state.

Implementation remains local, uncommitted, unstaged, and unpushed on
`codex/human-approval-controls`.
