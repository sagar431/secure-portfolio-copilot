# Implementation Status

## Current milestone

Playbook Step 3 — governed synthetic-document ingestion, parsing, preview, and lifecycle management.

## Completed acceptance criteria

- Step 1 health/error foundations and Step 2 database-derived identity and authorization remain
  intact and covered by regression tests.
- Eight reversible tables persist logical documents, immutable versions, ingestion jobs, PDF pages,
  spreadsheet sheets/rows/cells, and metadata-only audit events.
- `MANAGE_UPLOADS` is enforced per workspace and company on every options, upload, status, library,
  preview, approval, rejection, version, and deletion operation. Nora can manage Orion and Atlas;
  ordinary query users cannot mount or call the admin feature.
- The backend publishes trusted tenant/company options, valid department/visibility/classification
  triples, reporting-period requirements, and upload limits. Strict multipart metadata rejects
  extra or inconsistent fields.
- PDF, XLSX, and CSV validation is bounded and fail-closed. Signature/MIME mismatches, malformed or
  encrypted/active PDFs, macros, external links, unsafe OOXML, ZIP bombs, and oversized inputs are
  rejected with safe errors.
- Parser workers have time and resource limits. Parsed output retains PDF page provenance and
  spreadsheet sheet/row/cell coordinates; formula-like cell content remains inert text.
- The exact lifecycle is `UPLOADED -> VALIDATING -> PARSING -> PREVIEW_READY`, followed by approval
  or rejection, with separate safe validation/parsing failure states and terminal deletion.
- Initial checksum duplicates are deterministic, while the explicit version endpoint creates the
  next immutable version. Actor-scoped idempotency keys prevent accidental duplicate writes.
- Approval is allowed only after a successful version-addressed preview. Rejected versions cannot
  later be approved. Soft deletion immediately hides all versions and removes stored objects.
- React provides capability-gated navigation, trusted cascading metadata controls, XHR upload
  progress, abortable status polling, safe request-ID errors, a filterable library, PDF/spreadsheet
  preview, version upload, approval/rejection, and accessible deletion confirmation.

## Pending acceptance criteria

None within Step 3.

## Verification result

Verified on 2026-08-21:

- Backend formatting, linting, strict type checking, and the full 103-test suite pass, including real
  PostgreSQL, parser, storage, upload-security, authentication, policy, and regression coverage.
- Frontend formatting, linting, strict type checking, Vitest, and production build pass.
- Alembic clean upgrade, drift check, downgrade to Step 2, and re-upgrade pass; all eight Step 3
  tables were inspected in PostgreSQL.
- Live Nora uploads pass for the real Orion PDF (4 pages), Orion workbook (7 named sheets), and the
  unsafe CSV fixture (formula-like strings preserved inert). Approval and deletion behave as
  specified.
- The fake PDF returns safe HTTP 415 with a request ID; Alice receives HTTP 403 before admin options
  or upload work; deleted preview returns safe HTTP 404.
- The `Simulated_data` content hash is unchanged.

## Known limitations

- Password login and demo users are development-only; production requires an external identity
  provider in a later hardening phase.
- Access tokens are held in browser `sessionStorage`; production should prefer a hardened session or
  HttpOnly cookie design with CSRF controls.
- There is no refresh token; a session expires after 15 minutes and the user signs in again.
- Each synthetic user currently has one home membership. The contracts support multiple active
  membership-derived grants, but no workspace-switching UI exists.
- Parsing runs synchronously behind an ingestion-job contract in this local milestone; a durable
  distributed queue is not implemented.
- Local object storage is for development only. Production object storage, malware scanning, and a
  retention worker remain later hardening work.
- Deletion is immediate and soft at the database level. A later retention process may hard-delete
  metadata; that process is not part of Step 3.
- Approved documents are deliberately not queryable. Retrieval, chunking, embeddings, LLMs, MCP,
  memory, calculations, agents, and AWS remain absent.

## Test commands

See [docs/testing-guide.md](docs/testing-guide.md) for exact automated, migration, seed, live API,
and UI verification commands.

## Next approved milestone

None. Work stops after Step 3 until the user explicitly approves a later milestone.
