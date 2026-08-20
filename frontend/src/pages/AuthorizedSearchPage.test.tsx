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
    expect(screen.getByText('chunk-finance-1')).toBeInTheDocument()
    expect(screen.getByText('document-finance-1')).toBeInTheDocument()
    expect(screen.getByText('version-finance-2')).toBeInTheDocument()
    expect(screen.getByText('0.8754')).toBeInTheDocument()
    expect(screen.getByText('orion-finance.xlsx')).toBeInTheDocument()
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
      'Searching the authorized index',
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

  it('shows only the safe denial and request ID and clears previous results', async () => {
    renderPage()
    submitSearch()
    expect(await screen.findByText('chunk-finance-1')).toBeInTheDocument()

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
    const result = (await screen.findByText('chunk-finance-1')).closest(
      'article',
    )
    if (!result) {
      throw new Error('Search result was not rendered')
    }
    expect(within(result).getByText('Version ID')).toBeInTheDocument()
    expect(within(result).getByText('Classification')).toBeInTheDocument()
    expect(within(result).getByText('Source provenance')).toBeInTheDocument()
    expect(within(result).getByText('Cells')).toBeInTheDocument()
  })
})
