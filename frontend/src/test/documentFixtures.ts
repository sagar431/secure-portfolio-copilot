import type {
  DocumentPreviewData,
  DocumentSummary,
  IngestionOptionsData,
} from '../types/documents'

export const ingestionOptions: IngestionOptionsData = {
  tenants: [
    {
      id: 'tenant-orion',
      slug: 'orion',
      name: 'Orion Capital',
      companies: [
        {
          id: 'company-orion',
          slug: 'orion-main',
          name: 'Orion Portfolio Company',
        },
      ],
    },
  ],
  classification_pairs: [
    {
      department: 'finance',
      visibility: 'DEPARTMENT_PRIVATE',
      classification: 'FINANCE_ONLY',
      label: 'Finance only',
    },
    {
      department: 'shared',
      visibility: 'TENANT_SHARED',
      classification: 'TENANT_SHARED',
      label: 'Tenant shared',
    },
  ],
  document_types: [
    {
      value: 'FINANCIAL_REPORT',
      label: 'Financial report',
      reporting_period_required: true,
    },
    {
      value: 'OTHER',
      label: 'Other',
      reporting_period_required: false,
    },
  ],
  limits: {
    max_upload_bytes: 10 * 1024 * 1024,
    extensions: ['.pdf', '.xlsx', '.csv'],
    mime_types: [
      'application/pdf',
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      'text/csv',
    ],
  },
}

export const documentSummary: DocumentSummary = {
  document_id: 'document-orion-board-pack',
  version_id: 'version-orion-board-pack-1',
  version_number: 1,
  filename: 'Orion_FY2025_Board_Pack.pdf',
  checksum: 'a7ff74b627185989b311713a9b44be2bfdb028cb9abcbde6a0240cd343e534be',
  source_type: 'PDF',
  detected_mime_type: 'application/pdf',
  size_bytes: 8851,
  tenant: {
    id: ingestionOptions.tenants[0].id,
    slug: ingestionOptions.tenants[0].slug,
    name: ingestionOptions.tenants[0].name,
  },
  company: ingestionOptions.tenants[0].companies[0],
  department: 'finance',
  visibility: 'DEPARTMENT_PRIVATE',
  classification: 'FINANCE_ONLY',
  document_type: 'FINANCIAL_REPORT',
  reporting_period: 'FY2025',
  status: 'PREVIEW_READY',
  page_count: 2,
  sheet_count: 0,
  row_count: 0,
  cell_count: 0,
  uploader_id: 'user-nora',
  approved_by_user_id: null,
  current_approved_version_id: null,
  warnings: [],
  created_at: '2026-08-21T10:00:00Z',
  ingestion_job_id: 'job-1',
}

export const pdfPreview: DocumentPreviewData = {
  document: documentSummary,
  warnings: [],
  content: {
    kind: 'pdf',
    page_count: 2,
    pages: [
      { page_number: 1, text: 'Orion board overview.' },
      { page_number: 2, text: 'Revenue and EBITDA discussion.' },
    ],
  },
}

export const spreadsheetPreview: DocumentPreviewData = {
  document: {
    ...documentSummary,
    version_id: 'version-orion-financials-1',
    filename: 'Orion_FY2024_FY2025_Financials.xlsx',
    source_type: 'XLSX',
    detected_mime_type:
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    page_count: 0,
    sheet_count: 1,
    row_count: 2,
    cell_count: 4,
  },
  warnings: ['Formula-like cells are displayed as inert text.'],
  content: {
    kind: 'spreadsheet',
    source_type: 'XLSX',
    sheet_count: 1,
    sheets: [
      {
        sheet_index: 0,
        sheet_name: 'P&L',
        row_count: 2,
        column_count: 2,
        rows: [
          {
            row_number: 1,
            cells: [
              {
                coordinate: 'A1',
                value: 'Metric',
                value_kind: 'text',
                formula_like: false,
              },
              {
                coordinate: 'B1',
                value: 'FY2025',
                value_kind: 'text',
                formula_like: false,
              },
            ],
          },
          {
            row_number: 2,
            cells: [
              {
                coordinate: 'A2',
                value: 'Revenue',
                value_kind: 'text',
                formula_like: false,
              },
              {
                coordinate: 'B2',
                value: '=SUM(B3:B4)',
                value_kind: 'formula_text',
                formula_like: true,
              },
            ],
          },
        ],
      },
    ],
  },
}
