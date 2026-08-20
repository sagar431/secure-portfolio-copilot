# Deliberately Invalid Inputs

These files are negative tests and must never be indexed.

- `not_a_real_pdf.pdf`: reject because its bytes do not match the PDF signature.
- `unsafe_spreadsheet_cells.csv`: accept only if all formula-like cells remain inert text; do not execute links or commands.
- `invalid_metadata.json`: reject because the declared tenant conflicts with the filename-implied tenant.

Expected behavior is fail closed, emit an audit event, and expose no extracted text to an LLM.
