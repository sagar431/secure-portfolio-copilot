import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '../api/client'
import * as searchApi from '../api/search'
import { AuthContext, type AuthContextValue } from '../auth/context'
import { authorizedSearchData } from '../test/searchFixtures'
import { AuthorizedSearchPage } from './AuthorizedSearchPage'

vi.mock('../api/search', () => ({
  searchAuthorizedDocuments: vi.fn(),
}))

const authValue: AuthContextValue = {
  status: 'authenticated',
  currentUser: {
    identity: {
      id: 'user-alice',
      email: 'alice@example.com',
      display_name: 'Alice Finance Analyst',
    },
    active_memberships: [
      {
        id: 'membership-alice',
        tenant: {
          id: 'tenant-orion',
          slug: 'orion',
          name: 'Orion Capital',
        },
        role: 'analyst',
        primary_department: 'finance',
      },
    ],
    authorization_scope: {
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
          capabilities: ['QUERY_DOCUMENTS'],
        },
      ],
    },
  },
  accessToken: 'signed-alice-token',
  login: vi.fn(),
  logout: vi.fn(),
}

function renderPage() {
  return render(
    <MemoryRouter>
      <AuthContext.Provider value={authValue}>
        <AuthorizedSearchPage />
      </AuthContext.Provider>
    </MemoryRouter>,
  )
}

function submitSearch(query = 'operating margin') {
  fireEvent.change(screen.getByLabelText('Query'), { target: { value: query } })
  fireEvent.submit(
    screen
      .getByRole('button', { name: 'Search authorized documents' })
      .closest('form')!,
  )
}

describe('AuthorizedSearchPage', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(searchApi.searchAuthorizedDocuments).mockResolvedValue({
      data: authorizedSearchData,
      request_id: 'search-request',
    })
  })

  it('shows active scope and renders only the server-authorized result DTO', async () => {
    renderPage()

    expect(screen.getByText('Alice Finance Analyst')).toBeInTheDocument()
    expect(screen.getByText('finance, shared')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Top results'), {
      target: { value: '3' },
    })
    submitSearch('  operating margin  ')

    await waitFor(() =>
      expect(searchApi.searchAuthorizedDocuments).toHaveBeenCalledWith(
        'signed-alice-token',
        { query: 'operating margin', top_k: 3 },
        expect.any(AbortSignal),
      ),
    )
    expect(screen.getAllByText('chunk-finance-1')).toHaveLength(2)
    expect(screen.getAllByText('document-finance-1')).toHaveLength(2)
    expect(screen.getAllByText('version-finance-2')).toHaveLength(2)
    expect(screen.getByText('0.8125')).toBeInTheDocument()
    expect(screen.getByText('0.9375')).toBeInTheDocument()
    expect(screen.getByText('0.8750')).toBeInTheDocument()
    expect(screen.getAllByText('orion-finance.xlsx')).toHaveLength(2)
    expect(screen.getByText(/financial report/i)).toBeInTheDocument()
    expect(screen.getByText('Summary')).toBeInTheDocument()
    expect(screen.getByText('4–8')).toBeInTheDocument()
    expect(screen.getByText('A4–F8')).toBeInTheDocument()
    expect(
      screen.getByText(
        'Operating margin improved to <script>alert("unsafe")</script>.',
      ),
    ).toBeInTheDocument()
    expect(document.querySelector('script')).toBeNull()
    expect(screen.getByText('Embeddings ready')).toBeInTheDocument()
    expect(screen.getByText(/nomic-embed-text:v1.5/)).toBeInTheDocument()
    expect(screen.getByText('87.5%')).toBeInTheDocument()
    expect(screen.getByText('No authorization leaks')).toBeInTheDocument()
  })

  it('shows loading and then an indexing-aware empty state', async () => {
    let resolveSearch:
      | ((
          value: Awaited<
            ReturnType<typeof searchApi.searchAuthorizedDocuments>
          >,
        ) => void)
      | undefined
    vi.mocked(searchApi.searchAuthorizedDocuments).mockReturnValue(
      new Promise((resolve) => {
        resolveSearch = resolve
      }),
    )
    renderPage()
    submitSearch()

    expect(screen.getByRole('status')).toHaveTextContent(
      'Searching the authorized hybrid index',
    )
    expect(screen.getByLabelText('Query')).toBeDisabled()

    resolveSearch?.({
      data: {
        ...authorizedSearchData,
        status: 'indexing',
        result_count: 0,
        indexing: {
          status: 'indexing',
          active_chunk_count: 0,
          indexed_document_count: 0,
          embedding: {
            ...authorizedSearchData.indexing.embedding,
            status: 'indexing',
            embedded_chunk_count: 0,
            pending_chunk_count: 42,
          },
        },
        results: [],
      },
      request_id: 'indexing-request',
    })

    expect(
      await screen.findByText(/Indexing is still in progress/),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/No authorized results matched this query/),
    ).toBeInTheDocument()
  })

  it('shows safe degraded embedding and not-run evaluation states', async () => {
    vi.mocked(searchApi.searchAuthorizedDocuments).mockResolvedValueOnce({
      data: {
        ...authorizedSearchData,
        status: 'degraded',
        result_count: 0,
        indexing: {
          ...authorizedSearchData.indexing,
          status: 'degraded',
          embedding: {
            ...authorizedSearchData.indexing.embedding,
            status: 'unavailable',
            embedded_chunk_count: 0,
            pending_chunk_count: 42,
          },
        },
        evaluation_summary: { status: 'not_run' },
        results: [],
      },
      request_id: 'degraded-request',
    })
    renderPage()
    submitSearch()

    expect(
      await screen.findByText(/Hybrid retrieval is temporarily degraded/),
    ).toBeInTheDocument()
    expect(screen.getByText('Embeddings unavailable')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Not run' })).toBeInTheDocument()
    expect(
      screen.getByText(/No aggregate evaluation is available/),
    ).toBeInTheDocument()
  })

  it('shows only the safe denial and request ID and clears previous results', async () => {
    renderPage()
    submitSearch()
    expect(await screen.findAllByText('chunk-finance-1')).toHaveLength(2)

    vi.mocked(searchApi.searchAuthorizedDocuments).mockRejectedValueOnce(
      new ApiError(
        'Document query access is not available.',
        403,
        'forbidden',
        'search-denied-request',
      ),
    )
    submitSearch('legal settlement')

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Document query access is not available. Request ID: search-denied-request',
    )
    expect(screen.queryByText('chunk-finance-1')).not.toBeInTheDocument()
  })

  it('does not expose unexpected client error details', async () => {
    vi.mocked(searchApi.searchAuthorizedDocuments).mockRejectedValueOnce(
      new Error('provider stack and sensitive diagnostics'),
    )
    renderPage()
    submitSearch()

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Authorized search could not be completed. Try again.',
    )
    expect(
      screen.queryByText(/provider stack and sensitive diagnostics/),
    ).not.toBeInTheDocument()
  })

  it('rejects a blank query in the form without calling the API', () => {
    renderPage()
    fireEvent.submit(
      screen
        .getByRole('button', { name: 'Search authorized documents' })
        .closest('form')!,
    )

    expect(screen.getByRole('alert')).toHaveTextContent('Enter a search query.')
    expect(searchApi.searchAuthorizedDocuments).not.toHaveBeenCalled()
  })

  it('labels every metadata and provenance field accessibly', async () => {
    renderPage()
    submitSearch()
    const result = (await screen.findAllByText('chunk-finance-1'))[0].closest(
      'article',
    )
    if (!result) {
      throw new Error('Search result was not rendered')
    }
    expect(within(result).getByText('Version ID')).toBeInTheDocument()
    expect(within(result).getByText('Classification')).toBeInTheDocument()
    expect(within(result).getByText('Citation preview')).toBeInTheDocument()
    expect(within(result).getByText('Citation version ID')).toBeInTheDocument()
    expect(within(result).getByText('Cells')).toBeInTheDocument()
  })
})
