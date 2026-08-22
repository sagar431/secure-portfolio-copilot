import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { AgentApprovalCard } from './AgentApprovalCard'

describe('AgentApprovalCard', () => {
  it('renders an expired approval as inert accessible text', () => {
    const approve = vi.fn()
    render(
      <AgentApprovalCard
        approval={{
          approval_id: '83838383-8383-4383-8383-838383838383',
          run_id: '82828282-8282-4282-8282-828282828282',
          status: 'PENDING',
          action_label: '<script>Search authorized documents</script>',
          safe_explanation: 'Use one allow-listed tool.',
          tool_name: 'portfolio.search_authorized_documents',
          risk_level: 'LOW_READ_ONLY',
          resource_type: 'authorized portfolio documents',
          estimated_cost_class: 'low',
          safe_scope_summary: 'Orion Capital · Finance',
          remaining_budget: { steps: 4, tools: 4 },
          expires_at: '2000-01-01T00:00:00Z',
        }}
        resolving={false}
        onApprove={approve}
        onReject={vi.fn()}
        onStop={vi.fn()}
        onChangeRequest={vi.fn()}
      />,
    )
    expect(screen.getByRole('status')).toHaveTextContent(/expired/i)
    const button = screen.getByRole('button', { name: 'Approve once' })
    expect(button).toBeDisabled()
    fireEvent.click(button)
    expect(approve).not.toHaveBeenCalled()
    expect(document.querySelector('script')).toBeNull()
  })
})
