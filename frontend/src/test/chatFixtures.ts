import type {
  AgentRunData,
  ConversationData,
  GroundedAnswerData,
} from '../types/chat'

export const conversationData: ConversationData = {
  id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
  title: 'Orion finance review',
  created_at: '2026-08-21T01:00:00Z',
  updated_at: '2026-08-21T02:00:00Z',
}

export const groundedAnswerData: GroundedAnswerData = {
  conversation_id: conversationData.id,
  user_message_id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
  assistant_message_id: 'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
  status: 'grounded',
  answer: 'Operating margin improved. <script>window.unsafe = true</script>',
  claims: [
    {
      text: 'Operating margin improved to 18.4%.',
      citation_ids: ['C1'],
    },
  ],
  citations: [
    {
      citation_id: 'C1',
      document_id: 'dddddddd-dddd-4ddd-8ddd-dddddddddddd',
      document_version_id: 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee',
      chunk_id: 'ffffffff-ffff-4fff-8fff-ffffffffffff',
      document_title: 'orion-finance.xlsx',
      version_number: 2,
      excerpt:
        'Operating margin improved to 18.4%. <img src=x onerror=alert(1)>',
      page_number: null,
      sheet_name: 'Summary',
      row_start: 4,
      row_end: 8,
      cell_start: 'A4',
      cell_end: 'F8',
    },
  ],
  limitations: ['The answer covers the approved reporting period only.'],
  model_name: 'Gemini 3.1 Flash Lite',
  route_reason: 'SIMPLE_LOW_RISK',
  fallback_used: false,
  requested_response_mode: 'auto',
  resolved_response_mode: 'fast',
  input_tokens: 700,
  output_tokens: 140,
  latency_ms: 2100,
  estimated_model_cost_usd: null,
  pricing_snapshot_date: null,
}

export const insufficientAnswerData: GroundedAnswerData = {
  conversation_id: conversationData.id,
  user_message_id: '11111111-1111-4111-8111-111111111111',
  assistant_message_id: '22222222-2222-4222-8222-222222222222',
  status: 'insufficient_evidence',
  answer: 'The authorized documents do not contain enough evidence to answer.',
  claims: [],
  citations: [],
  limitations: ['No supported evidence matched the question.'],
  model_name: null,
  route_reason: null,
  fallback_used: false,
  requested_response_mode: 'auto',
  resolved_response_mode: null,
  input_tokens: null,
  output_tokens: null,
  latency_ms: 12,
  estimated_model_cost_usd: null,
  pricing_snapshot_date: null,
}

export const agentRunData: AgentRunData = {
  conversation_id: conversationData.id,
  user_message_id: '12121212-1212-4121-8121-121212121212',
  assistant_message_id: '23232323-2323-4232-8232-232323232323',
  agent_session_id: '34343434-3434-4343-8343-343434343434',
  terminal_status: 'completed',
  stopping_reason: 'completed',
  answer: groundedAnswerData.answer.replaceAll('C1', 'ev_1'),
  claims: groundedAnswerData.claims.map((claim) => ({
    ...claim,
    citation_ids: ['ev_1'],
  })),
  citations: groundedAnswerData.citations.map((citation) => ({
    ...citation,
    citation_id: 'ev_1',
  })),
  limitations: groundedAnswerData.limitations,
  calculations: [],
  step_count: 1,
  replan_count: 0,
  retry_count: 0,
  trace: [
    {
      event_id: '45454545-4545-4454-8454-454545454545',
      event_type: 'perception',
      action_name: null,
      status: 'completed',
      duration_ms: 14,
      evidence_reference_ids: [],
      reason_code: 'PERCEPTION_COMPLETED',
    },
    {
      event_id: '56565656-5656-4565-8565-565656565656',
      event_type: 'tool',
      action_name: 'portfolio.search_authorized_documents',
      status: 'completed',
      duration_ms: 23,
      evidence_reference_ids: ['ev_1'],
      reason_code: 'TOOL_COMPLETED',
    },
    {
      event_id: '67676767-6767-4676-8676-676767676767',
      event_type: 'terminal',
      action_name: null,
      status: 'completed',
      duration_ms: 0,
      evidence_reference_ids: ['ev_1'],
      reason_code: 'COMPLETED',
    },
  ],
  model_name: 'Gemini 3.7 Flash',
  route_reason: 'AGENTIC_REQUEST',
  requested_response_mode: 'auto',
  resolved_response_mode: 'deep',
}

const calculationCitations = [
  {
    ...groundedAnswerData.citations[0],
    citation_id: 'ev_1',
    chunk_id: '10101010-1010-4010-8010-101010101010',
    row_start: 2,
    row_end: 2,
    cell_start: 'C2',
    cell_end: 'C2',
  },
  {
    ...groundedAnswerData.citations[0],
    citation_id: 'ev_2',
    chunk_id: '20202020-2020-4020-8020-202020202020',
    row_start: 3,
    row_end: 3,
    cell_start: 'C3',
    cell_end: 'C3',
  },
  {
    ...groundedAnswerData.citations[0],
    citation_id: 'ev_3',
    chunk_id: '30303030-3030-4030-8030-303030303030',
    row_start: 4,
    row_end: 4,
    cell_start: 'C4',
    cell_end: 'C4',
  },
]

export const calculationRunData: AgentRunData = {
  ...agentRunData,
  answer:
    'Orion EBITDA margin for FY2025 is 10.00%, calculated by trusted host code.',
  claims: [
    {
      text: 'Orion EBITDA margin for FY2025 is 10.00%.',
      citation_ids: ['ev_1', 'ev_2', 'ev_3'],
    },
  ],
  citations: calculationCitations,
  calculations: [
    {
      calculation_id: '78787878-7878-4787-8787-787878787878',
      metric: 'ebitda_margin',
      company_slug: 'orion-main',
      period: 'FY2025',
      formula:
        '((Revenue - Cost of Goods Sold - Operating Expenses (excl. D&A)) / Revenue) × 100',
      trusted_inputs: [
        {
          name: 'Revenue',
          period: 'FY2025',
          value: 1000,
          unit: 'INR crore',
          citation_id: 'ev_1',
        },
        {
          name: 'Cost of Goods Sold',
          period: 'FY2025',
          value: 650,
          unit: 'INR crore',
          citation_id: 'ev_2',
        },
        {
          name: 'Operating Expenses (excl. D&A)',
          period: 'FY2025',
          value: 250,
          unit: 'INR crore',
          citation_id: 'ev_3',
        },
      ],
      result: 10,
      unit: 'percent',
      citation_ids: ['ev_1', 'ev_2', 'ev_3'],
    },
  ],
  trace: [
    agentRunData.trace[0],
    {
      ...agentRunData.trace[1],
      action_name: 'portfolio.calculate_ebitda_margin',
      evidence_reference_ids: ['ev_1', 'ev_2', 'ev_3'],
      reason_code: 'TOOL_COMPLETED',
    },
    {
      ...agentRunData.trace[2],
      evidence_reference_ids: ['ev_1', 'ev_2', 'ev_3'],
      reason_code: 'DETERMINISTIC_CALCULATION_VALIDATED',
    },
  ],
}
