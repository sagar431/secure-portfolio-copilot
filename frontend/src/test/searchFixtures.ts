import type { AuthorizedSearchData } from '../types/search'

export const authorizedSearchData: AuthorizedSearchData = {
  status: 'ready',
  query: 'operating margin',
  top_k: 5,
  result_count: 1,
  authorized_scope: {
    grants: [
      {
        workspace: {
          id: 'tenant-orion',
          slug: 'orion',
          name: 'Orion Capital',
        },
        company_ids: ['company-orion'],
        company_slugs: ['orion-main'],
        query_departments: ['finance', 'shared'],
      },
    ],
  },
  indexing: {
    status: 'ready',
    active_chunk_count: 42,
    indexed_document_count: 7,
    embedding: {
      status: 'ready',
      model: 'nomic-embed-text:v1.5',
      dimensions: 768,
      embedded_chunk_count: 42,
      pending_chunk_count: 0,
      failed_chunk_count: 0,
    },
  },
  evaluation_summary: {
    status: 'complete',
    dataset_name: 'synthetic-retrieval-v1',
    curated_query_count: 8,
    recall_at_5: 0.875,
    expected_top_5_hits: 7,
    authorization_leak_count: 0,
  },
  results: [
    {
      chunk_id: 'chunk-finance-1',
      document_id: 'document-finance-1',
      document_version_id: 'version-finance-2',
      version_number: 2,
      excerpt: 'Operating margin improved to <script>alert("unsafe")</script>.',
      scores: {
        keyword: 0.8125,
        vector: 0.9375,
        final: 0.875,
      },
      source: {
        page_number: null,
        sheet_name: 'Summary',
        row_start: 4,
        row_end: 8,
        cell_start: 'A4',
        cell_end: 'F8',
      },
      citation: {
        chunk_id: 'chunk-finance-1',
        document_id: 'document-finance-1',
        document_version_id: 'version-finance-2',
        document_title: 'orion-finance.xlsx',
        version_number: 2,
        excerpt:
          'Operating margin improved to <script>alert("unsafe")</script>.',
        page_number: null,
        sheet_name: 'Summary',
        row_start: 4,
        row_end: 8,
        cell_start: 'A4',
        cell_end: 'F8',
      },
      document: {
        filename: 'orion-finance.xlsx',
        source_type: 'XLSX',
        document_type: 'FINANCIAL_REPORT',
        reporting_period: 'FY2025',
        tenant_slug: 'orion',
        company_slug: 'orion-main',
        department: 'finance',
        visibility: 'DEPARTMENT_PRIVATE',
        classification: 'FINANCE_ONLY',
      },
    },
  ],
}
