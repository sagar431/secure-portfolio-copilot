# Codex Build Playbook

## Secure Multi-Tenant Portfolio Due-Diligence Copilot

**Purpose:** Exact, stepwise prompts for building the MVP with Codex while learning and verifying every backend, frontend, security, MCP, and agent-loop feature.

**Source of truth:** `PRD.md` remains authoritative. This playbook controls implementation order and the conversation with Codex.

**Core demo completion:** Steps 0–11.

**Optional post-demo extensions:** Step 12 memory and Step 13 sandbox analysis.

---

## 1. What the finished core demo proves

The core demonstration must support four reliable workflows:

1. An Orion Finance user asks why EBITDA margin changed, and the system retrieves authorized metrics and evidence, calculates deterministically, and answers with citations.
2. The same Finance user asks for a Legal-only clause, and the request is denied before retrieval or model context construction.
3. The Orion user asks for Atlas information, and cross-tenant/company access is denied.
4. The developer trace visibly shows Perception → Policy → MCP Gateway → Decision → Tool → Observation → Finalization.

Do not add multi-agent collaboration, dynamic tool installation, unrestricted code execution, live Gmail/Drive, Neo4j, browser agents, or production AWS before these four workflows pass.

---

## 2. Prepare the repository once

Create a new Git repository and place the following at the root:

```text
portfolio-copilot/
├── PRD.md
├── CODEX_BUILD_PLAYBOOK.md
└── references/
    └── eag/
```

Do not copy every course file into the repository. Add only the selected reference files named in the active step. Production code must never import from `references/eag/`.

Create a checkpoint commit manually after each step passes. Codex must not create commits unless explicitly instructed.

---

## 3. Paste this master instruction once at the beginning

```text
You are helping me build the Secure Multi-Tenant Portfolio Due-Diligence Copilot defined in PRD.md.

Read PRD.md and CODEX_BUILD_PLAYBOOK.md completely before taking action. PRD.md is the product source of truth. CODEX_BUILD_PLAYBOOK.md controls implementation order.

Operating rules:

1. Work on only the active numbered step I provide. Do not implement later steps for completeness.
2. Before editing, inspect the repository and relevant selected EAG reference files. Explain what you will reuse conceptually, what you will reject, and why.
3. Never import production code from references/eag/. Rewrite concepts using typed, testable product code.
4. Preserve all unrelated user changes.
5. Keep authentication, authorization, tenant filtering, tool validation, calculations, retry limits, and audit behavior in deterministic code—not prompts.
6. Never execute unrestricted LLM-generated Python, SQL, shell commands, filesystem paths, or URLs.
7. Never let an LLM provide tenant_id, user_id, role, department, authorization scope, or allowed tools.
8. Use strict typed schemas between layers.
9. Write unit/integration/security tests with each feature. Use fake model and embedding providers in tests.
10. Do not expose chain-of-thought. Traces may show typed decisions, reason codes, evidence IDs, tool names, status, latency, and limits.
11. Update IMPLEMENTATION_STATUS.md and LEARNING_NOTES.md after implementation.
12. Report exact commands run, pass/fail results, manual verification steps, changed files, database changes, and known limitations.
13. If a required dependency, credential, decision, or reference file is missing, stop and explain the exact blocker. Do not silently replace the architecture.
14. Do not start the next numbered step. Wait for my approval.

For every active step, first produce a plan mapped to the step’s acceptance criteria and wait for approval before writing code.

Confirm these rules and inspect the repository. Do not implement anything yet.
```

Expected result: Codex confirms the contract and describes the current repository without changing files.

---

## 4. Reusable prompts after every step plan

### 4.1 Approve and build

After reviewing Codex’s plan, paste:

```text
Approved. Implement exactly the active step’s approved plan and acceptance criteria. Do not implement future steps.

Run all relevant formatting, type-checking, unit, integration, security, and frontend tests available for this step. Update IMPLEMENTATION_STATUS.md and LEARNING_NOTES.md.

When finished, provide:
1. outcome first;
2. files created or changed;
3. backend, frontend, and database flow;
4. authorization/security behavior;
5. exact test commands and results;
6. manual verification steps for me;
7. known limitations;
8. questions I should be able to answer before moving forward.

Do not start the next step and do not commit changes.
```

### 4.2 Independent verification

After Codex says implementation is complete, paste:

```text
Verify the active step independently. Do not add new features.

Inspect the actual diff and acceptance criteria. Run the full relevant test set, including negative/security cases. Perform or simulate the documented manual flow where possible. Check that no later-step feature was accidentally introduced.

Report:
1. PASS or FAIL for every acceptance criterion;
2. evidence from tests or inspected behavior;
3. regressions or security concerns;
4. untested assumptions;
5. whether it is safe to create a checkpoint and proceed.

If anything fails, fix only failures within the active step, rerun verification, and report the final status. Do not start the next step.
```

### 4.3 Failure recovery

If a manual test fails, paste:

```text
The active step failed this manual test:

<paste the command, input, expected result, and actual result here>

Diagnose this failure only. Reproduce it, identify the root cause with evidence, implement the smallest correct fix within the active step, and rerun relevant regression and security tests. Do not change architecture or implement future features. Report the root cause, changed files, tests, and new manual verification steps.
```

### 4.4 Checkpoint request

After verification passes, paste:

```text
The active step is approved. Summarize a suitable checkpoint commit message and list the exact files that belong to this step. Do not commit and do not start the next step.
```

Review the file list, create the commit manually, and then move to the next numbered prompt.

---

# CORE DEMO BUILD

## Step 0 — Architecture freeze and reference-code audit

### Add these EAG references

Copy only representative Session 6 models/cognitive-layer files into:

```text
references/eag/step-0/
```

Do not include the entire course repository.

### Paste this prompt

```text
Active step: Step 0 — Architecture freeze and reference-code audit.

Do not write application code.

Read PRD.md completely. Inspect the repository and selected Session 6 reference files under references/eag/step-0/.

Produce:

1. a concise product summary and the four required demo workflows;
2. an architecture decision record confirming a modular single-agent loop, not a multi-agent MVP;
3. a trust-boundary diagram covering UI, FastAPI, authentication, Perception, policy, MCP Gateway, Decision, MCP servers, data stores, observation validation, and finalization;
4. an LLM-versus-deterministic ownership table;
5. the proposed repository tree;
6. the required typed contracts: TrustedIdentity, AuthorizationScope, PerceptionResult, PlanVersion, Action, Observation, AgentState, EvidenceReference, CalculationResult, and terminal statuses;
7. an EAG reuse report listing adopt, adapt, and reject decisions;
8. the exact test strategy for tenant denial, department denial, tool authorization, calculation exactness, citation support, and bounded execution;
9. unresolved decisions that materially block Step 1.

Important decisions already fixed:

- one modular agent with separate Perception and Decision calls;
- one embedded MCP Gateway for the MVP;
- typed tool actions, never raw executable code;
- deterministic RBAC + ABAC authorization;
- conservative bounded planning;
- synthetic data only;
- memory and sandbox are optional later steps.

Wait for approval. Do not create or modify files.
```

### Gate before Step 1

You must be able to explain:

- why separate prompts do not automatically mean multiple agents;
- where authorization occurs;
- why the LLM never receives or creates authorization fields;
- why the MCP Gateway is not itself an MCP tool.

---

## Step 1 — Repository scaffold and development harness

### Paste this prompt

```text
Active step: Step 1 — Repository scaffold and development harness.

Implement only the technical foundation. Do not add authentication, uploads, retrieval, embeddings, LLM calls, MCP, memory, or financial calculations.

Required implementation:

Backend:
- FastAPI application with /health and /ready endpoints;
- Pydantic v2 settings loaded from environment with a safe checked-in example file;
- SQLAlchemy 2 and Alembic structure;
- PostgreSQL/pgvector development configuration through Docker Compose;
- consistent API success/error envelope and request ID middleware;
- structured logging without sensitive request bodies;
- pytest setup.

Frontend:
- React + TypeScript + Vite application;
- routing and basic application shell;
- backend health-status component;
- API client with typed error handling;
- Vitest/React Testing Library setup.

Repository:
- README.md with setup commands;
- IMPLEMENTATION_STATUS.md;
- LEARNING_NOTES.md;
- docs/architecture.md, docs/security-invariants.md, and docs/testing-guide.md placeholders with meaningful Step 1 content;
- formatter, lint, type-check, and test commands.

Acceptance criteria:
- backend health and readiness tests pass;
- frontend renders and can display backend health;
- database starts and an empty Alembic migration cycle succeeds;
- one backend and one frontend failure-path test pass;
- no LLM/MCP/retrieval code exists;
- a new developer can follow README commands.

First inspect and return the implementation plan, exact files, dependencies, commands, and risks. Wait for approval before editing.
```

### Manual gate

- Start database.
- Apply migrations.
- Start backend and frontend.
- Confirm the UI reports backend health.
- Stop and restart everything using only README commands.

---

## Step 2 — Identity, tenancy, departments, and policy engine

### Paste this prompt

```text
Active step: Step 2 — Identity, tenancy, departments, and policy engine.

Implement deterministic identity and authorization only. Do not add documents, retrieval, LLM calls, or MCP.

Required domain data:
- two tenants or isolated client workspaces;
- Orion and Atlas companies;
- Finance, Legal, and Shared departments/classifications;
- seeded users: Nora Admin, Alice Orion Finance, Leo Orion Legal, and Ava Atlas Finance;
- memberships and company/workspace assignments.

Backend:
- database models and migration for tenants, companies, users, memberships, roles, departments, and workspace/company grants;
- development-only password login and signed JWT validation;
- GET /api/auth/me;
- immutable TrustedIdentity and AuthorizationScope models;
- deterministic RBAC + ABAC policy engine;
- reason-coded allow/deny decisions;
- policy repository/service tests.

Frontend:
- login page with development demo-user cards;
- protected routes;
- active tenant, company, role, and department display;
- logout behavior;
- clear authentication error states.

Security requirements:
- derive identity and tenant server-side;
- ignore forged tenant/user/role fields in request bodies;
- deny by default;
- never use an LLM for authorization;
- do not reveal the existence or content of inaccessible resources.

Acceptance criteria:
- Alice gets Orion Finance + Shared scope only;
- Leo gets Orion Legal + Shared scope only;
- Ava gets Atlas Finance + Shared scope only;
- Alice cannot acquire Legal or Atlas scope by modifying client input;
- expired/invalid tokens fail;
- frontend cannot bypass backend policy;
- positive and negative API/security tests pass.

First produce a plan, data model, policy matrix, endpoint contracts, files, migration, tests, and manual demo. Wait for approval before editing.
```

### Manual gate

Log in as each seeded user and record `/api/auth/me`. Attempt to forge tenant, role, department, and company fields. Every forged value must be ignored or denied.

---

## Step 3 — Synthetic portfolio data, upload, parsing, and approval

### Add these EAG references

Copy selected Session 8 PDF/XLSX parsing and safe-input examples into:

```text
references/eag/step-3/
```

### Paste this prompt

```text
Active step: Step 3 — Synthetic portfolio data, upload, parsing, and approval.

Implement the governed ingestion vertical slice. Do not add embeddings, generative answers, MCP, or agent planning.

Create synthetic, clearly fictional demo data for Orion and Atlas:
- Finance spreadsheet with 2024/2025 revenue, EBITDA, cash, and debt;
- Finance/board PDF explaining operating changes;
- Legal PDF containing clauses and risks;
- Shared company overview;
- ground-truth manifest containing source locations and expected access.

Backend:
- Document, DocumentVersion, IngestionJob, ParsedPage/Sheet/Row or equivalent models and migrations;
- admin-only upload endpoint;
- required classification: tenant, company, department, visibility, document type, version;
- PDF, XLSX, and CSV validation by MIME/content, size, checksum, and extension;
- development object-store adapter;
- parsing with page/sheet/row provenance;
- preview, approve, reject, and delete workflow;
- authorization on every operation;
- idempotent checksum/version behavior.

Frontend:
- admin upload page;
- classification form;
- upload progress and failure states;
- parsed preview with page/sheet/row locations;
- approve/reject controls;
- authorized document library.

Security:
- no arbitrary filesystem path input;
- no arbitrary URL ingestion;
- sanitize filenames;
- content limits and parser failure handling;
- no indexing before approval;
- no cross-tenant classification by an unauthorized admin.

Acceptance criteria:
- Nora uploads and approves one Orion Finance PDF and spreadsheet;
- preview preserves page/sheet/row provenance;
- invalid type/oversized/malformed files fail safely;
- non-admin upload/approval fails;
- Orion documents cannot be classified as Atlas without permission;
- deletion/version behavior is tested;
- no embeddings or LLM calls exist.

Inspect the selected EAG reference files, identify unsafe assumptions, and produce a plan, schema, API contracts, UI flow, tests, and synthetic-data manifest before editing. Wait for approval.
```

### Manual gate

Upload one PDF and one XLSX. Verify preview locations. Reject one version and approve another. Confirm a non-admin cannot upload or approve.

---

## Step 4 — Secure chunks and deterministic retrieval baseline

### Add these EAG references

Copy selected Session 7 chunk/metadata and top-k examples into:

```text
references/eag/step-4/
```

### Paste this prompt

```text
Active step: Step 4 — Secure chunks and deterministic retrieval baseline.

Implement approved-document chunking and keyword retrieval. Do not add embeddings, LLM answer generation, MCP, or agent orchestration.

Backend:
- DocumentChunk model and migration;
- deterministic PDF and spreadsheet chunking;
- inherited tenant/company/department/visibility/version/status metadata on every chunk;
- page/sheet/row provenance;
- authorized repository query that requires AuthorizationScope;
- keyword/BM25-style or PostgreSQL full-text baseline;
- result DTO with evidence IDs, source locations, scores, and document metadata;
- no repository method capable of unscoped production retrieval.

Frontend:
- development-only authorized-search page;
- show active scope, query, returned IDs, metadata, provenance, and scores;
- never display forbidden candidates.

Security requirements:
- apply tenant/company/department/status filters before results leave the repository;
- UI filtering is not a security control;
- caches, if any, include scope fingerprint and source version;
- denied results must not appear in logs or traces.

Acceptance criteria:
- Alice can retrieve Orion Finance and Shared chunks;
- Alice cannot retrieve Orion Legal or any Atlas chunks;
- Leo can retrieve Orion Legal and Shared but not Orion Finance;
- Ava cannot retrieve Orion chunks;
- inactive/rejected/deleted versions are absent;
- every result includes valid provenance;
- cross-tenant and cross-department security tests pass 100%.

Inspect the EAG reference, then propose the chunk contract, repository API, query strategy, negative tests, UI, and exact files. Wait for approval before editing.
```

### Manual gate

Run the same query as Alice, Leo, and Ava. Record returned document/chunk IDs. Confirm forbidden IDs never appear.

---

## Step 5 — Embeddings, hybrid retrieval, and citations

### Add these EAG references

Copy selected Session 7 embedding and Session 11 retrieval-scoring examples into:

```text
references/eag/step-5/
```

### Paste this prompt

```text
Active step: Step 5 — Embeddings, hybrid retrieval, and citations.

Upgrade the authorized retrieval baseline with embeddings and hybrid ranking. Do not generate natural-language answers and do not add MCP or the AgentLoop.

Backend:
- EmbeddingProvider interface with deterministic fake provider for tests and one configurable development provider;
- pgvector migration and embedding lifecycle tied to approved active document versions;
- hybrid keyword + vector retrieval;
- deterministic authorization filters applied before any result is returned;
- bounded top_k and context limits;
- optional reranker interface only, unless necessary for measured quality;
- citation DTO resolving document title, page/sheet/row, version, and excerpt;
- retrieval evaluation dataset from synthetic ground truth;
- retrieval trace containing only permitted IDs/scores.

Frontend:
- enhance the authorized-search page with keyword, vector, and final scores;
- citation preview from returned evidence;
- evaluation summary for curated queries.

Acceptance criteria:
- known questions retrieve expected authorized chunk IDs in top 5;
- recall@5 is measured and reported;
- citation locations resolve correctly;
- restricted chunks never enter reranking or returned context;
- embeddings are regenerated or invalidated on version changes;
- tests do not require a live embedding API.

Inspect the references and produce a plan, scoring formula, authorization order, provider interface, evaluation cases, tests, and files. Wait for approval.
```

### Manual gate

Run the curated retrieval questions, inspect top results and citations, then rerun as unauthorized users and confirm zero leakage.

---

## Step 6 — Grounded RAG chat before agent orchestration

### Paste this prompt

```text
Active step: Step 6 — Grounded RAG chat before agent orchestration.

Build a simple non-agentic grounded RAG answer path on top of the already-tested authorized retriever. Do not add MCP, Perception, Decision, planning, memory, or calculations.

Backend:
- Conversation and Message models/migration;
- LLMProvider interface with fake deterministic provider for tests and one configured real provider;
- POST conversation message endpoint;
- authorized retrieval before prompt construction;
- prompt containing only permitted evidence;
- grounded-answer schema with answer status, claims, evidence references, and limitations;
- controlled insufficient-evidence and authorization-denial behavior;
- final citation-reference validation;
- token/context/output limits;
- sanitized request trace for retrieval and generation.

Frontend:
- conversation list and chat workspace;
- suggested questions;
- inline citations and evidence drawer;
- insufficient-evidence and denial cards;
- loading, cancellation, and error states.

Acceptance criteria:
- authorized Orion Finance question returns a supported cited answer;
- unsupported question abstains;
- Finance request for Legal data is denied before retrieval/generation;
- Atlas request by Alice is denied;
- every factual claim references permitted evidence;
- fake-provider integration tests are deterministic;
- no agent loop or tool calling exists yet.

Produce the plan, prompt boundary, API schema, citation validator, frontend flow, tests, and exact files. Wait for approval.
```

### Manual gate

Ask one supported, one unsupported, one Legal-only, and one Atlas question as Alice. Inspect evidence and the sanitized trace.

---

## Step 7 — Embedded MCP Gateway and document tools

### Add these EAG references

Copy selected Session 4 MCP server/client files, Session 8 typed-tool examples, and Session 9 heuristic examples into:

```text
references/eag/step-7/
```

### Paste this prompt

```text
Active step: Step 7 — Embedded MCP Gateway and document tools.

Replace direct retriever service invocation in the future agent path with a production-safe embedded MCP Gateway. Preserve the existing non-agentic RAG path as a regression reference. Do not add Perception/Decision yet.

Implement:

MCP server:
- search_authorized_documents;
- get_document_excerpt;
- strict input/output schemas;
- common structured result/error envelope;
- trusted authorization context injected out of band;
- server-side reauthorization.

Embedded MCP Gateway:
- ToolRegistry;
- CapabilityMapper interface;
- PolicyEngine integration;
- ActionGuard;
- MCPRouter/client manager;
- ResultValidator;
- AuditRecorder;
- health/timeout/retry/error classification;
- authorized tool-catalog filtering.

Rules:
- do not expose tenant_id, user_id, role, department, or allowed scope as model/tool arguments;
- do not expose run_python, run_sql, run_shell, read_file(path), arbitrary URL, or write tools;
- tool hiding is not sufficient: every call must be reauthorized;
- use the current installed MCP SDK patterns; do not copy obsolete course transport assumptions blindly;
- one embedded gateway is enough; no tunnel handler or separate gateway service.

Frontend/developer UI:
- inspectable permitted tool catalog for the active demo user;
- gateway trace showing discovered, authorized, shortlisted, called, allowed/denied, latency, and error type;
- never expose raw restricted content.

Acceptance criteria:
- Alice and Leo receive different permitted catalogs where policy requires;
- an unknown or unauthorized tool fails before server execution;
- malformed arguments fail schema validation;
- forged authorization arguments have no effect;
- timeout and one transient retry are tested;
- document tools return structured authorized evidence;
- all MCP contract/security tests pass.

Inspect the selected EAG files, identify current-versus-course MCP assumptions, and produce an architecture/reuse report, tool schemas, gateway flow, exact files, and tests. Wait for approval.
```

### Manual gate

Inspect Alice and Leo’s catalogs. Call both document tools through the gateway. Attempt an unauthorized and malformed call. Confirm audit events and no tool execution on denial.

---

## Step 8 — Perception, Decision, and bounded AgentLoop

### Add these EAG references

Copy only these Session 10-style references into:

```text
references/eag/step-8/
```

- AgentLoop;
- AgentSession and step/snapshot models;
- Perception implementation and prompt;
- Decision implementation and prompt;
- MultiMCP and one minimal server;
- query heuristics;
- run_user_code only as an unsafe example;
- live session trace.

Optionally add selected Session 17 structured-flow/timeout examples. Do not add parallel plan variants.

### Paste this prompt

```text
Active step: Step 8 — Perception, Decision, and bounded AgentLoop.

Build the EAG-inspired cognitive loop using the safe gateway and document tools already implemented. Do not add financial calculations, memory, sandbox code, or multiple agents.

First audit the Session 10 references and explicitly identify:
- duplicated initial memory input;
- missing authorization;
- unrestricted run_user_code/raw code execution;
- unconditional pdb breakpoint;
- unbounded while loop;
- incomplete terminal state when a plan is exhausted;
- unscoped memory;
- loss of structured tool metadata;
- plan-version/completed-step behavior.

Implement:

Perception:
- investment-domain user_query mode;
- step_result mode receiving a structured Observation;
- strict typed schema for intent, domain, entities, result requirement, required capabilities, ambiguities, risk flags, evidence status, local/global goal status, confidence, and brief rationale;
- no authorization, tool selection, calculation, or direct use of restricted information.

Decision:
- initial and mid_session modes;
- one-to-three-step plan_text;
- exactly one next typed action;
- allowed actions: TOOL_CALL, FINALIZE, CLARIFY, REFUSE;
- tool choice only from the gateway-provided permitted shortlist;
- no Python/SQL/source-code output and no authorization fields.

AgentLoop:
- one typed AgentState;
- plan versions preserving completed history;
- gateway invocation through ActionGuard;
- structured observations returned to step-result Perception;
- continue, one replan, clarify, refuse, finalize, or fail transitions;
- maximum four tool steps, one transient retry, one retrieval rewrite, and one replan;
- explicit terminal states COMPLETED, REFUSED, NEEDS_CLARIFICATION, INSUFFICIENT_EVIDENCE, LIMIT_REACHED, FAILED;
- no final answer merely because plan text is exhausted;
- final authorization/citation validation;
- sanitized trace with typed decisions and no chain-of-thought.

Testing:
- fake Perception, fake Decision, and fake MCP Gateway for deterministic state-machine tests;
- initial direct completion;
- one successful tool call;
- multiple sequential calls;
- useful partial result;
- unhelpful result and one replan;
- malformed/unauthorized action;
- clarification;
- refusal;
- timeout/retry;
- limit reached;
- exhausted plan;
- finalization validation failure.

Acceptance criteria:
- separate Perception and Decision model calls are observable;
- Decision never executes raw code;
- only gateway-permitted tools can execute;
- output returns to Perception before the next Decision;
- every request reaches an explicit terminal status;
- the non-agentic RAG regression path still passes;
- state-machine/security tests pass without a live model.

Produce the reuse audit, contracts, state diagram, transition table, prompt files, exact implementation plan, tests, and migration needs. Wait for approval before editing.
```

### Manual gate

Ask an authorized document question and inspect every structured transition. Trigger clarification, denial, insufficient evidence, and a synthetic tool timeout. Confirm bounded termination.

---

## Step 9 — Financial metric and deterministic calculation tools

### Add these EAG references

Copy selected Session 8 safe math/SQL/tool-schema examples into:

```text
references/eag/step-9/
```

### Paste this prompt

```text
Active step: Step 9 — Financial metric and deterministic calculation tools.

Add financial data and approved calculations to the existing MCP Gateway and AgentLoop. Do not add a general sandbox, unrestricted SQL, stock trading, external market APIs, or memory.

Backend/data:
- normalized FinancialMetric records populated from approved synthetic spreadsheets;
- period, metric definition, value, currency, unit, company, source document, sheet, and row provenance;
- deterministic approved formula registry.

MCP tools:
- query_financial_metrics;
- calculate_financial_metric.

Initial formulas:
- EBITDA_MARGIN;
- REVENUE_GROWTH;
- NET_PROFIT_MARGIN;
- DEBT_TO_EQUITY;
- CASH_RUNWAY;
- CAGR.

Rules:
- LLM never performs authoritative arithmetic;
- metric queries use parameterized repository methods, not model-generated SQL;
- calculator accepts formula enum and validated numeric inputs;
- every result returns formula, inputs, result, unit, warnings, and evidence references;
- validate period alignment, currency, units, missing values, division by zero, and stale/conflicting records;
- authorization applies before metric retrieval and again at the tool.

Agent behavior:
- Perception recognizes financial lookup/comparison/calculation;
- gateway shortlists metric and calculator tools;
- Decision retrieves inputs before calculation;
- step-result Perception checks input/evidence completeness;
- final answer distinguishes source facts, calculated values, and interpretation.

Frontend:
- calculation breakdown card;
- formula, inputs, units, result, evidence links, and warnings;
- trace shows metric query then calculator invocation.

Acceptance criteria:
- Orion 2024/2025 EBITDA margins are exact and reproducible;
- Finance user receives authorized values and citations;
- Legal-only or Atlas values are unavailable to Alice;
- missing/division-by-zero/currency/unit cases are tested;
- no authoritative arithmetic appears only in LLM output;
- calculation and authorization tests pass 100%.

Inspect references and produce the normalized schema, formula contracts, tool schemas, agent flow, UI, tests, and exact files. Wait for approval.
```

### Manual gate

Ask for Orion 2024/2025 EBITDA margins. Independently calculate expected values. Verify exact equality, evidence locations, and denial for Atlas.

---

## Step 10 — Presentation-quality developer trace

### Paste this prompt

```text
Active step: Step 10 — Presentation-quality developer trace.

Build the trace UI and sanitized observability needed to explain the system in an interview. Do not add new agent capabilities.

Backend:
- RequestTrace/AgentRun, PlanVersion, AgentStep, ObservationRecord, tool-call, validation, and terminal-status persistence or suitable development trace store;
- request/event API for a completed run and optional sanitized streaming during execution;
- trace DTO that contains IDs, typed summaries, reason codes, status, scores, formula metadata, timing, token/cost estimates, retries, replans, and stopping reason;
- redaction and access control on trace APIs;
- no raw system prompts, hidden reasoning, secrets, restricted candidates, or full confidential chunks.

Frontend trace drawer/timeline:
1. User query received;
2. initial Perception;
3. trusted authorization scope summary;
4. gateway catalog discovered/authorized/shortlisted counts;
5. Decision plan version and next action;
6. ActionGuard decision;
7. MCP tool execution;
8. structured Observation;
9. step-result Perception;
10. Decision continuation/replan/finalization;
11. final citation/numeric/security validation;
12. terminal status and stopping reason.

UX requirements:
- readable demo mode;
- plan-version differences visible;
- citations and calculation evidence open from trace;
- denial clearly shows zero tools called;
- failures show sanitized error class and retry decision;
- normal users do not see development trace unless authorized.

Acceptance criteria:
- authorized financial workflow is understandable from the trace without opening code;
- department and tenant denial traces show no restricted content and no tool execution;
- transient failure trace shows at most one retry/replan;
- trace access is tenant/user/admin controlled;
- redaction and authorization tests pass;
- frontend end-to-end tests cover success, denial, and calculation traces.

First provide wireframe, trace schema, redaction policy, access rules, endpoint contracts, tests, and files. Wait for approval.
```

### Manual gate

Run the four demo workflows and explain every trace event aloud. Confirm no hidden reasoning or forbidden evidence appears.

---

## Step 11 — Evaluation, demo reset, and release hardening

### Paste this prompt

```text
Active step: Step 11 — Evaluation, demo reset, and release hardening.

Do not add product capabilities. Make the four core workflows reliable, measurable, resettable, and presentable.

Build:
- deterministic synthetic reset/seed command;
- evaluation case schema and curated dataset;
- at least 20 supported questions;
- at least 10 explicit tenant/department deny tests;
- at least 4 calculation tests;
- at least 4 insufficient-evidence tests;
- agent-loop transition/failure cases;
- retrieval recall@5;
- citation presence and support checks;
- calculation exactness;
- authorization deny rate;
- abstention correctness;
- latency and estimated-cost summary;
- one-command backend/frontend/evaluation test flow;
- final README and demo script;
- fallback screenshots or recorded trace fixtures if the live model is unavailable;
- documented prototype limitations and production evolution.

Release gates:
- cross-tenant deny pass rate: 100%;
- cross-department deny pass rate: 100%;
- calculation exactness for approved formulas: 100%;
- citation presence for factual answers: 100%;
- every AgentLoop run has an explicit terminal state;
- no unauthorized content appears in prompts, answers, traces, caches, or logs during negative tests;
- reset and replay work from documented commands;
- all four demo workflows pass end to end.

Do not claim production certification. Clearly label synthetic data, development authentication, embedded gateway, and remaining production work.

First audit the entire implemented core against PRD.md. Produce a gap report and a Step 11 plan. Wait for approval before editing.
```

### Final core-demo gate

Run and record:

1. Alice authorized Orion Finance analysis.
2. Alice denied Orion Legal clause.
3. Alice denied Atlas data.
4. Orion EBITDA-margin query with metric and calculator tools.

Do not start memory or sandbox until this gate passes.

---

# OPTIONAL EXTENSIONS

## Step 12 — Isolated, permission-inheriting memory

### Add these EAG references

Copy selected Session 7 memory and semantic-retrieval examples into:

```text
references/eag/step-12/
```

### Paste this prompt

```text
Active optional step: Step 12 — Isolated, permission-inheriting memory.

The core demo is already passing. Add memory without weakening any authorization or retrieval invariant.

Implement:
- working conversation memory;
- private user preferences;
- approved department/workspace memory;
- operational failure history that is not injected by default;
- metadata-first tenant/user/department/workspace/sensitivity/expiry filtering;
- source provenance and ACL inheritance;
- memory candidate extraction by LLM;
- deterministic validation, deduplication, conflict handling, visibility, TTL, and write approval;
- search_memory and write_memory MCP tools;
- memory inspector and delete/correct controls.

Do not store:
- chain-of-thought;
- secrets;
- complete documents;
- unauthorized content;
- unsupported conclusions;
- calculations without source/input provenance;
- every conversation forever.

Acceptance criteria:
- Alice can store and retrieve “show INR in crores” privately;
- Leo and Ava cannot retrieve Alice’s private memory;
- Finance-derived memory cannot become Legal or Shared-visible without valid policy;
- deleted/expired memory is not returned;
- source access is rechecked on every read;
- memory-isolation tests pass 100%.

Inspect the EAG references, explain why global FAISS memory is unsuitable, and produce schema, read/write paths, policy, MCP schemas, frontend, tests, and files. Wait for approval.
```

---

## Step 13 — Optional model-generated Python in an isolated sandbox

### Paste this prompt

```text
Active optional step: Step 13 — Model-generated Python in an isolated sandbox.

The core demo and memory tests must already pass. Add sandbox analysis only for open-ended computations that approved tools cannot solve.

Architecture:
- Decision may select only a typed analyze_in_sandbox tool with task, authorized file IDs, allowed sheets, and expected output schema;
- Decision must not return source code;
- an internal sandbox code-generation component may generate Python;
- static validation occurs before execution;
- code executes only inside an ephemeral isolated environment;
- output becomes a structured Observation and returns to Perception.

Sandbox restrictions:
- no host execution;
- no public or private network by default;
- no credentials or application secrets;
- only explicitly authorized staged files;
- read-only input and controlled output directories;
- approved library allowlist;
- no subprocess, socket, package installation, cloud SDK, arbitrary filesystem, or database access;
- CPU, memory, time, output-size, and process limits;
- one repair attempt maximum;
- automatic cleanup and sanitized audit.

Clarify capability gaps:
- sandbox may handle custom computation on authorized data;
- it cannot bypass missing data, missing credentials, policy denial, unavailable external services, or unsupported transactions;
- repeated successful sandbox tasks should be reviewed and promoted manually into tested deterministic MCP tools.

Acceptance criteria:
- authorized downside-scenario spreadsheet analysis succeeds reproducibly;
- unauthorized file access fails;
- filesystem/network/credential access fails;
- infinite loop is terminated;
- malformed output is rejected;
- fixed approved formulas continue using calculate_financial_metric;
- the main AgentLoop never executes raw code.

First produce threat model, sandbox-provider decision, interface, validation policy, tests, cost/cleanup behavior, and exact files. Wait for approval.
```

---

## 5. Prompts for interview preparation after the build

### Ask Codex for an end-to-end code walkthrough

```text
Do not modify code. Teach me the completed authorized financial-analysis workflow using the actual repository.

Start from the React submit handler and follow the exact request through FastAPI, TrustedIdentity, Perception, policy, MCP Gateway discovery/filtering, Decision, ActionGuard, MCP tools, Observation, replanning/finalization, validation, database reads, and frontend rendering.

For every transition, name the file, class/function, typed input, typed output, security invariant, expected trace event, and relevant test. Then ask me ten questions to verify I understand it.
```

### Ask Codex for a denial walkthrough

```text
Do not modify code. Walk me through the actual code path when Alice asks for an Orion Legal-only clause and when she asks for Atlas data.

Prove from repository code and tests that denial occurs before restricted retrieval, memory, MCP execution, model context construction, caching, and logging. Identify every defence-in-depth check and explain what would happen if one layer contained a bug.
```

### Ask Codex to conduct a mock interview

```text
Act as a skeptical Forward Deployed/Presales AI Engineer interviewer reviewing this repository and demo.

Ask one question at a time about requirements discovery, architecture, Perception versus Decision, single-agent versus multi-agent, MCP discovery, gateway authorization, RBAC/ABAC, tenant isolation, RAG quality, calculations, memory, sandboxing, retries, observability, cost, scaling, and production migration.

After each answer, grade me from 1–5, identify the missing technical point, and give a stronger concise answer grounded in this repository. Do not modify code.
```

---

## 6. Final rule

Never move to the next step because the code “looks complete.” Move only after:

1. automated acceptance tests pass;
2. negative/security tests pass;
3. the manual gate passes;
4. you can explain the frontend, backend, database, LLM, MCP, and policy flow;
5. a checkpoint exists.

Four reliable workflows are more valuable than thirteen partially working features.
